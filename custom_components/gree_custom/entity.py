"""Base entity for Gree integration."""

from collections.abc import Callable
from typing import override

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .aiogree.device import GreeDevice
from .const import DOMAIN
from .coordinator import GreeCoordinator


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

    @property
    @override
    def unique_id(self) -> str | None:
        """Returns a unique id for the entity."""
        return f"{self.device.mac_address}_{self.entity_description.key}"

    @property
    @override
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        if self.device.mac_address != self.device.mac_address_controller:
            return DeviceInfo(
                connections={(CONNECTION_NETWORK_MAC, self.device.mac_address)},
                identifiers={(DOMAIN, self.device.unique_id)},
                name=self.device.name,
                manufacturer="Gree",
                sw_version=self.device.firmware_version,
                # via_device=(DOMAIN, self.device.mac_address_controller),
            )
        return DeviceInfo(
            connections={(CONNECTION_NETWORK_MAC, self.device.mac_address)},
            identifiers={(DOMAIN, self.device.unique_id)},
            name=self.device.name,
            manufacturer="Gree",
            sw_version=self.device.firmware_version,
            hw_version=self.device.firmware_code,
            model_id=self.device.device_model_id,
        )

    @property
    @override
    def available(self) -> bool:
        """Return True if entity is available.

        If entity has 'check_availability' enabled this uses the device available state
        Otherwise, it only uses the 'additional_available_func'
        """

        custom_available = self.entity_description.additional_available_func(
            self.device
        )

        if not self.check_availability:
            return custom_available

        coordinator_ok = self.coordinator.last_update_success
        device_ok = self.device.available

        return custom_available and coordinator_ok and device_ok


class GreeEntityDescription(EntityDescription, frozen_or_thawed=True):
    """Description of a Gree switch."""

    # Use this to override the feature that is checked with the device to evaluate support
    feature_key_override: str | None = None
    # Use this to conditionally block the entity availability independent of the device availability
    additional_available_func: Callable[[GreeDevice], bool] = lambda _: True
    # True if the support can be evaluated with the device API only, false if support must be explicit in device config
    auto_device_support: bool = False
