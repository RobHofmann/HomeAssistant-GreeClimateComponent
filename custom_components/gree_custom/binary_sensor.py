"""Gree Binary Sensor Entity for Home Assistant."""

from collections.abc import Callable
import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .aiogree.device import GreeDevice
from .const import GATTR_FAULTS
from .coordinator import GreeConfigEntry, GreeCoordinator
from .entity import GreeEntity, GreeEntityDescription
from .platform_helpers import iter_platform_context, supported_descriptions

_LOGGER = logging.getLogger(__name__)


class GreeBinarySensorDescription(
    GreeEntityDescription, BinarySensorEntityDescription, frozen_or_thawed=True
):
    """Description of a Gree binary sensor."""

    value_func: Callable[[GreeDevice], bool | None]


SENSOR_TYPES: list[GreeBinarySensorDescription] = [
    GreeBinarySensorDescription(
        key=GATTR_FAULTS,
        translation_key=GATTR_FAULTS,
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_func=lambda device: device.has_hvac_error,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GreeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensors from a config entry."""

    entities: list[GreeBinarySensor] = []
    for ctx in iter_platform_context(entry, "Binary Sensors"):
        descriptions = supported_descriptions(
            SENSOR_TYPES,
            ctx.coordinator.device,
            ctx.device_config,
        )

        _LOGGER.debug(
            "Adding Binary Sensor Entities for device '%s': %s",
            ctx.coordinator.device.mac_address,
            [d.key for d in descriptions],
        )

        entities.extend(
            [
                GreeBinarySensor(description, ctx.coordinator, ctx.check_availability)
                for description in descriptions
            ]
        )

    async_add_entities(entities)


class GreeBinarySensor(GreeEntity, BinarySensorEntity):  # pyright: ignore[reportIncompatibleVariableOverride]
    """Defines a Gree Binary Sensor entity."""

    entity_description: GreeBinarySensorDescription

    def __init__(
        self,
        description: GreeBinarySensorDescription,
        coordinator: GreeCoordinator,
        check_availability: bool = True,
    ) -> None:
        """Initialize binary sensor."""
        super().__init__(
            description,
            coordinator,
            restore_state=False,
            check_availability=check_availability,
        )

        self.entity_description = description  # pyright: ignore[reportIncompatibleVariableOverride]
        _LOGGER.debug(
            "Initialized binary sensor: %s (check_availability=%s)",
            self.unique_id,
            self.check_availability,
        )

    @property
    def is_on(self) -> bool | None:
        """Return the state of the sensor."""
        return self.entity_description.value_func(self.device)
