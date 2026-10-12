"""Support for Gree number entities (e.g., target humidity control)."""

from collections.abc import Callable
import logging
from typing import override

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .aiogree.api import (
    DeviceType,
    HumidityControlMode,
    OperationMode,
    TemperatureUnits,
)
from .aiogree.const import (
    MAX_HUM_COOL_P,
    MAX_HUM_DRY_P,
    MAX_TEMP_C,
    MAX_TEMP_F,
    MIN_HUM_COOL_P,
    MIN_HUM_DRY_P,
    MIN_TEMP_C,
    MIN_TEMP_F,
)
from .aiogree.device import GreeDevice
from .const import (
    GATTR_FEAT_HUMIDITY,
    GATTR_FEAT_HUMIDITY_TARGET,
    GATTR_ZONE_TARGET_TEMPERATURE,
    UNITS_GREE_TO_HA,
)
from .coordinator import GreeConfigEntry, GreeCoordinator
from .entity import GreeEntity, GreeEntityDescription
from .platform_helpers import supported_descriptions

_LOGGER = logging.getLogger(__name__)


class GreeNumberDescription(
    GreeEntityDescription, NumberEntityDescription, frozen_or_thawed=True
):
    """Description of a Gree number."""

    value_func: Callable[[GreeDevice], float | None]
    set_func: Callable[[GreeDevice, int], None]
    min_func: Callable[[GreeDevice], int] | None = None
    max_func: Callable[[GreeDevice], int] | None = None
    # The unit, when the device decides it, such as Celsius or Fahrenheit
    unit_func: Callable[[GreeDevice], str] | None = None
    updates_device: bool = True


NUMBER_TYPES: list[GreeNumberDescription] = [
    GreeNumberDescription(
        feature_key_override=GATTR_FEAT_HUMIDITY,
        key=GATTR_FEAT_HUMIDITY_TARGET,
        translation_key=GATTR_FEAT_HUMIDITY_TARGET,
        device_class=NumberDeviceClass.HUMIDITY,
        mode=NumberMode.AUTO,
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
    ),
    GreeNumberDescription(
        key=GATTR_ZONE_TARGET_TEMPERATURE,
        translation_key=GATTR_ZONE_TARGET_TEMPERATURE,
        auto_device_support=True,
        device_filter=lambda device: device.device_type is DeviceType.ZONE,
        device_class=NumberDeviceClass.TEMPERATURE,
        mode=NumberMode.BOX,
        native_step=1,
        min_func=lambda device: (
            MIN_TEMP_F
            if device.target_temperature_unit is TemperatureUnits.F
            else MIN_TEMP_C
        ),
        max_func=lambda device: (
            MAX_TEMP_F
            if device.target_temperature_unit is TemperatureUnits.F
            else MAX_TEMP_C
        ),
        unit_func=lambda device: UNITS_GREE_TO_HA[device.target_temperature_unit],
        value_func=lambda device: device.target_temperature,
        set_func=lambda device, value: device.set_target_temperature(value),
        updates_device=True,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GreeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switches from a config entry."""

    _LOGGER.debug("Setting up Number Entities")

    entities: list[GreeNumber] = []

    for coordinator in entry.runtime_data.values():
        descriptions = supported_descriptions(
            NUMBER_TYPES,
            coordinator.device,
            coordinator.device_config,
        )

        _LOGGER.debug(
            "Adding Number Entities for device '%s': %s",
            coordinator.device.mac_address,
            [d.key for d in descriptions],
        )

        entities.extend(
            GreeNumber(
                description,
                coordinator,
                coordinator.restore_states,
                coordinator.check_availability,
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
    @override
    def native_min_value(self) -> float:
        """Return the minimum allowed value."""
        if self.entity_description.min_func is not None:
            return self.entity_description.min_func(self.device)

        return super().native_min_value

    @property
    @override
    def native_max_value(self) -> float:
        """Return the maximum allowed value."""
        if self.entity_description.max_func is not None:
            return self.entity_description.max_func(self.device)

        return super().native_max_value

    @property
    @override
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit, from the device when it decides it."""
        if self.entity_description.unit_func is not None:
            return self.entity_description.unit_func(self.device)

        return super().native_unit_of_measurement

    @property
    @override
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        return self.entity_description.value_func(self.device)

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        if not self.available:
            raise HomeAssistantError("Entity unavailable")

        try:
            # Round, not cut: a temperature converted by Home Assistant can
            # be 69.8 for 70 degrees Fahrenheit
            self.entity_description.set_func(self.device, round(value))

            if self.entity_description.updates_device:
                await self.coordinator.push_device_status()

            # notify coordinator listeners of state change so that dependent entities are updated immediately
            self.coordinator.async_update_listeners()

        except Exception as err:
            raise HomeAssistantError("Failed to turn on switch") from err

        self.async_write_ha_state()
