"""Support for Gree number entities (e.g., target humidity control)."""

from collections.abc import Callable
import logging

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
)
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .aiogree.api import HumidityControlMode, OperationMode
from .aiogree.const import MAX_HUM_COOL_P, MAX_HUM_DRY_P, MIN_HUM_COOL_P, MIN_HUM_DRY_P
from .aiogree.device import GreeDevice
from .const import GATTR_FEAT_HUMIDITY, GATTR_FEAT_HUMIDITY_TARGET
from .coordinator import GreeConfigEntry, GreeCoordinator
from .entity import GreeEntity, GreeEntityDescription
from .platform_helpers import iter_platform_context, supported_descriptions

_LOGGER = logging.getLogger(__name__)


class GreeNumberDescription(
    GreeEntityDescription, NumberEntityDescription, frozen_or_thawed=True
):
    """Description of a Gree number."""

    value_func: Callable[[GreeDevice], int]
    set_func: Callable[[GreeDevice, int], None]
    min_func: Callable[[GreeDevice], int] | None = None
    max_func: Callable[[GreeDevice], int] | None = None
    updates_device: bool = True


NUMBER_TYPES: list[GreeNumberDescription] = [
    GreeNumberDescription(
        feature_key_override=GATTR_FEAT_HUMIDITY,
        key=GATTR_FEAT_HUMIDITY_TARGET,
        translation_key=GATTR_FEAT_HUMIDITY_TARGET,
        device_class=NumberDeviceClass.HUMIDITY,
        mode="auto",
        native_step=5,
        native_unit_of_measurement=PERCENTAGE,
        value_func=lambda device: device.feature_humidity_control_target,
        set_func=lambda device, value: device.set_feature_humidity_control_target(
            value
        ),
        additional_available_func=lambda device: (
            device.operation_mode in (OperationMode.cool, OperationMode.dry)
            and device.feature_humidity_control is HumidityControlMode.target_dry
        ),
        min_func=lambda device: (
            MIN_HUM_COOL_P
            if device.operation_mode == OperationMode.cool
            else MIN_HUM_DRY_P
        ),
        max_func=lambda device: (
            MAX_HUM_COOL_P
            if device.operation_mode == OperationMode.cool
            else MAX_HUM_DRY_P
        ),
        updates_device=True,
    )
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GreeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switches from a config entry."""

    entities: list[GreeNumber] = []

    for ctx in iter_platform_context(entry, "Numbers"):
        descriptions = supported_descriptions(
            NUMBER_TYPES,
            ctx.coordinator.device,
            ctx.device_config,
        )

        _LOGGER.debug(
            "Adding Number Entities for device '%s': %s",
            ctx.coordinator.device.mac_address,
            [d.key for d in descriptions],
        )

        entities.extend(
            GreeNumber(
                description, ctx.coordinator, ctx.restore_state, ctx.check_availability
            )
            for description in descriptions
        )

    async_add_entities(entities)


class GreeNumber(GreeEntity, NumberEntity):  # pyright: ignore[reportIncompatibleVariableOverride]
    """Defines a Gree Number entity."""

    entity_description: GreeNumberDescription

    def __init__(
        self,
        description: GreeNumberDescription,
        coordinator: GreeCoordinator,
        restore_state: bool = True,
        check_availability: bool = True,
    ) -> None:
        """Initialize switch."""
        super().__init__(description, coordinator, restore_state, check_availability)

        self.entity_description = description  # pyright: ignore[reportIncompatibleVariableOverride]
        _LOGGER.debug(
            "Initialized number: %s (check_availability=%s)",
            self.unique_id,
            self.check_availability,
        )

    @property
    def native_min_value(self) -> float:
        """Return the minimum allowed value."""
        if self.entity_description.min_func is not None:
            return self.entity_description.min_func(self.device)

        return self.entity_description.native_min_value

    @property
    def native_max_value(self) -> float:
        """Return the maximum allowed value."""
        if self.entity_description.max_func is not None:
            return self.entity_description.max_func(self.device)

        return self.entity_description.native_max_value

    @property
    def native_value(self) -> int:  # pyright: ignore[reportIncompatibleVariableOverride]
        """Return the state of the sensor."""
        return self.entity_description.value_func(self.device)

    async def async_set_native_value(self, value: int) -> None:
        """Update the current value."""
        if not self.available:
            raise HomeAssistantError("Entity unavailable")

        try:
            self.entity_description.set_func(self.device, value)

            if self.entity_description.updates_device:
                await self.coordinator.push_device_status()

            # notify coordinator listeners of state change so that dependent entities are updated immediately
            self.coordinator.async_update_listeners()

        except Exception as err:
            raise HomeAssistantError("Failed to turn on switch") from err

        self.async_write_ha_state()
