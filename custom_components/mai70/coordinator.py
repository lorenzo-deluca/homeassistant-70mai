"""Data update coordinator for the 70mai integration."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import ALARM_TYPES, BATTERY_KEY_INDEX, BATTERY_SMART_TYPE, DEFAULT_SCAN_INTERVAL, DOMAIN
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


def _first_present(item: Dict[str, Any], keys: tuple) -> Optional[str]:
    for key in keys:
        value = item.get(key)
        if value is not None:
            return str(value)
    return None


def _local_utc_offset_hours() -> int:
    offset = datetime.now().astimezone().utcoffset()
    return int(offset.total_seconds() // 3600) if offset else 0


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

    async def _async_ensure_logged_in(self) -> None:
        if self.client.token:
            return
        await self.hass.async_add_executor_job(
            self.client.login, self._email, self._plain_password
        )

    async def _async_update_data(self) -> Dict[str, Dict[str, Any]]:
        try:
            await self._async_ensure_logged_in()
            devices = await self.hass.async_add_executor_job(
                self.client.get_all_device_for_user
            )
        except MaiNotAuthenticatedError:
            # Token went stale between polls: force a fresh login and retry once.
            self.client.token = None
            try:
                await self._async_ensure_logged_in()
                devices = await self.hass.async_add_executor_job(
                    self.client.get_all_device_for_user
                )
            except MaiError as exc:
                raise UpdateFailed(f"Re-login failed: {exc}") from exc
        except MaiError as exc:
            raise UpdateFailed(f"getAllDeviceForUser failed: {exc}") from exc

        device_list = devices.get("resultBodyObject") or []
        if not isinstance(device_list, list):
            raise UpdateFailed(
                f"Unexpected getAllDeviceForUser response shape: {device_list!r}"
            )

        now_ms = int(datetime.now().timestamp() * 1000)
        begin_ms = self._last_poll_ms or (now_ms - int(timedelta(days=1).total_seconds() * 1000))

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
            }

        self._last_poll_ms = now_ms
        return result

    async def _async_get_position(self, device_id: str) -> Optional[Dict[str, Any]]:
        try:
            resp = await self.hass.async_add_executor_job(self.client.get_position, device_id)
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
            resp = await self.hass.async_add_executor_job(
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

    async def _async_get_new_alarms(
        self, device_id: str, begin_ms: int, now_ms: int
    ) -> List[Dict[str, Any]]:
        try:
            resp = await self.hass.async_add_executor_job(
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
