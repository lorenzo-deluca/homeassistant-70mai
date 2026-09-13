"""Alarm event platform for the 70mai integration.

get_device_alarm_list()'s item schema is now confirmed (see
client70mai.client.MaiClient), but the exact meaning of each numeric
`alramType` code isn't (101 is confirmed as a collision alarm; others are
unconfirmed guesses), so this still fires a single generic "alarm" event
type per new alarm rather than mapping codes to specific, possibly-wrong
event names. The confirmed fields (type code, time, GPS, media URLs) are
exposed directly on the event data, plus the raw alarm dict for anyone
who wants the rest.
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
    _attr_icon = "mdi:bell-alert-outline"

    def __init__(self, coordinator: Mai70Coordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_alarm"

    @callback
    def _handle_coordinator_update(self) -> None:
        for alarm in self._device_data.get("new_alarms", []):
            self._trigger_event(
                "alarm",
                {
                    "alarm_id": alarm["alarm_id"],
                    "alarm_type": alarm.get("alarm_type"),
                    "happen_time": alarm.get("happen_time"),
                    "latitude": alarm.get("latitude"),
                    "longitude": alarm.get("longitude"),
                    "picture_url": alarm.get("picture_url"),
                    "video_url": alarm.get("video_url"),
                    "cover_url": alarm.get("cover_url"),
                    "raw": alarm["raw"],
                },
            )
        super()._handle_coordinator_update()
