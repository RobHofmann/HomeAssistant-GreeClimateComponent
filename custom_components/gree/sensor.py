"""Gree Sensor Entity for Home Assistant."""

from collections.abc import Callable
from dataclasses import dataclass
import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .coordinator import GreeConfigEntry, GreeCoordinator
from .entity import GreeEntity, GreeEntityDescription
from .gree_device import GreeDevice

_LOGGER = logging.getLogger(__name__)

GATTR_INDOOR_TEMPERATURE = "indoor_temperature"
GATTR_OUTDOOR_TEMPERATURE = "outdoor_temperature"
GATTR_HUMIDITY = "humidity"


@dataclass(frozen=True, kw_only=True)
class GreeSensorDescription(GreeEntityDescription, SensorEntityDescription):
    """Description of a Gree temperature sensor."""

    value_func: Callable[[GreeDevice], float | None]


SENSOR_TYPES: tuple[GreeSensorDescription, ...] = (
    GreeSensorDescription(
        key=GATTR_INDOOR_TEMPERATURE,
        translation_key=GATTR_INDOOR_TEMPERATURE,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=0,
        value_func=lambda device: device.indoors_temperature_c,
        available_func=lambda device: device.has_indoor_temperature_sensor,
    ),
    GreeSensorDescription(
        key=GATTR_OUTDOOR_TEMPERATURE,
        translation_key=GATTR_OUTDOOR_TEMPERATURE,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=0,
        value_func=lambda device: device.outdoors_temperature_c,
        available_func=lambda device: device.has_outdoor_temperature_sensor,
    ),
    GreeSensorDescription(
        key=GATTR_HUMIDITY,
        translation_key=GATTR_HUMIDITY,
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        value_func=lambda device: device.humidity,
        available_func=lambda device: device.has_humidity_sensor,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GreeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors from a config entry."""

    coordinator = entry.runtime_data

    sensors = []

    if coordinator.device.has_indoor_temperature_sensor:
        sensors.append(GATTR_INDOOR_TEMPERATURE)
    if coordinator.device.has_outdoor_temperature_sensor:
        sensors.append(GATTR_OUTDOOR_TEMPERATURE)
    if coordinator.device.has_humidity_sensor:
        sensors.append(GATTR_HUMIDITY)

    _LOGGER.debug("Adding Sensor Entities: %s", sensors)

    entities = [
        GreeSensor(description, coordinator, restore_state=True)
        for description in SENSOR_TYPES
        if description.key in sensors
    ]

    async_add_entities(entities)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    return True


class GreeSensor(GreeEntity, SensorEntity, RestoreEntity):  # pyright: ignore[reportIncompatibleVariableOverride]
    """A Gree Sensor."""

    entity_description: GreeSensorDescription

    def __init__(
        self,
        description: GreeSensorDescription,
        coordinator: GreeCoordinator,
        restore_state: bool = True,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, restore_state)

        self.entity_description = description  # pyright: ignore[reportIncompatibleVariableOverride]
        self._attr_unique_id = f"{self._device.name}_{description.key}"
        _LOGGER.debug("Initialized sensor %s", self._attr_unique_id)

    @property
    def available(self):  # pyright: ignore[reportIncompatibleVariableOverride]
        """Return True if entity is available."""
        return self._device.available and self.entity_description.available_func(
            self._device
        )

    @property
    def native_value(self):  # pyright: ignore[reportIncompatibleVariableOverride]
        """Return the state of the sensor."""
        return self.entity_description.value_func(self._device)

    async def async_added_to_hass(self):
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        # Restore last HA state to device if applicable
        if self.restore_state:
            last_state = await self.async_get_last_state()
            if last_state is not None:
                _LOGGER.debug(
                    "Restoring state for %s: %s", self.entity_id, last_state.state
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
