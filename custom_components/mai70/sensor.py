"""Sensor platforms for the 70mai integration."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfElectricPotential
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

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
    async_setup_dynamic_entities(
        coordinator,
        async_add_entities,
        entity_factory=lambda device_id: Mai70LastReportSensor(coordinator, device_id),
        should_add=lambda data: (data.get("dashcam_detail") or {}).get("report_time") is not None,
    )
    async_setup_dynamic_entities(
        coordinator,
        async_add_entities,
        entity_factory=lambda device_id: Mai70StatusSensor(coordinator, device_id),
        should_add=lambda data: data.get("dashcam_detail") is not None,
    )
    async_setup_dynamic_entities(
        coordinator,
        async_add_entities,
        entity_factory=lambda device_id: Mai70CellularFirmwareSensor(coordinator, device_id),
        should_add=lambda data: (data.get("cellular") or {}).get("software_version") is not None,
    )
    async_setup_dynamic_entities(
        coordinator,
        async_add_entities,
        entity_factory=lambda device_id: Mai70SimSensor(coordinator, device_id),
        should_add=lambda data: (data.get("cellular") or {}).get("imei") is not None,
    )
    async_setup_dynamic_entities(
        coordinator,
        async_add_entities,
        entity_factory=lambda device_id: Mai70CountrySensor(coordinator, device_id),
        should_add=lambda data: data.get("country_code") is not None,
    )
    async_setup_dynamic_entities(
        coordinator,
        async_add_entities,
        entity_factory=lambda device_id: Mai70FirmwareVersionSensor(coordinator, device_id),
        should_add=lambda data: (data.get("firmware") or {}).get("version") is not None,
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
    _attr_icon = "mdi:car-battery"

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


class Mai70LastReportSensor(Mai70Entity, SensorEntity):
    """Last time the dashcam reported its status to the cloud, from
    getDashcamDetail's device.reportTime.
    """

    _attr_translation_key = "last_report"
    _attr_name = None
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: Mai70Coordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_last_report"

    @property
    def native_value(self) -> Optional[datetime]:
        report_time = (self._device_data.get("dashcam_detail") or {}).get("report_time")
        return dt_util.utc_from_timestamp(report_time / 1000) if report_time else None


class Mai70StatusSensor(Mai70Entity, SensorEntity):
    """Raw device/SIM-plugin/geofence status flags from getDashcamDetail.
    The field names are confirmed but their value meaning (bool vs int,
    exact codes) isn't documented anywhere, so this passes the raw
    deviceStatus value through rather than mapping it to an on/off state;
    see client70mai.client.MaiClient.get_dashcam_detail.
    """

    _attr_translation_key = "status"
    _attr_name = None
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:information-outline"

    def __init__(self, coordinator: Mai70Coordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_status"

    @property
    def _detail(self) -> Dict[str, Any]:
        return self._device_data.get("dashcam_detail") or {}

    @property
    def native_value(self) -> Any:
        return self._detail.get("device_status")

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        return {
            "sim_plugin_active_status": self._detail.get("sim_plugin_active_status"),
            "geofence_active_status": self._detail.get("geofence_active_status"),
            "value_confirmed": False,
        }


class Mai70CellularFirmwareSensor(Mai70Entity, SensorEntity):
    """Cellular add-on firmware version, from getSimPluginDetail. Only
    added for devices that actually have a SIM plugin (detected
    empirically: the entity only appears once that call succeeds with a
    software version, same approach as device_tracker's position entity).
    """

    _attr_translation_key = "cellular_firmware"
    _attr_name = None
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:antenna"

    def __init__(self, coordinator: Mai70Coordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_cellular_firmware"

    @property
    def _cellular(self) -> Dict[str, Any]:
        return self._device_data.get("cellular") or {}

    @property
    def native_value(self) -> Optional[str]:
        return self._cellular.get("software_version")

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        return {
            "sub_software_version": self._cellular.get("sub_software_version"),
            "imei": self._cellular.get("imei"),
        }


class Mai70SimSensor(Mai70Entity, SensorEntity):
    """SIM/cellular add-on identity, from getSimPluginDetail. Only added
    for devices with a cellular add-on (same empirical detection as
    Mai70CellularFirmwareSensor).
    """

    _attr_translation_key = "sim"
    _attr_name = None
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:sim"

    def __init__(self, coordinator: Mai70Coordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_sim"

    @property
    def _cellular(self) -> Dict[str, Any]:
        return self._device_data.get("cellular") or {}

    @property
    def native_value(self) -> Optional[str]:
        return self._cellular.get("imei")

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        return {
            "plugin_device_id": self._cellular.get("plugin_device_id"),
            "is_beta_device": self._cellular.get("is_beta_device"),
        }


class Mai70CountrySensor(Mai70Entity, SensorEntity):
    """Account country code, from getUserCountryCode. Account-level (the
    same value for every device on the account), exposed per device since
    entities in this integration are attached to a 70mai device.
    """

    _attr_translation_key = "country"
    _attr_name = None
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:flag"

    def __init__(self, coordinator: Mai70Coordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_country"

    @property
    def native_value(self) -> Optional[str]:
        return self._device_data.get("country_code")


class Mai70FirmwareVersionSensor(Mai70Entity, SensorEntity):
    """Current dashcam firmware version, from checkNewRomFromApp's
    resultBodyObject.version (confirmed to report the device's own
    installed firmware, independent of the request's base_version - see
    Mai70Coordinator._async_get_firmware_info).
    """

    _attr_translation_key = "firmware"
    _attr_name = None
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:chip"

    def __init__(self, coordinator: Mai70Coordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_firmware"

    @property
    def _firmware(self) -> Dict[str, Any]:
        return self._device_data.get("firmware") or {}

    @property
    def native_value(self) -> Optional[str]:
        return self._firmware.get("version")

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        release_time = self._firmware.get("release_time")
        return {
            "sub_version": self._firmware.get("sub_version"),
            "description": self._firmware.get("desc"),
            "release_time": dt_util.utc_from_timestamp(release_time / 1000).isoformat()
            if release_time
            else None,
            "file_size": self._firmware.get("file_size"),
            "device_category_confirmed": False,
        }
