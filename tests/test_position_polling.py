"""Tests for the dedicated, adaptive getPosition poll
(coordinator.Mai70PositionCoordinator) and the API lock it shares with the
main coordinator."""
from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Optional

import pytest
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from client70mai.exceptions import MaiConnectionError

from custom_components.mai70.const import (
    DOMAIN,
    POSITION_ACTIVE_MAX_AGE,
    POSITION_SCAN_INTERVAL_ACTIVE,
    POSITION_SCAN_INTERVAL_IDLE,
)
from custom_components.mai70.coordinator import Mai70Coordinator, _position_scan_interval

from .conftest import DEVICE_ID, FakeMaiClient, position_body, setup_integration

# Request ts of the "driving" Proxyman capture; lastUpdateTime was 11s
# older. The "parked" capture's position was ~604s old.
NOW_MS = 1_789_318_035_096
MAX_AGE_MS = int(POSITION_ACTIVE_MAX_AGE.total_seconds() * 1000)
STALE_AGE_S = POSITION_ACTIVE_MAX_AGE.total_seconds() + 60

SESSION_INVALID = {
    "error": True,
    "errorCode": 500001,
    "errorMessage": "token无效",
    "resultBodyObject": None,
}


def _fix(age_ms: Optional[int]) -> dict:
    return {"position": {"last_update_time": None if age_ms is None else NOW_MS - age_ms}}


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        pytest.param({"a": _fix(11_000)}, POSITION_SCAN_INTERVAL_ACTIVE, id="driving"),
        pytest.param({"a": _fix(MAX_AGE_MS)}, POSITION_SCAN_INTERVAL_ACTIVE, id="at-max-age"),
        pytest.param({"a": _fix(MAX_AGE_MS + 1)}, POSITION_SCAN_INTERVAL_IDLE, id="past-max-age"),
        pytest.param({"a": _fix(604_000)}, POSITION_SCAN_INTERVAL_IDLE, id="parked"),
        pytest.param({"a": _fix(None)}, POSITION_SCAN_INTERVAL_IDLE, id="no-timestamp"),
        pytest.param({"a": {"position": None}}, POSITION_SCAN_INTERVAL_IDLE, id="no-position"),
        pytest.param({}, POSITION_SCAN_INTERVAL_IDLE, id="no-devices"),
        pytest.param(
            {"parked": _fix(604_000), "driving": _fix(11_000)},
            POSITION_SCAN_INTERVAL_ACTIVE,
            id="any-device-driving",
        ),
    ],
)
def test_position_scan_interval(data: dict, expected: timedelta) -> None:
    assert _position_scan_interval(data, NOW_MS) == expected


def _main(hass: HomeAssistant, entry) -> Mai70Coordinator:
    return hass.data[DOMAIN][entry.entry_id]


def _entity_id(hass: HomeAssistant, domain: str, unique_id: str) -> Optional[str]:
    return er.async_get(hass).async_get_entity_id(domain, DOMAIN, unique_id)


def _tracker_id(hass: HomeAssistant, device_id: str = DEVICE_ID) -> Optional[str]:
    return _entity_id(hass, "device_tracker", f"{device_id}_position")


async def _advance(hass: HomeAssistant, delta: timedelta) -> None:
    """Fire every timer due within `delta` (plus a second for the
    coordinator's sub-second scheduling jitter) from now, and wait for the
    refreshes they start (coordinators run them as background tasks)."""
    async_fire_time_changed(hass, dt_util.utcnow() + delta + timedelta(seconds=1))
    await hass.async_block_till_done(wait_background_tasks=True)


def _non_position_calls(client: FakeMaiClient) -> int:
    return sum(1 for name, _ in client.calls if name != "get_position")


async def test_tracker_is_fed_by_position_poll_only(
    hass: HomeAssistant, fake_client: FakeMaiClient
) -> None:
    entry = await setup_integration(hass, fake_client)
    main = _main(hass, entry)

    # Only the position coordinator calls getPosition; the main one
    # doesn't carry a "position" key at all anymore.
    assert fake_client.call_count("get_position") == 1
    assert "position" not in main.data[DEVICE_ID]

    state = hass.states.get(_tracker_id(hass))
    assert state.attributes["latitude"] == pytest.approx(45.676380)
    assert state.attributes["longitude"] == pytest.approx(9.207113)

    other_calls = _non_position_calls(fake_client)
    fake_client.positions[DEVICE_ID] = position_body(lat="45.700000", lng="9.300000")
    await _advance(hass, POSITION_SCAN_INTERVAL_ACTIVE)

    state = hass.states.get(_tracker_id(hass))
    assert state.attributes["latitude"] == pytest.approx(45.7)
    assert state.attributes["longitude"] == pytest.approx(9.3)
    assert fake_client.call_count("get_position") == 2
    # The position poll didn't drag the main coordinator's ~10 other
    # endpoints (or its listeners, e.g. the alarm event) along with it.
    assert _non_position_calls(fake_client) == other_calls


async def test_interval_follows_position_freshness(
    hass: HomeAssistant, fake_client: FakeMaiClient
) -> None:
    entry = await setup_integration(hass, fake_client)
    position_coordinator = _main(hass, entry).position_coordinator
    assert position_coordinator.update_interval == POSITION_SCAN_INTERVAL_ACTIVE

    # Car parks: lastUpdateTime stops advancing.
    fake_client.positions[DEVICE_ID] = position_body(age_s=STALE_AGE_S)
    await _advance(hass, POSITION_SCAN_INTERVAL_ACTIVE)
    assert fake_client.call_count("get_position") == 2
    assert position_coordinator.update_interval == POSITION_SCAN_INTERVAL_IDLE

    # Car drives off again: not noticed before the idle interval elapses...
    fake_client.positions[DEVICE_ID] = position_body(age_s=5)
    await _advance(hass, POSITION_SCAN_INTERVAL_ACTIVE)
    assert fake_client.call_count("get_position") == 2

    # ...but switches back to the fast interval once it does.
    await _advance(hass, POSITION_SCAN_INTERVAL_IDLE)
    assert fake_client.call_count("get_position") == 3
    assert position_coordinator.update_interval == POSITION_SCAN_INTERVAL_ACTIVE


async def test_failed_poll_keeps_last_known_position(
    hass: HomeAssistant, fake_client: FakeMaiClient
) -> None:
    await setup_integration(hass, fake_client)

    fake_client.positions[DEVICE_ID] = MaiConnectionError("network down")
    await _advance(hass, POSITION_SCAN_INTERVAL_ACTIVE)

    assert fake_client.call_count("get_position") == 2
    state = hass.states.get(_tracker_id(hass))
    assert state.state != STATE_UNAVAILABLE
    assert state.attributes["latitude"] == pytest.approx(45.676380)
    assert state.attributes["longitude"] == pytest.approx(9.207113)


async def test_device_without_position_gets_no_tracker(
    hass: HomeAssistant, fake_client: FakeMaiClient
) -> None:
    fake_client.positions[DEVICE_ID] = None
    await setup_integration(hass, fake_client)

    assert _tracker_id(hass) is None


async def test_session_invalidated_during_position_poll(
    hass: HomeAssistant, fake_client: FakeMaiClient
) -> None:
    entry = await setup_integration(hass, fake_client)
    position_coordinator = _main(hass, entry).position_coordinator
    assert fake_client.login_calls == 1

    # The 70mai app logged in and kicked this integration's session out.
    fake_client.positions[DEVICE_ID] = SESSION_INVALID
    await _advance(hass, POSITION_SCAN_INTERVAL_ACTIVE)

    assert fake_client.token is None
    assert not position_coordinator.last_update_success
    assert hass.states.get(_tracker_id(hass)).state == STATE_UNAVAILABLE

    # The faster poll still honours the re-login cooldown: no login, and no
    # API call either, until TOKEN_INVALID_RELOGIN_DELAY has passed.
    position_calls = fake_client.call_count("get_position")
    await _advance(hass, POSITION_SCAN_INTERVAL_ACTIVE)
    assert fake_client.login_calls == 1
    assert fake_client.call_count("get_position") == position_calls


async def test_concurrent_refreshes_log_in_once(
    hass: HomeAssistant, fake_client: FakeMaiClient
) -> None:
    entry = await setup_integration(hass, fake_client)
    main = _main(hass, entry)
    assert fake_client.login_calls == 1

    # Token gone (expired naturally, no invalidation cooldown) while both
    # coordinators refresh at once: a slow login widens the race window.
    fake_client.token = None
    fake_client.login_delay_s = 0.05
    await asyncio.gather(main.async_refresh(), main.position_coordinator.async_refresh())

    # A second concurrent login would mint another token and invalidate the
    # first (70mai keeps one session per account).
    assert fake_client.login_calls == 2
    assert main.last_update_success
    assert main.position_coordinator.last_update_success


async def test_new_device_gets_tracker_from_position_poll(
    hass: HomeAssistant, fake_client: FakeMaiClient
) -> None:
    entry = await setup_integration(hass, fake_client)
    fake_client.devices.append({"deviceId": "dev2", "nickName": "Van"})
    fake_client.positions["dev2"] = position_body(lat="41.900000", lng="12.500000")

    # Bound after setup: the main poll discovers it, the position poll then
    # fetches its position and the tracker appears.
    await _main(hass, entry).async_refresh()
    await _advance(hass, POSITION_SCAN_INTERVAL_ACTIVE)

    state = hass.states.get(_tracker_id(hass, "dev2"))
    assert state.attributes["latitude"] == pytest.approx(41.9)
    assert state.attributes["longitude"] == pytest.approx(12.5)


async def test_parking_photo_follows_position_poll(
    hass: HomeAssistant, fake_client: FakeMaiClient
) -> None:
    fake_client.positions[DEVICE_ID] = position_body(park_pic_url="https://example.com/p.jpg")
    await setup_integration(hass, fake_client)

    assert _entity_id(hass, "image", f"{DEVICE_ID}_parking_photo") is not None
