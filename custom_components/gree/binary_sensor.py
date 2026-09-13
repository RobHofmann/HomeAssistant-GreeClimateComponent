"""Support for Gree binary sensors."""

from __future__ import annotations

# Standard library imports
import logging
from dataclasses import dataclass

# Home Assistant imports
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.helpers.entity import EntityCategory

# Local imports
from .const import DOMAIN
from .entity import GreeEntity, GreeEntityDescription

_LOGGER = logging.getLogger(__name__)


@dataclass
class GreeBinarySensorEntityDescription(GreeEntityDescription, BinarySensorEntityDescription):
    """Describes Gree binary sensor entity."""

    pass


BINARY_SENSORS: tuple[GreeBinarySensorEntityDescription, ...] = (
    GreeBinarySensorEntityDescription(
        property_key="filter_alarm",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:air-filter",
        value_fn=lambda device: device.filter_alarm,
        available_fn=lambda device: device.available and bool(device._has_filter_alarm),
    ),
    GreeBinarySensorEntityDescription(
        property_key="hepa_alarm",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        icon="mdi:air-purifier",
        value_fn=lambda device: device.hepa_alarm,
        available_fn=lambda device: device.available and bool(device._has_hepa_alarm),
    ),
)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Gree binary sensors from a config entry."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    device = entry_data["device"]

    sensors = [
        GreeBinarySensor(hass, entry, description)
        for description in BINARY_SENSORS
        if description.exists_fn(description, device)
    ]

    if sensors:
        async_add_entities(sensors)
        _LOGGER.info(f"Added {len(sensors)} Gree binary sensors")


class GreeBinarySensor(GreeEntity, BinarySensorEntity):
    """Gree binary sensor entity."""

    entity_description: GreeBinarySensorEntityDescription

    @property
    def is_on(self) -> bool | None:
        """Return True when the device reports a problem."""
        return self.entity_description.value_fn(self._device)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.entity_description.available_fn(self._device)
