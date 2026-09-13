"""Binary sensor platforms for the 70mai integration."""
from __future__ import annotations

from typing import Any, Dict, Optional

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
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
        entity_factory=lambda device_id: Mai70MonitorVideoUploadSensor(coordinator, device_id),
        should_add=lambda data: (data.get("device_switch") or {}).get("monitor_video_upload")
        is not None,
    )
    async_setup_dynamic_entities(
        coordinator,
        async_add_entities,
        entity_factory=lambda device_id: Mai70SimOutPowerSensor(coordinator, device_id),
        should_add=lambda data: data.get("sim_out_power") is not None,
    )


class Mai70MonitorVideoUploadSensor(Mai70Entity, BinarySensorEntity):
    """Whether the "monitor video" cloud-upload switch is on, from
    getDeviceSwitch's confirmed monitorVedioUpload field (sic - verbatim
    API typo). Read-only: this integration doesn't call setDeviceSwitch,
    so toggling it from the 70mai app is the only way to change it today.
    """

    _attr_translation_key = "monitor_video_upload"
    _attr_name = None
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:cloud-upload-outline"

    def __init__(self, coordinator: Mai70Coordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_monitor_video_upload"

    @property
    def _device_switch(self) -> Dict[str, Any]:
        return self._device_data.get("device_switch") or {}

    @property
    def is_on(self) -> Optional[bool]:
        return self._device_switch.get("monitor_video_upload")

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        return {"details": self._device_switch.get("details")}


class Mai70SimOutPowerSensor(Mai70Entity, BinarySensorEntity):
    """Whether the SIM/cellular add-on can power the dashcam on its own
    (e.g. for parking-mode surveillance without the car battery), from
    simPluginSupportOutPower. Only added for devices with a cellular
    add-on (same empirical gating as the other SIM-derived entities).
    """

    _attr_translation_key = "sim_out_power"
    _attr_name = None
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:battery-charging-outline"

    def __init__(self, coordinator: Mai70Coordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_sim_out_power"

    @property
    def is_on(self) -> Optional[bool]:
        return self._device_data.get("sim_out_power")
