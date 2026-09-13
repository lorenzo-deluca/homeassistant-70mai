"""GPS device_tracker platform for the 70mai integration."""
from __future__ import annotations

from typing import Any, Dict, Optional

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
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
        entity_factory=lambda device_id: Mai70DeviceTracker(coordinator, device_id),
        should_add=lambda data: data.get("position") is not None,
    )


class Mai70DeviceTracker(Mai70Entity, TrackerEntity):
    """GPS position of a 70mai dashcam."""

    _attr_translation_key = "position"
    _attr_name = None

    def __init__(self, coordinator: Mai70Coordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_position"

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def _position(self) -> Dict[str, Any]:
        return self._device_data.get("position") or {}

    @property
    def latitude(self) -> Optional[float]:
        return self._position.get("latitude")

    @property
    def longitude(self) -> Optional[float]:
        return self._position.get("longitude")

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        return {
            "last_update_time": self._position.get("last_update_time"),
            # getPosition's own "status" field, meaning not documented.
            "status": self._position.get("status"),
            "status_confirmed": False,
        }
