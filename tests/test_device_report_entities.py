"""Entities fed by endpoints confirmed with client70mai 0.4.0: dashcam
firmware/SD card (offline getDeviceDetail), cloud storage (UserspaceApi),
lost mode (getLostStatus), plus the quarter-hour timeOffset fix."""
from __future__ import annotations

from typing import Any, Dict, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from client70mai import quarter_hour_offsets
from client70mai.exceptions import MaiConnectionError

from custom_components.mai70.const import DOMAIN

from .conftest import DEVICE_ID, FakeMaiClient, setup_integration

# Anonymized shapes of real responses (see client70mai's docstrings).
OFFLINE_DETAIL = {
    "accountcar": None,
    "device": {"deviceId": DEVICE_ID},
    "simPlugin": None,
    "statisticsList": [
        {"key": "FWversionDate", "value": "1769468400"},
        {"key": "Timestamp", "value": "20260903104649"},
        {"key": "ApkTFStatus", "value": "SDOK"},
        {"key": "bssid", "value": "aa:bb:cc:dd:ee:02"},
        {"key": "FWversion", "value": "1.9.118ww"},
    ],
    "subdeviceList": None,
}
DEVICE_STATS = [
    {
        "deviceChannel": 65001001,
        "deviceId": DEVICE_ID,
        "deviceModule": 65001,
        "deviceType": 65,
        "picCount": 0,
        "picSize": 0,
        "updateTimestamp": 1700000000000,
        "userId": None,
        "videoCount": 6,
        "videoSize": 124875489,
    }
]
SPACE_BRIEF = {"diskSize": 1073741824, "videoCount": 2, "videoSize": 41552299, "userId": 1}


def _state(hass: HomeAssistant, platform: str, unique_id: str):
    entity_id: Optional[str] = er.async_get(hass).async_get_entity_id(platform, DOMAIN, unique_id)
    return hass.states.get(entity_id) if entity_id else None


async def test_dashcam_firmware_and_sd_card(hass: HomeAssistant, fake_client: FakeMaiClient) -> None:
    fake_client.responses["get_offline_device_detail"] = OFFLINE_DETAIL
    await setup_integration(hass, fake_client)

    firmware = _state(hass, "sensor", f"{DEVICE_ID}_dashcam_firmware")
    assert firmware.state == "1.9.118ww"
    assert firmware.attributes["firmware_date"] == "2026-01-26T23:00:00+00:00"
    assert firmware.attributes["report_timestamp"] == "20260903104649"

    sd_card = _state(hass, "sensor", f"{DEVICE_ID}_sd_card")
    assert sd_card.state == "SDOK"


async def test_no_device_report_entities_without_statistics(
    hass: HomeAssistant, fake_client: FakeMaiClient
) -> None:
    fake_client.responses["get_offline_device_detail"] = {**OFFLINE_DETAIL, "statisticsList": []}
    await setup_integration(hass, fake_client)

    assert _state(hass, "sensor", f"{DEVICE_ID}_dashcam_firmware") is None
    assert _state(hass, "sensor", f"{DEVICE_ID}_sd_card") is None


async def test_cloud_storage(hass: HomeAssistant, fake_client: FakeMaiClient) -> None:
    fake_client.responses["get_userspace_device_stats"] = DEVICE_STATS
    fake_client.responses["get_user_space_brief"] = SPACE_BRIEF
    await setup_integration(hass, fake_client)

    state = _state(hass, "sensor", f"{DEVICE_ID}_cloud_storage")
    assert state.attributes["unit_of_measurement"] == "MB"
    assert round(float(state.state), 1) == 124.9
    assert state.attributes["video_count"] == 6
    assert state.attributes["account_quota"] == 1073741824
    # account-level calls: once per poll, not once per device
    assert fake_client.call_count("get_userspace_device_stats") == 1
    assert fake_client.call_count("get_user_space_brief") == 1


async def test_cloud_storage_without_quota(hass: HomeAssistant, fake_client: FakeMaiClient) -> None:
    fake_client.responses["get_userspace_device_stats"] = DEVICE_STATS
    fake_client.responses["get_user_space_brief"] = MaiConnectionError("down")
    await setup_integration(hass, fake_client)

    state = _state(hass, "sensor", f"{DEVICE_ID}_cloud_storage")
    assert state is not None
    assert state.attributes["account_quota"] is None


async def test_no_cloud_storage_for_device_without_files(
    hass: HomeAssistant, fake_client: FakeMaiClient
) -> None:
    fake_client.responses["get_userspace_device_stats"] = [{**DEVICE_STATS[0], "deviceId": "other"}]
    await setup_integration(hass, fake_client)

    assert _state(hass, "sensor", f"{DEVICE_ID}_cloud_storage") is None


async def test_lost_mode(hass: HomeAssistant, fake_client: FakeMaiClient) -> None:
    fake_client.responses["get_lost_status"] = {
        "lost": False,
        "lostSessionId": None,
        "remainingCount": None,
    }
    await setup_integration(hass, fake_client)

    assert _state(hass, "binary_sensor", f"{DEVICE_ID}_lost_mode").state == "off"


async def test_no_lost_mode_entity_without_data(hass: HomeAssistant, fake_client: FakeMaiClient) -> None:
    await setup_integration(hass, fake_client)
    assert _state(hass, "binary_sensor", f"{DEVICE_ID}_lost_mode") is None


async def test_battery_history_uses_quarter_hour_offsets(
    hass: HomeAssistant, fake_client: FakeMaiClient
) -> None:
    await setup_integration(hass, fake_client)

    calls = [args for name, args in fake_client.calls if name == "get_device_status_history_daily"]
    assert calls
    # (device_id, year, month, day, key_index, smart_type, tz, dst)
    assert calls[0][6:] == quarter_hour_offsets()
