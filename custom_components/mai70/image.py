"""Parking-photo image platform for the 70mai integration."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

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
        entity_factory=lambda device_id: Mai70ParkingPhotoImage(coordinator, device_id, hass),
        should_add=lambda data: (data.get("position") or {}).get("park_pic_url") is not None,
    )


class Mai70ParkingPhotoImage(Mai70Entity, ImageEntity):
    """Latest parking-mode snapshot, from getPosition's parkPicUrl. Only
    added once a device has actually returned one (same empirical gating
    as the position/cellular entities): most devices never populate this.
    """

    _attr_translation_key = "parking_photo"
    _attr_name = None
    _attr_icon = "mdi:image-outline"

    def __init__(self, coordinator: Mai70Coordinator, device_id: str, hass: HomeAssistant) -> None:
        Mai70Entity.__init__(self, coordinator, device_id)
        ImageEntity.__init__(self, hass)
        self._attr_unique_id = f"{device_id}_parking_photo"

    @property
    def _position(self) -> Dict[str, Any]:
        return self._device_data.get("position") or {}

    @property
    def image_url(self) -> Optional[str]:
        return self._position.get("park_pic_url")

    @property
    def image_last_updated(self) -> Optional[datetime]:
        last_update = self._position.get("park_pic_last_update_time")
        return dt_util.utc_from_timestamp(last_update / 1000) if last_update else None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        return {
            # "parkingPhotoSwitch"'s exact meaning isn't documented.
            "parking_photo_switch": self._position.get("parking_photo_switch"),
        }
