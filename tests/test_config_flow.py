"""Config flow: server/region selection (auto, known region, typed address)."""
from __future__ import annotations

from typing import Dict, List, Optional
from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from client70mai.exceptions import MaiConnectionError, MaiError, MaiResponseFormatError

from custom_components.mai70.const import (
    CONF_BASE_URL,
    CONF_SERVER,
    CONF_UUID,
    DOMAIN,
    SERVER_EU,
    SERVER_INT,
    SERVER_US,
)

from .conftest import FakeMaiClient, ok

EMAIL = "user@example.com"


class LoginRecorder:
    """Stands in for the MaiClient class in config_flow: each base URL
    either logs in or raises the exception mapped to it."""

    def __init__(self, outcomes: Dict[str, Optional[MaiError]], conf_file_url: Optional[str] = None):
        self.outcomes = outcomes
        self.conf_file_url = conf_file_url
        self.tried: List[str] = []

    def __call__(self, uuid: str, base_url: str) -> "LoginRecorder._Client":
        return self._Client(self, base_url)

    class _Client:
        def __init__(self, recorder: "LoginRecorder", base_url: str) -> None:
            self.recorder = recorder
            self.base_url = base_url

        def login(self, email: str, password: str):
            self.recorder.tried.append(self.base_url)
            error = self.recorder.outcomes.get(self.base_url)
            if error is not None:
                raise error
            return ok({"token": "token", "confFileUrl": self.recorder.conf_file_url})


REJECTED = MaiResponseFormatError("Login response did not contain resultBodyObject.token")
UNREACHABLE = MaiConnectionError("connection refused")


async def _submit(hass: HomeAssistant, recorder: LoginRecorder, server: str):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    # A created entry gets set up for real, against the network-free fake.
    with patch("custom_components.mai70.config_flow.MaiClient", recorder), patch(
        "custom_components.mai70.MaiClient", return_value=FakeMaiClient()
    ):
        return await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_EMAIL: EMAIL, CONF_PASSWORD: "password", CONF_SERVER: server},
        )


async def test_auto_falls_through_to_the_server_that_accepts_the_login(hass: HomeAssistant) -> None:
    recorder = LoginRecorder({SERVER_EU: REJECTED})
    result = await _submit(hass, recorder, "auto")

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_BASE_URL] == SERVER_INT
    assert result["data"][CONF_UUID]
    assert recorder.tried == [SERVER_EU, SERVER_INT]


async def test_known_region_tries_only_that_server(hass: HomeAssistant) -> None:
    recorder = LoginRecorder({})
    result = await _submit(hass, recorder, "us")

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_BASE_URL] == SERVER_US
    assert recorder.tried == [SERVER_US]


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("int-api.70mai.com", "https://int-api.70mai.com"),
        ("  https://example.70mai.com/ ", "https://example.70mai.com"),
        ("http://192.168.1.10:8080", "http://192.168.1.10:8080"),
    ],
)
async def test_typed_server_is_normalized_and_used(
    hass: HomeAssistant, typed: str, expected: str
) -> None:
    recorder = LoginRecorder({})
    result = await _submit(hass, recorder, typed)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_BASE_URL] == expected
    assert recorder.tried == [expected]


@pytest.mark.parametrize("typed", ["ftp://example.com", "https://", "not a host"])
async def test_invalid_typed_server_is_rejected_without_login(hass: HomeAssistant, typed: str) -> None:
    recorder = LoginRecorder({})
    result = await _submit(hass, recorder, typed)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_SERVER: "invalid_server"}
    assert recorder.tried == []


async def test_rejected_everywhere_is_invalid_auth(hass: HomeAssistant) -> None:
    recorder = LoginRecorder({SERVER_EU: REJECTED, SERVER_INT: UNREACHABLE, SERVER_US: REJECTED})
    result = await _submit(hass, recorder, "auto")

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert recorder.tried == [SERVER_EU, SERVER_INT, SERVER_US]


async def test_unreachable_everywhere_is_cannot_connect(hass: HomeAssistant) -> None:
    recorder = LoginRecorder({SERVER_EU: UNREACHABLE, SERVER_INT: UNREACHABLE, SERVER_US: UNREACHABLE})
    result = await _submit(hass, recorder, "auto")

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_conf_file_url_is_logged_for_reporting(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    recorder = LoginRecorder({}, conf_file_url="https://cfg.example/app_config.zip")
    result = await _submit(hass, recorder, "int")

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert "confFileUrl=https://cfg.example/app_config.zip" in caplog.text


async def test_same_account_cannot_be_added_twice(hass: HomeAssistant) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id=EMAIL, data={}).add_to_hass(hass)
    recorder = LoginRecorder({})
    result = await _submit(hass, recorder, "auto")

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert recorder.tried == []


@pytest.mark.parametrize(
    ("extra_data", "expected"),
    [
        # Entries created before region support have no base_url.
        ({}, SERVER_EU),
        ({CONF_BASE_URL: SERVER_INT}, SERVER_INT),
    ],
)
async def test_entry_base_url_is_passed_to_the_client(
    hass: HomeAssistant, fake_client: FakeMaiClient, extra_data: dict, expected: str
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=EMAIL,
        data={
            CONF_EMAIL: EMAIL,
            CONF_PASSWORD: "password",
            CONF_UUID: "00000000-0000-0000-0000-000000000000",
            **extra_data,
        },
    )
    entry.add_to_hass(hass)
    with patch("custom_components.mai70.MaiClient", return_value=fake_client) as client_cls:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert client_cls.call_args.kwargs["base_url"] == expected
