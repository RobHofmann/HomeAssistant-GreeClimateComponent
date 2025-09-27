"""Base entity for Gree integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
from homeassistant.helpers.entity import DeviceInfo, EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import GreeCoordinator
from .gree_device import GreeDevice


class GreeEntity(CoordinatorEntity[GreeCoordinator]):
    """Base Gree entity."""

    _attr_has_entity_name = True
    entity_description: GreeEntityDescription

    def __init__(
        self,
        description: GreeEntityDescription,
        coordinator: GreeCoordinator,
        restore_state: bool,
        check_availability: bool,
    ) -> None:
        """Initialize Gree entity."""
        super().__init__(coordinator)

        self.entity_description = description  # pyright: ignore[reportIncompatibleVariableOverride]
        self.device = coordinator.device
        self.restore_state = restore_state
        self.check_availability = check_availability

        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_NETWORK_MAC, self.device.unique_id)},
            identifiers={(DOMAIN, self.device.unique_id)},
            name=self.device.name,
            manufacturer="Gree",
            sw_version=self.device.firmware_version,
        )

    @property
    def available(self):  # pyright: ignore[reportIncompatibleVariableOverride]
        """Return True if entity is available."""
        if self.check_availability:
            return (
                self.coordinator.last_update_success
                and self.entity_description.available_func(self.device)
            )
        return True


@dataclass(frozen=True, kw_only=True)
class GreeEntityDescription(EntityDescription):
    """Description of a Gree switch."""

    # Restore the last state by default since the device can be controlled externally,
    # this way HA sets the device to its last known HA state.
    # This will be overridden by entry configuration
    # restore_state: bool = True

    available_func: Callable[[GreeDevice], bool]
