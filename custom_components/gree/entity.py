"""Base entity for Gree integration."""

from __future__ import annotations

# Standard library imports
from collections.abc import Callable
from dataclasses import dataclass

# Home Assistant imports
from config.custom_components.gree.coordinator import GreeCoordinator
from config.custom_components.gree.gree_device import GreeDevice
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
from homeassistant.helpers.entity import DeviceInfo, EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

# Local imports
from .const import DOMAIN


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
