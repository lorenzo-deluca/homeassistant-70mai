"""Config flow for the 70mai Dashcam integration."""
from __future__ import annotations

import logging
import uuid as uuid_module
from typing import Any, Dict, Optional

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResult
from client70mai import MaiClient
from client70mai.exceptions import MaiError

from .const import CONF_UUID, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class Mai70ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for 70mai."""

    VERSION = 1

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        errors: Dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_EMAIL].lower())
            self._abort_if_unique_id_configured()

            device_uuid = str(uuid_module.uuid4()).upper()
            client = MaiClient(uuid=device_uuid)
            try:
                await self.hass.async_add_executor_job(
                    client.login, user_input[CONF_EMAIL], user_input[CONF_PASSWORD]
                )
            except MaiError as exc:
                _LOGGER.debug("Login failed during config flow: %s", exc)
                errors["base"] = "invalid_auth"
            else:
                return self.async_create_entry(
                    title=user_input[CONF_EMAIL],
                    data={
                        CONF_EMAIL: user_input[CONF_EMAIL],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_UUID: device_uuid,
                    },
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )
