"""Gree Sensor Entity for Home Assistant."""

from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
import logging
from typing import override

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import StateType

from .aiogree.device import GreeDevice
from .const import GATTR_HUMIDITY, GATTR_INDOOR_TEMPERATURE, GATTR_OUTDOOR_TEMPERATURE
from .coordinator import GreeConfigEntry, GreeCoordinator
from .entity import GreeEntity, GreeEntityDescription
from .platform_helpers import supported_descriptions

_LOGGER = logging.getLogger(__name__)


class GreeSensorDescription(
    GreeEntityDescription, SensorEntityDescription, frozen_or_thawed=True
):
    """Description of a Gree temperature sensor."""

    value_func: Callable[[GreeDevice], float | None]


SENSOR_TYPES: list[GreeSensorDescription] = [
    GreeSensorDescription(
        auto_device_support=True,
        key=GATTR_INDOOR_TEMPERATURE,
        translation_key=GATTR_INDOOR_TEMPERATURE,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=0,
        value_func=lambda device: device.indoors_temperature_c,
    ),
    GreeSensorDescription(
        auto_device_support=True,
        key=GATTR_OUTDOOR_TEMPERATURE,
        translation_key=GATTR_OUTDOOR_TEMPERATURE,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=0,
        value_func=lambda device: device.outdoors_temperature_c,
    ),
    GreeSensorDescription(
        auto_device_support=True,
        key=GATTR_HUMIDITY,
        translation_key=GATTR_HUMIDITY,
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        value_func=lambda device: device.humidity,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GreeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors from a config entry."""

    _LOGGER.debug("Setting up Sensor Entities")

    entities: list[GreeSensor] = []

    for coordinator in entry.runtime_data.values():
        # Sensors are checked directly, not on the entry config
        descriptions = supported_descriptions(SENSOR_TYPES, coordinator.device, None)

        _LOGGER.debug(
            "Adding Sensor Entities for device '%s': %s",
            coordinator.device.mac_address,
            [d.key for d in descriptions],
        )

        entities.extend(
            GreeSensor(description, coordinator, False, coordinator.check_availability)
            for description in descriptions
        )

    async_add_entities(entities)


class GreeSensor(GreeEntity, SensorEntity, RestoreEntity):  # pyright: ignore[reportIncompatibleVariableOverride]
    """A Gree Sensor."""

    entity_description: GreeSensorDescription

    def __init__(
        self,
        description: GreeSensorDescription,
        coordinator: GreeCoordinator,
        restore_state: bool = True,
        check_availability: bool = True,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(description, coordinator, restore_state, check_availability)

        self.entity_description = description  # pyright: ignore[reportIncompatibleVariableOverride]
        _LOGGER.debug(
            "Initialized sensor: %s (check_availability=%s)",
            self.unique_id,
            self.check_availability,
        )

    @property
    @override
    def native_value(self) -> StateType | date | datetime | Decimal:
        """Return the state of the sensor."""
        return self.entity_description.value_func(self.device)

    @override
    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        # Restore last HA state to device if applicable
        if self.restore_state:
            last_state = await self.async_get_last_state()
            if last_state is not None:
                _LOGGER.debug(
                    "Restoring state for %s: %s", self.unique_id, last_state.state
                )
                if last_state.state not in (None, "unknown", "unavailable"):
                    try:
                        self._attr_native_value = float(last_state.state)
                    except ValueError as err:
                        _LOGGER.error(
                            "Failed to restore state for %s: %s",
                            self.entity_id,
                            repr(err),
                        )
