"""Alarm event platform for the 70mai integration.

get_device_alarm_list()'s item schema isn't confirmed (see
client70mai.client.MaiClient), so this fires a single generic "alarm"
event type per new alarm rather than mapping alarm_types (105/108) to
specific, possibly-wrong event names. The raw alarm dict is passed through
as an attribute for anyone who wants to inspect it.
"""
from __future__ import annotations

from typing import Any, Dict

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import Mai70Coordinator
from .entity import Mai70Entity, async_setup_dynamic_entities


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: Mai70Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_setup_dynamic_entities(
        coordinator,
        async_add_entities,
        entity_factory=lambda device_id: Mai70AlarmEvent(coordinator, device_id),
    )


class Mai70AlarmEvent(Mai70Entity, EventEntity):
    """Fires once for each new dashcam alarm observed."""

    _attr_translation_key = "alarm"
    _attr_name = None
    _attr_event_types = ["alarm"]

    def __init__(self, coordinator: Mai70Coordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_alarm"

    @callback
    def _handle_coordinator_update(self) -> None:
        for alarm in self._device_data.get("new_alarms", []):
            self._trigger_event(
                "alarm",
                {"alarm_id": alarm["alarm_id"], "raw": alarm["raw"]},
            )
        super()._handle_coordinator_update()
