"""Support for Gree sensors."""

from __future__ import annotations

# Standard library imports
import logging
from dataclasses import dataclass

# Home Assistant imports
from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import (
    CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    PERCENTAGE,
    EntityCategory,
    UnitOfFrequency,
    UnitOfTemperature,
)


# Local imports
from .const import DOMAIN
from .entity import GreeEntity, GreeEntityDescription

_LOGGER = logging.getLogger(__name__)


@dataclass
class GreeSensorEntityDescription(GreeEntityDescription, SensorEntityDescription):
    """Describes Gree Sensor entity."""

    pass


SENSORS: tuple[GreeSensorEntityDescription, ...] = (
    GreeSensorEntityDescription(
        property_key="outside_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda device: device.outside_temperature if device._has_outside_temp_sensor else None,
        available_fn=lambda device: device.available and device._has_outside_temp_sensor,
    ),
    GreeSensorEntityDescription(
        property_key="room_humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        value_fn=lambda device: device.room_humidity if device._has_room_humidity_sensor else None,
        available_fn=lambda device: device.available and device._has_room_humidity_sensor,
    ),
    GreeSensorEntityDescription(
        property_key="compressor_frequency",
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:sine-wave",
        value_fn=lambda device: device.compressor_frequency,
        available_fn=lambda device: device.available and bool(device._has_compressor_freq),
    ),
    GreeSensorEntityDescription(
        property_key="compressor_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: device.compressor_temperature,
        available_fn=lambda device: device.available and bool(device._has_compressor_temp),
    ),
    GreeSensorEntityDescription(
        property_key="evaporator_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: device.evaporator_temperature,
        available_fn=lambda device: device.available and bool(device._has_evaporator_temp),
    ),
    GreeSensorEntityDescription(
        property_key="env_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda device: device.env_temperature,
        available_fn=lambda device: device.available and bool(device._has_env_temp),
    ),
    GreeSensorEntityDescription(
        property_key="outside_temperature_alt",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda device: device.outside_temperature_alt,
        available_fn=lambda device: device.available and bool(device._has_outside_temp_alt),
    ),
    GreeSensorEntityDescription(
        property_key="pm25",
        device_class=SensorDeviceClass.PM25,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda device: device.pm25,
        available_fn=lambda device: device.available and bool(device._has_pm25),
    ),
    GreeSensorEntityDescription(
        property_key="error_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:alert-circle-outline",
        value_fn=lambda device: device.error_code,
        available_fn=lambda device: device.available and bool(device._has_all_err),
    ),
    GreeSensorEntityDescription(
        property_key="jf_error_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        icon="mdi:alert-circle-outline",
        value_fn=lambda device: device.jf_error_code,
        available_fn=lambda device: device.available and bool(device._has_jf_error),
    ),
)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Gree sensors from a config entry."""
    # Get the device that was created in __init__.py
    entry_data = hass.data[DOMAIN][entry.entry_id]
    device = entry_data["device"]

    sensors = []

    for description in SENSORS:
        if description.exists_fn(description, device):
            sensors.append(GreeSensor(hass, entry, description))
            _LOGGER.debug(f"Added {description.property_key} sensor")

    if sensors:
        async_add_entities(sensors)
        _LOGGER.info(f"Added {len(sensors)} Gree sensors")


class GreeSensor(GreeEntity, SensorEntity):
    """Gree sensor entity."""

    entity_description: GreeSensorEntityDescription

    def __init__(self, hass, entry, description: GreeSensorEntityDescription) -> None:
        """Initialize Gree sensor."""
        super().__init__(hass, entry, description)

        # Set temperature unit for temperature sensors
        # Diagnostic temperatures declare Celsius explicitly (the protocol always reports
        # them that way); only the user-facing ones follow the device's configured unit.
        if description.device_class == SensorDeviceClass.TEMPERATURE and description.native_unit_of_measurement is None:
            self._attr_native_unit_of_measurement = self._device.temperature_unit

    @property
    def native_value(self):
        """Return the native value of the sensor."""
        return self.entity_description.value_fn(self._device)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.entity_description.available_fn(self._device)
