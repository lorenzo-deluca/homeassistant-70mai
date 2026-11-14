"""Config flow for the 70mai Dashcam integration."""
from __future__ import annotations

import logging
import uuid as uuid_module
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from client70mai import MaiClient
from client70mai.exceptions import MaiConnectionError, MaiError, MaiTimeoutError

from .const import (
    CONF_BASE_URL,
    CONF_SERVER,
    CONF_UUID,
    DOMAIN,
    SERVER_AUTO,
    SERVER_CHOICES,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_SERVER, default=SERVER_AUTO): SelectSelector(
            SelectSelectorConfig(
                options=[SERVER_AUTO, *SERVER_CHOICES],
                translation_key=CONF_SERVER,
                mode=SelectSelectorMode.DROPDOWN,
                # Lets the user type any server address in the same field.
                custom_value=True,
            )
        ),
    }
)


class InvalidServer(ValueError):
    """A hand-typed server address that isn't a usable http(s) URL."""


def normalize_server(value: str) -> str:
    """Turn a hand-typed server ("int-api.70mai.com", "https://host/")
    into a base URL MaiClient accepts. Raises InvalidServer."""
    value = value.strip()
    if "://" not in value:
        value = f"https://{value}"
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname or " " in value:
        raise InvalidServer(value)
    return value.rstrip("/")


def resolve_servers(server: str) -> List[str]:
    """Base URLs to try, in order, for the user's server choice."""
    if server == SERVER_AUTO:
        return list(SERVER_CHOICES.values())
    if server in SERVER_CHOICES:
        return [SERVER_CHOICES[server]]
    return [normalize_server(server)]


class Mai70ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for 70mai."""

    VERSION = 1

    async def _async_try_login(
        self, base_urls: List[str], device_uuid: str, email: str, password: str
    ) -> tuple[Optional[str], Optional[str]]:
        """Log in against each base URL in turn. Returns (base_url, None)
        for the first one that works, else (None, error_key)."""
        reached_server = False
        for base_url in base_urls:
            client = MaiClient(uuid=device_uuid, base_url=base_url)
            try:
                resp = await self.hass.async_add_executor_job(
                    client.login, email, password
                )
            except (MaiConnectionError, MaiTimeoutError) as exc:
                _LOGGER.warning("Could not reach 70mai server %s: %s", base_url, exc)
            except MaiError as exc:
                # Wrong password and "account lives on another regional
                # server" look the same from here.
                reached_server = True
                _LOGGER.warning("70mai login rejected by %s: %s", base_url, exc)
            else:
                _LOGGER.debug("70mai login succeeded on %s", base_url)
                # The 70mai app learns its real server from a remote config
                # whose URL comes back here (null in every EU capture so
                # far). Logged so non-EU users can report it: it may point
                # at a server missing from SERVER_CHOICES.
                body = resp.get("resultBodyObject") if isinstance(resp, dict) else None
                conf_file_url = body.get("confFileUrl") if isinstance(body, dict) else None
                if conf_file_url:
                    _LOGGER.info(
                        "70mai login on %s returned confFileUrl=%s; please share "
                        "it in an issue at "
                        "https://github.com/lorenzo-deluca/homeassistant-70mai/issues",
                        base_url,
                        conf_file_url,
                    )
                return base_url, None
        return None, "invalid_auth" if reached_server else "cannot_connect"

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        errors: Dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_EMAIL].lower())
            self._abort_if_unique_id_configured()

            try:
                base_urls = resolve_servers(user_input[CONF_SERVER])
            except InvalidServer:
                errors[CONF_SERVER] = "invalid_server"
            else:
                device_uuid = str(uuid_module.uuid4()).upper()
                base_url, error = await self._async_try_login(
                    base_urls,
                    device_uuid,
                    user_input[CONF_EMAIL],
                    user_input[CONF_PASSWORD],
                )
                if base_url is not None:
                    return self.async_create_entry(
                        title=user_input[CONF_EMAIL],
                        data={
                            CONF_EMAIL: user_input[CONF_EMAIL],
                            CONF_PASSWORD: user_input[CONF_PASSWORD],
                            CONF_UUID: device_uuid,
                            CONF_BASE_URL: base_url,
                        },
                    )
                errors["base"] = error

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, user_input
            ),
            errors=errors,
        )
