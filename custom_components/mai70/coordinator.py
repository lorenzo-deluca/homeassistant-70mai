"""Data update coordinator for the 70mai integration."""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    ALARM_TYPES,
    BATTERY_KEY_INDEX,
    BATTERY_SMART_TYPE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    FIRMWARE_CHECK_BASE_SUBVERSION,
    FIRMWARE_CHECK_BASE_VERSION,
    TOKEN_INVALID_RELOGIN_DELAY,
)
from client70mai import MaiClient
from client70mai.exceptions import MaiError, MaiNotAuthenticatedError

_LOGGER = logging.getLogger(__name__)

# Candidate keys for a device's id/name, in order. "deviceId"/"nickName"
# are the confirmed getAllDeviceForUser fields; the rest are defensive
# fallbacks for an older/different device dict shape.
_DEVICE_ID_KEYS = ("deviceId", "id")
_DEVICE_NAME_KEYS = ("nickName", "ssid", "deviceId")
# get_device_alarm_list()'s item schema isn't confirmed, so the id field
# name is a best-effort guess.
_ALARM_ID_KEYS = ("alarmId", "id")

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


def _local_utc_offset_hours() -> int:
    offset = datetime.now().astimezone().utcoffset()
    return int(offset.total_seconds() // 3600) if offset else 0


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

    async def _async_ensure_logged_in(self) -> None:
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
                "position": await self._async_get_position(device_id),
                "battery_mv": await self._async_get_battery_mv(device_id),
                "new_alarms": await self._async_get_new_alarms(device_id, begin_ms, now_ms),
                "dashcam_detail": await self._async_get_dashcam_detail(device_id),
                "cellular": await self._async_get_cellular_info(device_id),
                "country_code": country_code,
                "firmware": await self._async_get_firmware_info(device_id, device),
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
        }

    async def _async_get_battery_mv(self, device_id: str) -> Optional[int]:
        today = date.today()
        try:
            resp = await self._async_call(
                self.client.get_device_status_history_daily,
                device_id,
                today.year,
                today.month,
                today.day,
                BATTERY_KEY_INDEX,
                BATTERY_SMART_TYPE,
                _local_utc_offset_hours(),
            )
        except MaiError as exc:
            _LOGGER.debug("getDeviceStatusHistoryDaily failed for %s: %s", device_id, exc)
            return None
        samples = resp.get("resultBodyObject")
        if not isinstance(samples, list) or not samples:
            return None
        latest_sample = max(
            (s for s in samples if isinstance(s, dict) and "maxTs" in s),
            key=lambda s: s["maxTs"],
            default=None,
        )
        if latest_sample is None:
            return None
        return latest_sample.get("latest")

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
            resp = await self._async_call(
                self.client.get_device_alarm_list,
                device_id,
                begin_ms,
                now_ms,
                ALARM_TYPES,
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
            new_alarms.append({"alarm_id": alarm_id, "raw": alarm})
        return new_alarms
