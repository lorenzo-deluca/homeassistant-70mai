"""Battery voltage sensor (issue #6): yesterday fallback, keeping the last
reading, and surviving restarts when no sample is available yet."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    mock_restore_cache_with_extra_data,
)

from custom_components.mai70.const import DEFAULT_SCAN_INTERVAL, DOMAIN

from .conftest import DEVICE_ID, FakeMaiClient, battery_bucket, setup_integration

UNIQUE_ID = f"{DEVICE_ID}_battery_voltage"
TS_EARLY = 1_793_000_000_000
TS_LATE = TS_EARLY + 3_600_000


def _entity_id(hass: HomeAssistant) -> Optional[str]:
    return er.async_get(hass).async_get_entity_id("sensor", DOMAIN, UNIQUE_ID)


async def _poll(hass: HomeAssistant) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + DEFAULT_SCAN_INTERVAL)
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_uses_newest_sample_of_today(hass: HomeAssistant, fake_client: FakeMaiClient) -> None:
    fake_client.battery_history[(DEVICE_ID, date.today())] = [
        battery_bucket(12_296, TS_LATE),
        battery_bucket(11_900, TS_EARLY),
    ]
    await setup_integration(hass, fake_client)

    state = hass.states.get(_entity_id(hass))
    assert float(state.state) == 12.296
    assert state.attributes["last_sample"] == dt_util.utc_from_timestamp(TS_LATE / 1000).isoformat()


async def test_falls_back_to_yesterday_when_today_is_empty(
    hass: HomeAssistant, fake_client: FakeMaiClient
) -> None:
    fake_client.battery_history[(DEVICE_ID, date.today() - timedelta(days=1))] = [
        battery_bucket(12_100, TS_EARLY)
    ]
    await setup_integration(hass, fake_client)

    assert float(hass.states.get(_entity_id(hass)).state) == 12.1


async def test_no_sample_ever_creates_no_sensor(hass: HomeAssistant, fake_client: FakeMaiClient) -> None:
    await setup_integration(hass, fake_client)

    assert _entity_id(hass) is None


async def test_keeps_last_reading_when_samples_disappear(
    hass: HomeAssistant, fake_client: FakeMaiClient
) -> None:
    fake_client.battery_history[(DEVICE_ID, date.today())] = [battery_bucket(12_296, TS_EARLY)]
    await setup_integration(hass, fake_client)

    fake_client.battery_history.clear()
    await _poll(hass)

    state = hass.states.get(_entity_id(hass))
    assert float(state.state) == 12.296
    assert state.attributes["last_sample"] == dt_util.utc_from_timestamp(TS_EARLY / 1000).isoformat()


async def test_registered_sensor_survives_restart_without_samples(
    hass: HomeAssistant, fake_client: FakeMaiClient
) -> None:
    """The issue #6 case: the sensor reported once, then HA restarted on a
    day without samples and called it "no longer provided"."""
    entity_id = er.async_get(hass).async_get_or_create(
        "sensor", DOMAIN, UNIQUE_ID, suggested_object_id="car_battery_voltage"
    ).entity_id
    last_sample = dt_util.utc_from_timestamp(TS_EARLY / 1000).isoformat()
    mock_restore_cache_with_extra_data(
        hass,
        [
            (
                State(entity_id, "12.296", {"last_sample": last_sample}),
                {"native_value": 12.296, "native_unit_of_measurement": "V"},
            )
        ],
    )
    await setup_integration(hass, fake_client)

    state = hass.states.get(entity_id)
    assert float(state.state) == 12.296
    assert state.attributes["last_sample"] == last_sample


async def test_registered_sensor_without_restore_data_is_unknown(
    hass: HomeAssistant, fake_client: FakeMaiClient
) -> None:
    entity_id = er.async_get(hass).async_get_or_create(
        "sensor", DOMAIN, UNIQUE_ID, suggested_object_id="car_battery_voltage"
    ).entity_id
    await setup_integration(hass, fake_client)

    assert hass.states.get(entity_id).state == STATE_UNKNOWN

    fake_client.battery_history[(DEVICE_ID, date.today())] = [battery_bucket(12_500, TS_LATE)]
    await _poll(hass)
    assert float(hass.states.get(entity_id).state) == 12.5
