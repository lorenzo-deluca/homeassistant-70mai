"""Shared entity base and dynamic-entity-discovery helper for the 70mai
integration.

All platforms (device_tracker, sensor, binary_sensor, image, event)
discover their entities the same way: a 70mai account can have devices
bound to it after HA has already started, so entities for a given
device_id are added the first time the coordinator's data satisfies a
platform-specific predicate, not just once at platform setup.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Set

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import Mai70Coordinator


class Mai70Entity(CoordinatorEntity[Mai70Coordinator]):
    """Base entity tying a 70mai device_id to one HA device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: Mai70Coordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id

    @property
    def _device_data(self) -> Dict[str, Any]:
        return self.coordinator.data.get(self._device_id, {})

    @property
    def available(self) -> bool:
        return super().available and self._device_id in self.coordinator.data

    @property
    def device_info(self) -> DeviceInfo:
        name = self._device_data.get("name", self._device_id)
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=name,
            manufacturer=MANUFACTURER,
        )


def async_setup_dynamic_entities(
    coordinator: Mai70Coordinator,
    async_add_entities: AddEntitiesCallback,
    entity_factory: Callable[[str], Entity],
    should_add: Callable[[Dict[str, Any]], bool] = lambda data: True,
) -> None:
    """Add an entity for each device_id the first time it satisfies
    `should_add`, and keep watching for devices that qualify later."""
    known_ids: Set[str] = set()

    @callback
    def _check_new_devices() -> None:
        new_entities = []
        for device_id, data in coordinator.data.items():
            if device_id in known_ids or not should_add(data):
                continue
            known_ids.add(device_id)
            new_entities.append(entity_factory(device_id))
        if new_entities:
            async_add_entities(new_entities)

    _check_new_devices()
    coordinator.async_add_listener(_check_new_devices)
