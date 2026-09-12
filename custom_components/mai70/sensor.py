"""Battery voltage sensor platform for the 70mai integration."""
from __future__ import annotations

from typing import Any, Dict, Optional

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfElectricPotential
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import BATTERY_KEY_INDEX, DOMAIN
from .coordinator import Mai70Coordinator
from .entity import Mai70Entity, async_setup_dynamic_entities


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: Mai70Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_setup_dynamic_entities(
        coordinator,
        async_add_entities,
        entity_factory=lambda device_id: Mai70BatterySensor(coordinator, device_id),
        should_add=lambda data: data.get("battery_mv") is not None,
    )


class Mai70BatterySensor(Mai70Entity, SensorEntity):
    """Car battery voltage, read from getDeviceStatusHistoryDaily's
    keyIndex "1.4" (millivolts, not officially documented; see
    client70mai.client.MaiClient.get_device_status_history_daily).
    """

    _attr_translation_key = "battery_voltage"
    _attr_name = None
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: Mai70Coordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_battery_voltage"

    @property
    def native_value(self) -> Optional[float]:
        battery_mv = self._device_data.get("battery_mv")
        return battery_mv / 1000 if battery_mv is not None else None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        return {"raw_key_index": BATTERY_KEY_INDEX, "unit_confirmed": False}
