"""Base entity for Gree integration."""

from __future__ import annotations

# Standard library imports
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

# Home Assistant imports
from config.custom_components.gree.coordinator import GreeCoordinator
from config.custom_components.gree.gree_device import GreeDevice
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
from homeassistant.helpers.entity import DeviceInfo, Entity, EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

# Local imports
from .const import DOMAIN

T = TypeVar("T")


class GreeEntity(CoordinatorEntity[GreeCoordinator]):
    """Base Gree entity."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: GreeCoordinator, restore_state: bool) -> None:
        """Initialize Gree entity."""
        super().__init__(coordinator)
        self._device = coordinator.device
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_NETWORK_MAC, self._device.unique_id)},
            identifiers={(DOMAIN, self._device.unique_id)},
            name=self._device.name,
            manufacturer="Gree",
        )
        self.restore_state = restore_state


@dataclass(frozen=True, kw_only=True)
class GreeEntityDescription(EntityDescription):
    """Description of a Gree switch."""

    # Restore the last state by default since the device can be controlled externally,
    # this way HA sets the device to its last known HA state.
    # This will be overridden by entry configuration
    # restore_state: bool = True

    available_func: Callable[[GreeDevice], bool]


@dataclass
class OldGreeEntityDescription:
    """Describes Gree entity."""

    property_key: str
    """Fills key and translation_key."""
    key: str = None
    translation_key: str = None

    def __post_init__(self):
        self.key = self.property_key
        self.translation_key = self.property_key

    name: str = None
    icon: str = None
    entity_category: str = None
    exists_fn: Callable[[object, object], bool] = lambda description, device: True
    value_fn: Callable[[object], Any] = None
    available_fn: Callable[[object], bool] = lambda device: True
    icon_fn: Callable[[Any, object], str] = None


class OldGreeEntity(Entity):
    """Base Gree entity."""

    _attr_has_entity_name = True
    entity_description: OldGreeEntityDescription

    def __init__(self, hass, entry, description: OldGreeEntityDescription) -> None:
        """Initialize Gree entity."""
        # Get the device from the entry data
        entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
        self._device = entry_data.get("device")
        self.entity_description = description
        self._set_id()

    def _set_id(self) -> None:
        """Set entity ID and unique ID."""
        if self.entity_description:
            if self.entity_description.icon_fn is not None:
                self._attr_icon = self.entity_description.icon_fn(
                    self.native_value, self._device
                )
            elif self.entity_description.icon is not None:
                self._attr_icon = self.entity_description.icon

            self._attr_unique_id = (
                f"{self._device._mac_addr}_{self.entity_description.key}"
            )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._device._mac_addr)},
            name=self._device._name,
            manufacturer="Gree",
            connections={(CONNECTION_NETWORK_MAC, self._device._mac_addr)},
        )

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if self.entity_description.available_fn:
            return self.entity_description.available_fn(self._device)
        return (
            self._device._device_online
            if hasattr(self._device, "_device_online")
            else True
        )

    @property
    def native_value(self) -> Any:
        """Return the native value of the entity."""
        if self.entity_description.value_fn:
            return self.entity_description.value_fn(self._device)
        return None
