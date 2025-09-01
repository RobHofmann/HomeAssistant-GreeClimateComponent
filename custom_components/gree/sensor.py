"""Support for Gree sensors."""

import logging
from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
)
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Gree sensors from a config entry."""
    # Get the device that was created in __init__.py
    entry_data = hass.data[DOMAIN][entry.entry_id]
    device = entry_data["device"]

    sensors = []

    sensors.append(GreeOutsideTemperatureSensor(device))
    _LOGGER.debug("Added outside temperature sensor")

    sensors.append(GreeRoomHumiditySensor(device))
    _LOGGER.debug("Added room humidity sensor")

    if sensors:
        async_add_entities(sensors)
        _LOGGER.info(f"Added {len(sensors)} Gree sensors")


class GreeOutsideTemperatureSensor(SensorEntity):
    """Gree outside temperature sensor."""

    def __init__(self, device):
        """Initialize the sensor."""
        self._device = device
        self._attr_name = f"{device.name} Outside Temperature"
        self._attr_unique_id = f"{device.unique_id}_outside_temp"
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = device.temperature_unit
        self._attr_suggested_display_precision = 0

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._device._mac_addr)},
            name=self._device.name,
            manufacturer="Gree",
        )

    @property
    def native_value(self):
        """Return the state of the sensor."""
        # Only return value if sensor is detected and available
        if self._device._has_outside_temp_sensor:
            return self._device.outside_temperature
        return None

    @property
    def available(self):
        """Return True if entity is available."""
        return self._device.available and self._device._has_outside_temp_sensor

    def update(self):
        """Update the sensor."""
        # The climate entity handles the actual data fetching
        pass


class GreeRoomHumiditySensor(SensorEntity):
    """Gree room humidity sensor."""

    def __init__(self, device):
        """Initialize the sensor."""
        self._device = device
        self._attr_name = f"{device.name} Room Humidity"
        self._attr_unique_id = f"{device.unique_id}_room_humidity"
        self._attr_device_class = SensorDeviceClass.HUMIDITY
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_suggested_display_precision = 0

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._device._mac_addr)},
            name=self._device.name,
            manufacturer="Gree",
        )

    @property
    def native_value(self):
        """Return the state of the sensor."""
        # Only return value if sensor is detected and available
        if self._device._has_room_humidity_sensor:
            return self._device.room_humidity
        return None

    @property
    def available(self):
        """Return True if entity is available."""
        return self._device.available and self._device._has_room_humidity_sensor

    def update(self):
        """Update the sensor."""
        # The climate entity handles the actual data fetching
        pass
