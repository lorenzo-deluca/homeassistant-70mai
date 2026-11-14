"""Shared fixtures: a network-free stand-in for client70mai.MaiClient and a
helper that sets the integration up against it."""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import patch

import pytest
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from client70mai.exceptions import MaiNotAuthenticatedError

from custom_components.mai70.const import CONF_UUID, DOMAIN

DEVICE_ID = "dev1"
DEVICE_NAME = "Car"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load custom_components/mai70 in every test."""
    yield


def ok(body: Any) -> Dict[str, Any]:
    """A successful MaiCommonResult envelope."""
    return {"error": False, "errorCode": 0, "errorMessage": None, "resultBodyObject": body}


def position_body(
    lat: str = "45.676380",
    lng: str = "9.207113",
    age_s: float = 10,
    park_pic_url: Optional[str] = None,
) -> Dict[str, Any]:
    """getPosition's confirmed resultBodyObject, with lastUpdateTime
    `age_s` seconds in the past."""
    return {
        "status": 2,
        "position": {
            "coordinatesLat": lat,
            "coordinatesLng": lng,
            "lastUpdateTime": int((time.time() - age_s) * 1000),
            "parkPicUrl": park_pic_url,
            "parkPicLastUpdateTime": None,
            "parkingPhotoSwitch": 0,
        },
    }


class FakeMaiClient:
    """Stands in for client70mai.MaiClient. login/getAllDeviceForUser/
    getPosition return what the test sets on `devices`/`positions`; every
    other endpoint returns an empty successful envelope, which the
    coordinator treats as "no data" for that entity.

    A `positions` value can also be an Exception (raised) or a full
    envelope dict with "error": True (returned as-is).
    """

    def __init__(self) -> None:
        self.token: Optional[str] = None
        self.login_delay_s = 0.0
        self.login_calls = 0
        self.devices: List[Dict[str, Any]] = [{"deviceId": DEVICE_ID, "nickName": DEVICE_NAME}]
        self.positions: Dict[str, Any] = {DEVICE_ID: position_body()}
        self.calls: List[Tuple[str, tuple]] = []

    def call_count(self, name: str) -> int:
        return sum(1 for call_name, _ in self.calls if call_name == name)

    def login(self, email: str, plain_password: str) -> Dict[str, Any]:
        self.login_calls += 1
        if self.login_delay_s:
            time.sleep(self.login_delay_s)
        self.token = "token"
        return ok({"token": self.token})

    def _require_token(self) -> None:
        if not self.token:
            raise MaiNotAuthenticatedError("not logged in")

    def get_all_device_for_user(self, *args: Any) -> Dict[str, Any]:
        self.calls.append(("get_all_device_for_user", args))
        self._require_token()
        return ok(self.devices)

    def get_position(self, device_id: str) -> Dict[str, Any]:
        self.calls.append(("get_position", (device_id,)))
        self._require_token()
        result = self.positions.get(device_id)
        if isinstance(result, Exception):
            raise result
        if isinstance(result, dict) and result.get("error"):
            return result
        return ok(result)

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)

        def _endpoint(*args: Any) -> Dict[str, Any]:
            self.calls.append((name, args))
            self._require_token()
            return ok(None)

        return _endpoint


@pytest.fixture
def fake_client() -> FakeMaiClient:
    return FakeMaiClient()


async def setup_integration(hass: HomeAssistant, client: FakeMaiClient) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="user@example.com",
        unique_id="user@example.com",
        data={
            CONF_EMAIL: "user@example.com",
            CONF_PASSWORD: "password",
            CONF_UUID: "00000000-0000-0000-0000-000000000000",
        },
    )
    entry.add_to_hass(hass)
    with patch("custom_components.mai70.MaiClient", return_value=client):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry
