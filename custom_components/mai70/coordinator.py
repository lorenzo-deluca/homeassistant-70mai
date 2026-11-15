"""Data update coordinators for the 70mai integration."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    BATTERY_KEY_INDEX,
    BATTERY_SMART_TYPE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    FIRMWARE_CHECK_BASE_SUBVERSION,
    FIRMWARE_CHECK_BASE_VERSION,
    POSITION_ACTIVE_MAX_AGE,
    POSITION_SCAN_INTERVAL_ACTIVE,
    POSITION_SCAN_INTERVAL_IDLE,
    TOKEN_INVALID_RELOGIN_DELAY,
)
from client70mai import MaiClient, quarter_hour_offsets
from client70mai.exceptions import MaiError, MaiNotAuthenticatedError

_LOGGER = logging.getLogger(__name__)

# Candidate keys for a device's id/name, in order. "deviceId"/"nickName"
# are the confirmed getAllDeviceForUser fields; the rest are defensive
# fallbacks for an older/different device dict shape.
_DEVICE_ID_KEYS = ("deviceId", "id")
_DEVICE_NAME_KEYS = ("nickName", "ssid", "deviceId")
# get_device_alarm_list()'s confirmed item schema uses "id"; "alarmId" is
# kept as a defensive fallback only.
_ALARM_ID_KEYS = ("id", "alarmId")

# get_all_device_for_user() pagination: page size to request, and a hard
# cap on the number of pages fetched per poll so a cursor/API bug can't
# turn this into an infinite loop.
_DEVICE_PAGE_COUNT = 50
_MAX_DEVICE_PAGES = 50

# 70mai's API only allows one active session per account: it doesn't
# reject a stale token client-side, it hands back this HTTP-200 error
# envelope instead. errorCode 500001 is the one confirmed capture (see
# client70mai.client.MaiClient.report_app_active's docstring, observed
# errorMessage "token无效" i.e. "invalid token"); matching "token" in the
# message too is an unconfirmed but reasonable fallback for the same
# condition under a different errorCode.
_TOKEN_INVALID_ERROR_CODE = 500001


def _first_present(item: Dict[str, Any], keys: tuple) -> Optional[str]:
    for key in keys:
        value = item.get(key)
        if value is not None:
            return str(value)
    return None


def _is_session_invalidated(resp: Any) -> bool:
    if not isinstance(resp, dict) or not resp.get("error"):
        return False
    if resp.get("errorCode") == _TOKEN_INVALID_ERROR_CODE:
        return True
    return "token" in str(resp.get("errorMessage", "")).lower()


class Mai70Coordinator(DataUpdateCoordinator):
    """Polls the 70mai cloud API for every device bound to one account."""

    def __init__(
        self, hass: HomeAssistant, client: MaiClient, email: str, plain_password: str
    ) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN, update_interval=DEFAULT_SCAN_INTERVAL
        )
        self.client = client
        self._email = email
        self._plain_password = plain_password
        self._last_poll_ms: Optional[int] = None
        self._seen_alarm_ids: Dict[str, set] = {}
        # monotonic timestamp of the last detected session invalidation
        # (see _on_session_invalidated), or None if the session is fine.
        self._token_invalid_since: Optional[float] = None
        # The position coordinator shares this client, so both can be
        # mid-update at once. Every API call and login goes through this
        # lock: MaiClient isn't documented as thread-safe (one shared
        # requests.Session, and a millisecond "ts" two simultaneous calls
        # could duplicate), and two concurrent logins would each mint a new
        # token while 70mai keeps only one session per account alive - the
        # second login would invalidate the first.
        self._api_lock = asyncio.Lock()
        self.position_coordinator = Mai70PositionCoordinator(hass, self)

    async def _async_ensure_logged_in(self) -> None:
        async with self._api_lock:
            if self.client.token:
                return
            if self._token_invalid_since is not None:
                remaining = TOKEN_INVALID_RELOGIN_DELAY.total_seconds() - (
                    time.monotonic() - self._token_invalid_since
                )
                if remaining > 0:
                    raise MaiNotAuthenticatedError(
                        "Waiting "
                        f"{remaining:.0f}s more before logging back in after 70mai "
                        "invalidated this session (see the earlier warning) - "
                        "logging in again too soon would just kick out whatever "
                        "else is currently using the account."
                    )
            await self.hass.async_add_executor_job(
                self.client.login, self._email, self._plain_password
            )
            if self._token_invalid_since is not None:
                _LOGGER.warning(
                    "70mai login succeeded again after the earlier session "
                    "invalidation; back to polling normally."
                )
                self._token_invalid_since = None

    def _on_session_invalidated(self, resp: Dict[str, Any]) -> None:
        self.client.token = None
        if self._token_invalid_since is not None:
            return
        self._token_invalid_since = time.monotonic()
        _LOGGER.warning(
            "70mai reported this integration's session as invalid "
            "(errorCode=%s, errorMessage=%r). 70mai's cloud API only allows "
            "one active session per account, so this almost always means "
            "the 70mai mobile app was just opened/logged in and kicked this "
            "integration out, not an integration bug. Waiting %s before "
            "logging back in, so the integration doesn't immediately kick "
            "the app back out in turn.",
            resp.get("errorCode"),
            resp.get("errorMessage"),
            TOKEN_INVALID_RELOGIN_DELAY,
        )

    async def _async_call(self, func: Callable[..., Dict[str, Any]], *args: Any) -> Dict[str, Any]:
        """Run one client70mai call, raising MaiNotAuthenticatedError if
        70mai's response says this session's token is no longer valid
        (see _on_session_invalidated) on top of whatever MaiError the
        call itself can already raise.
        """
        async with self._api_lock:
            resp = await self.hass.async_add_executor_job(func, *args)
        if _is_session_invalidated(resp):
            self._on_session_invalidated(resp)
            raise MaiNotAuthenticatedError(
                f"70mai invalidated this session (errorCode={resp.get('errorCode')!r})"
            )
        return resp

    async def _async_update_data(self) -> Dict[str, Dict[str, Any]]:
        device_list = await self._async_get_all_devices()

        now_ms = int(datetime.now().timestamp() * 1000)
        begin_ms = self._last_poll_ms or (now_ms - int(timedelta(days=1).total_seconds() * 1000))
        country_code = await self._async_get_country_code()
        cloud_storage = await self._async_get_cloud_storage()

        result: Dict[str, Dict[str, Any]] = {}
        for device in device_list:
            if not isinstance(device, dict):
                continue
            device_id = _first_present(device, _DEVICE_ID_KEYS)
            if not device_id:
                _LOGGER.debug("Skipping device with no recognizable id: %r", device)
                continue
            result[device_id] = {
                "meta": device,
                "name": _first_present(device, _DEVICE_NAME_KEYS) or device_id,
                # No "position" here: Mai70PositionCoordinator polls it.
                **await self._async_get_battery(device_id),
                "new_alarms": await self._async_get_new_alarms(device_id, begin_ms, now_ms),
                "dashcam_detail": await self._async_get_dashcam_detail(device_id),
                "cellular": await self._async_get_cellular_info(device_id),
                "country_code": country_code,
                "firmware": await self._async_get_firmware_info(device_id, device),
                "network_status": await self._async_get_network_status(device_id),
                "device_switch": await self._async_get_device_switch(device_id),
                "sim_out_power": await self._async_get_sim_out_power(device_id),
                "device_report": await self._async_get_device_report(device_id),
                "lost_mode": await self._async_get_lost_mode(device_id),
                "cloud_storage": cloud_storage.get(device_id),
            }

        self._last_poll_ms = now_ms
        return result

    async def _async_get_device_page(
        self, last_bind_time: Optional[int]
    ) -> Dict[str, Any]:
        try:
            return await self._async_call(
                self.client.get_all_device_for_user, last_bind_time, _DEVICE_PAGE_COUNT
            )
        except MaiNotAuthenticatedError:
            # Token went stale (naturally, or just invalidated - either way
            # self.client.token is None now): force a fresh login and retry
            # once. If a session invalidation was just detected, this login
            # itself will raise (see _async_ensure_logged_in's cooldown
            # check) instead of hammering 70mai with an immediate re-login.
            try:
                await self._async_ensure_logged_in()
                return await self._async_call(
                    self.client.get_all_device_for_user,
                    last_bind_time,
                    _DEVICE_PAGE_COUNT,
                )
            except MaiError as exc:
                raise UpdateFailed(f"Re-login failed: {exc}") from exc

    async def _async_get_all_devices(self) -> List[Dict[str, Any]]:
        try:
            await self._async_ensure_logged_in()
        except MaiError as exc:
            raise UpdateFailed(str(exc)) from exc
        devices: List[Dict[str, Any]] = []
        last_bind_time: Optional[int] = None
        for _ in range(_MAX_DEVICE_PAGES):
            try:
                resp = await self._async_get_device_page(last_bind_time)
            except MaiError as exc:
                raise UpdateFailed(f"getAllDeviceForUser failed: {exc}") from exc

            page = resp.get("resultBodyObject") or []
            if not isinstance(page, list):
                raise UpdateFailed(
                    f"Unexpected getAllDeviceForUser response shape: {page!r}"
                )
            devices.extend(device for device in page if isinstance(device, dict))

            if len(page) < _DEVICE_PAGE_COUNT:
                break
            last_bind_time = page[-1].get("bindTime")
            if last_bind_time is None:
                # No cursor to advance with; stop rather than re-fetch the
                # same page forever.
                break
        return devices

    async def _async_get_country_code(self) -> Optional[str]:
        try:
            resp = await self._async_call(self.client.get_user_country_code)
        except MaiError as exc:
            _LOGGER.debug("getUserCountryCode failed: %s", exc)
            return None
        body = resp.get("resultBodyObject")
        return body.get("countryCode") if isinstance(body, dict) else None

    async def _async_get_position(self, device_id: str) -> Optional[Dict[str, Any]]:
        try:
            resp = await self._async_call(self.client.get_position, device_id)
        except MaiError as exc:
            _LOGGER.debug("getPosition failed for %s (likely no GPS): %s", device_id, exc)
            return None
        body = resp.get("resultBodyObject")
        if not isinstance(body, dict):
            return None
        position = body.get("position")
        if not isinstance(position, dict):
            return None
        try:
            lat = float(position["coordinatesLat"])
            lng = float(position["coordinatesLng"])
        except (KeyError, TypeError, ValueError):
            return None
        return {
            "latitude": lat,
            "longitude": lng,
            "last_update_time": position.get("lastUpdateTime"),
            # "status"'s meaning isn't documented; passed through raw.
            "status": body.get("status"),
            "park_pic_url": position.get("parkPicUrl"),
            "park_pic_last_update_time": position.get("parkPicLastUpdateTime"),
            "parking_photo_switch": position.get("parkingPhotoSwitch"),
        }

    async def _async_get_battery(self, device_id: str) -> Dict[str, Optional[int]]:
        """{"battery_mv", "battery_ts"} of the newest battery-voltage
        sample, both None when there is none.

        The history is per calendar day, and a dashcam only reports while
        it's powered: a parked car can go a whole day (or every early
        morning, until the first drive) without a sample. So when today
        has none, yesterday's newest sample is used instead, and its
        timestamp is exposed so a stale value is recognisable as such.
        """
        today = date.today()
        for day in (today, today - timedelta(days=1)):
            sample = await self._async_get_latest_battery_sample(device_id, day)
            if sample is not None:
                return {
                    "battery_mv": sample.get("latest"),
                    "battery_ts": sample.get("latestTs") or sample.get("maxTs"),
                }
        return {"battery_mv": None, "battery_ts": None}

    async def _async_get_latest_battery_sample(
        self, device_id: str, day: date
    ) -> Optional[Dict[str, Any]]:
        try:
            resp = await self._async_call(
                self.client.get_device_status_history_daily,
                device_id,
                day.year,
                day.month,
                day.day,
                BATTERY_KEY_INDEX,
                BATTERY_SMART_TYPE,
                # Quarter-hours, not hours (client70mai >= 0.4.0 docs): the
                # day boundaries are computed from this offset.
                *quarter_hour_offsets(),
            )
        except MaiError as exc:
            _LOGGER.debug("getDeviceStatusHistoryDaily failed for %s: %s", device_id, exc)
            return None
        samples = resp.get("resultBodyObject")
        if not isinstance(samples, list):
            return None
        # Newest bucket by its "latest" reading's own timestamp (maxTs for
        # buckets without one), skipping buckets with no reading at all.
        return max(
            (
                s
                for s in samples
                if isinstance(s, dict)
                and s.get("latest") is not None
                and (s.get("latestTs") or s.get("maxTs")) is not None
            ),
            key=lambda s: s.get("latestTs") or s["maxTs"],
            default=None,
        )

    async def _async_get_dashcam_detail(self, device_id: str) -> Optional[Dict[str, Any]]:
        try:
            resp = await self._async_call(self.client.get_dashcam_detail, device_id)
        except MaiError as exc:
            _LOGGER.debug("getDashcamDetail failed for %s: %s", device_id, exc)
            return None
        body = resp.get("resultBodyObject")
        if not isinstance(body, dict):
            return None
        device = body.get("device")
        return {
            "device_status": body.get("deviceStatus"),
            "sim_plugin_active_status": body.get("simPluginActiveStatus"),
            "geofence_active_status": body.get("geofenceActiveStatus"),
            "report_time": device.get("reportTime") if isinstance(device, dict) else None,
        }

    async def _async_get_cellular_info(self, device_id: str) -> Optional[Dict[str, Any]]:
        try:
            resp = await self._async_call(self.client.get_sim_plugin_detail, device_id)
        except MaiError as exc:
            _LOGGER.debug(
                "getSimPluginDetail failed for %s (likely no cellular add-on): %s", device_id, exc
            )
            return None
        body = resp.get("resultBodyObject")
        if not isinstance(body, dict):
            return None
        software_version = body.get("pluginSoftwareVersion")
        if not software_version:
            return None
        return {
            "software_version": software_version,
            "sub_software_version": body.get("pluginSubSoftwareVersion"),
            "imei": body.get("imei"),
            "plugin_device_id": body.get("pluginDeviceId"),
            "is_beta_device": body.get("isBetaDevice"),
        }

    async def _async_get_network_status(self, device_id: str) -> Optional[Dict[str, Any]]:
        """getDashcamStatus is a separate, smaller endpoint from
        getDashcamDetail - CONFIRMED response: {"status", "allowPullAlive",
        "deviceNetworkLevel"}. "status"/"allowPullAlive" meanings aren't
        documented (and may or may not overlap with getDashcamDetail's own
        "deviceStatus"), so they're passed through raw; deviceNetworkLevel
        is the one field with an obvious, useful meaning (signal level).
        """
        try:
            resp = await self._async_call(self.client.get_dashcam_status, device_id)
        except MaiError as exc:
            _LOGGER.debug("getDashcamStatus failed for %s: %s", device_id, exc)
            return None
        body = resp.get("resultBodyObject")
        if not isinstance(body, dict) or body.get("deviceNetworkLevel") is None:
            return None
        return {
            "network_level": body.get("deviceNetworkLevel"),
            "status": body.get("status"),
            "allow_pull_alive": body.get("allowPullAlive"),
        }

    async def _async_get_device_switch(self, device_id: str) -> Optional[Dict[str, Any]]:
        try:
            resp = await self._async_call(self.client.get_device_switch, device_id)
        except MaiError as exc:
            _LOGGER.debug("getDeviceSwitch failed for %s: %s", device_id, exc)
            return None
        body = resp.get("resultBodyObject")
        if not isinstance(body, dict) or body.get("monitorVedioUpload") is None:
            return None
        return {
            "monitor_video_upload": bool(body.get("monitorVedioUpload")),
            "details": body.get("details"),
        }

    async def _async_get_sim_out_power(self, device_id: str) -> Optional[bool]:
        """Whether the SIM/cellular add-on can supply power to keep the
        dashcam running (e.g. for parking-mode surveillance) independent
        of the car battery. Only meaningful for devices with that add-on,
        so absence of a boolean result is treated like "no cellular
        add-on" (same empirical gating as the other SIM-derived entities).
        """
        try:
            resp = await self._async_call(self.client.sim_plugin_support_out_power, device_id)
        except MaiError as exc:
            _LOGGER.debug("simPluginSupportOutPower failed for %s: %s", device_id, exc)
            return None
        body = resp.get("resultBodyObject")
        return bool(body) if isinstance(body, bool) else None

    async def _async_get_device_report(self, device_id: str) -> Optional[Dict[str, Any]]:
        """The dashcam's own last status report, from
        offlineDeviceApi/V2/getDeviceDetail's confirmed statisticsList
        (despite "offline" in the path, it answers for cloud-connected
        devices too). The only source of the dashcam's OWN firmware
        version and SD-card status; returns None without a FWversion or
        ApkTFStatus entry.
        """
        try:
            resp = await self._async_call(self.client.get_offline_device_detail, device_id)
        except MaiError as exc:
            _LOGGER.debug("getDeviceDetail (offline) failed for %s: %s", device_id, exc)
            return None
        body = resp.get("resultBodyObject")
        stats = body.get("statisticsList") if isinstance(body, dict) else None
        if not isinstance(stats, list):
            return None
        values = {
            item["key"]: item.get("value")
            for item in stats
            if isinstance(item, dict) and isinstance(item.get("key"), str)
        }
        if values.get("FWversion") is None and values.get("ApkTFStatus") is None:
            return None
        return {
            "firmware_version": values.get("FWversion"),
            # epoch seconds, as a string
            "firmware_date": values.get("FWversionDate"),
            "sd_status": values.get("ApkTFStatus"),
            # YYYYMMDDhhmmss, presumably when the dashcam last reported
            "report_timestamp": values.get("Timestamp"),
        }

    async def _async_get_lost_mode(self, device_id: str) -> Optional[bool]:
        """Anti-theft lost mode, from getLostStatus's confirmed "lost"."""
        try:
            resp = await self._async_call(self.client.get_lost_status, device_id)
        except MaiError as exc:
            _LOGGER.debug("getLostStatus failed for %s: %s", device_id, exc)
            return None
        body = resp.get("resultBodyObject")
        lost = body.get("lost") if isinstance(body, dict) else None
        return lost if isinstance(lost, bool) else None

    async def _async_get_cloud_storage(self) -> Dict[str, Dict[str, Any]]:
        """{device_id: usage} from UserspaceApi/getDeviceStats (confirmed,
        bytes), each with the account quota from getUserSpaceBrief's
        diskSize. Both are account-level calls, made once per poll."""
        try:
            resp = await self._async_call(self.client.get_userspace_device_stats)
        except MaiError as exc:
            _LOGGER.debug("UserspaceApi getDeviceStats failed: %s", exc)
            return {}
        devices = resp.get("resultBodyObject")
        if not isinstance(devices, list):
            return {}

        quota: Optional[int] = None
        try:
            brief = (
                await self._async_call(self.client.get_user_space_brief)
            ).get("resultBodyObject")
        except MaiError as exc:
            _LOGGER.debug("getUserSpaceBrief failed: %s", exc)
            brief = None
        if isinstance(brief, dict) and isinstance(brief.get("diskSize"), int):
            quota = brief["diskSize"]

        result: Dict[str, Dict[str, Any]] = {}
        for item in devices:
            if not isinstance(item, dict) or not item.get("deviceId"):
                continue
            if not isinstance(item.get("videoSize"), int):
                continue
            result[str(item["deviceId"])] = {
                "video_size": item["videoSize"],
                "video_count": item.get("videoCount"),
                "pic_size": item.get("picSize"),
                "pic_count": item.get("picCount"),
                "updated": item.get("updateTimestamp"),
                "quota": quota,
            }
        return result

    async def _async_get_firmware_info(
        self, device_id: str, device_meta: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """resultBodyObject.version is the dashcam's current firmware
        version (confirmed against a real device), not the latest one
        published by 70mai - checkNewRomFromApp reports the device's own
        current firmware regardless of the base_version/base_subversion
        passed in the request.
        """
        # getAllDeviceForUser has no "category" field distinct from "type";
        # "type" is reused as the checkNewRomFromApp deviceCategory here as
        # a best-effort guess, not a confirmed mapping. A wrong guess just
        # makes the call fail below rather than surface bad data.
        device_module = device_meta.get("module")
        device_type = device_meta.get("type")
        device_channel = device_meta.get("channel")
        if device_module is None or device_type is None or device_channel is None:
            return None
        try:
            resp = await self._async_call(
                self.client.check_new_rom_from_app,
                device_id,
                device_module,
                device_type,
                FIRMWARE_CHECK_BASE_VERSION,
                device_type,
                device_channel,
                FIRMWARE_CHECK_BASE_SUBVERSION,
            )
        except MaiError as exc:
            _LOGGER.debug("checkNewRomFromApp failed for %s: %s", device_id, exc)
            return None
        body = resp.get("resultBodyObject")
        if not isinstance(body, dict):
            return None
        version = body.get("version")
        if not version:
            return None
        return {
            "version": version,
            "sub_version": body.get("subVersion"),
            "desc": body.get("desc"),
            "release_time": body.get("releaseTime"),
            "forced": body.get("forced"),
            "file_size": body.get("fileSize"),
        }

    async def _async_get_new_alarms(
        self, device_id: str, begin_ms: int, now_ms: int
    ) -> List[Dict[str, Any]]:
        try:
            # No alarm_types filter: 70mai's own app doesn't filter its
            # alarm-list screen by type either, and the confirmed observed
            # types (101 collision, 104/105/107) don't match the guessed
            # [105, 108] this used to send - that guess risked silently
            # dropping real alarms like collisions (101).
            resp = await self._async_call(
                self.client.get_device_alarm_list,
                device_id,
                begin_ms,
                now_ms,
            )
        except MaiError as exc:
            _LOGGER.debug("getDeviceAlarmList failed for %s: %s", device_id, exc)
            return []
        alarms = resp.get("resultBodyObject")
        if not isinstance(alarms, list):
            return []

        seen = self._seen_alarm_ids.setdefault(device_id, set())
        new_alarms = []
        for alarm in alarms:
            if not isinstance(alarm, dict):
                continue
            alarm_id = _first_present(alarm, _ALARM_ID_KEYS)
            if alarm_id is None or alarm_id in seen:
                continue
            seen.add(alarm_id)
            new_alarms.append(
                {
                    "alarm_id": alarm_id,
                    # alramType's exact meaning per code isn't confirmed
                    # (101 is a collision alarm, seen with GPS + video; the
                    # rest are unconfirmed guesses), so the code is passed
                    # through as-is rather than mapped to a label.
                    "alarm_type": alarm.get("alramType"),
                    "happen_time": alarm.get("happenTime"),
                    "latitude": alarm.get("coordinatesLat"),
                    "longitude": alarm.get("coordinatesLng"),
                    "picture_url": alarm.get("pictureUrl"),
                    "video_url": alarm.get("videoUrl"),
                    "cover_url": alarm.get("coverUrl"),
                    "raw": alarm,
                }
            )
        return new_alarms


def _position_scan_interval(
    data: Dict[str, Dict[str, Any]], now_ms: float
) -> timedelta:
    """POSITION_SCAN_INTERVAL_ACTIVE while any device's position is fresh
    (it's driving and pushing updates to 70mai's cloud), else
    POSITION_SCAN_INTERVAL_IDLE. See const.py for why lastUpdateTime's age
    is the signal rather than getPosition's undocumented "status".
    """
    max_age_ms = POSITION_ACTIVE_MAX_AGE.total_seconds() * 1000
    for device in data.values():
        last_update = (device.get("position") or {}).get("last_update_time")
        if isinstance(last_update, (int, float)) and now_ms - last_update <= max_age_ms:
            return POSITION_SCAN_INTERVAL_ACTIVE
    return POSITION_SCAN_INTERVAL_IDLE


class Mai70PositionCoordinator(DataUpdateCoordinator):
    """Polls only getPosition, more often than Mai70Coordinator and
    adaptively (see _position_scan_interval).

    A separate coordinator rather than refreshing position inside
    Mai70Coordinator more often: every listener of a coordinator is
    notified on each of its updates (the alarm event entity, for one,
    would re-fire its new_alarms), and re-fetching the whole ~10-endpoint
    payload every minute just for the position would be wasteful. Device
    discovery, login and the session-invalidation cooldown all stay with
    Mai70Coordinator; this one only reuses them.

    data: {device_id: {"name": str, "position": Optional[dict]}} - the
    same "name"/"position" keys Mai70Coordinator's own data used to
    carry, so the entities reading it (device_tracker, image) work with
    either.
    """

    def __init__(self, hass: HomeAssistant, main: Mai70Coordinator) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_position",
            update_interval=POSITION_SCAN_INTERVAL_IDLE,
            # Don't wake the tracker/image entities when nothing moved.
            always_update=False,
        )
        self._main = main

    async def _async_update_data(self) -> Dict[str, Dict[str, Any]]:
        try:
            await self._main._async_ensure_logged_in()
        except MaiError as exc:
            raise UpdateFailed(str(exc)) from exc

        previous = self.data or {}
        result: Dict[str, Dict[str, Any]] = {}
        for device_id, device in (self._main.data or {}).items():
            position = await self._main._async_get_position(device_id)
            if position is None:
                # A failed/empty getPosition (a transient error is more
                # likely now that this polls every minute) keeps the last
                # known fix instead of blanking the tracker; its
                # last_update_time still says how old it is.
                position = (previous.get(device_id) or {}).get("position")
            result[device_id] = {
                "name": device.get("name", device_id),
                "position": position,
            }

        if not self._main.client.token:
            # 70mai invalidated the session mid-poll (_async_get_position
            # swallows that like any other MaiError): don't report the
            # possibly-stale positions as a successful update.
            raise UpdateFailed("70mai invalidated this session during the position poll")

        interval = _position_scan_interval(result, time.time() * 1000)
        if interval != self.update_interval:
            _LOGGER.debug("Position poll interval changed to %s", interval)
            self.update_interval = interval
        return result
