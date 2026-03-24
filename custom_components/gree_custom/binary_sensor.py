"""Gree Binary Sensor Entity for Home Assistant."""

from collections.abc import Callable
import logging

from attr import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import CONF_MAC, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import UNDEFINED

from .aiogree.api import GreeProp
from .aiogree.device import GreeDevice
from .const import (
    CONF_ADVANCED,
    CONF_DEVICES,
    CONF_DISABLE_AVAILABLE_CHECK,
    CONF_FEATURES,
    CONF_TO_PROP_FEATURE_MAP,
    DEFAULT_SUPPORTED_FEATURES,
    GATTR_FAULTS,
)
from .coordinator import GreeConfigEntry, GreeCoordinator
from .entity import GreeEntity, GreeEntityDescription

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class GreeBinarySensorDescription(GreeEntityDescription, BinarySensorEntityDescription):
    """Description of a Gree binary sensor."""

    value_func: Callable[[GreeDevice], bool | None]


SENSOR_TYPES: list[GreeBinarySensorDescription] = [
    GreeBinarySensorDescription(
        key=GATTR_FAULTS,
        translation_key=GATTR_FAULTS,
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        available_func=lambda device: (
            device.available and device.supports_property(GreeProp.FAULT)
        ),
        value_func=lambda device: device.has_hvac_error,
        entity_registry_enabled_default=True,
        entity_registry_visible_default=True,
        force_update=False,
        icon=None,
        has_entity_name=True,
        name=None,
        translation_placeholders=None,
        unit_of_measurement=None,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GreeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensors from a config entry."""

    entities: list[GreeBinarySensor] = []

    for d in entry.data.get(CONF_DEVICES, []):
        coordinator: GreeCoordinator = entry.runtime_data[d.get(CONF_MAC, "")]
        if not coordinator:
            _LOGGER.error(
                "Cannot create Gree Binary Sensors. No coordinator found for device '%s'",
                d.get(CONF_MAC, ""),
            )

        descriptions: list[GreeBinarySensorDescription] = []

        conf_supported_features: list[str] = []
        supported_features: list[str] = []

        if d.get(CONF_FEATURES, None) is None:
            _LOGGER.warning("Undefined supported features")
            conf_supported_features = DEFAULT_SUPPORTED_FEATURES
        else:
            conf_supported_features = d.get(CONF_FEATURES, [])

        # Double check features with device support, just in case
        for feature in conf_supported_features:
            # For all other mapped features
            prop = CONF_TO_PROP_FEATURE_MAP.get(feature)
            if prop and coordinator.device.supports_property(prop):
                supported_features.append(feature)

        descriptions.extend(
            [
                description
                for description in SENSOR_TYPES
                if description.key in supported_features
            ]
        )

        _LOGGER.debug(
            "Adding Binary Sensor Entities for device '%s': %s",
            coordinator.device.mac_address_sub,
            [d.key for d in descriptions],
        )

        entities.extend(
            [
                GreeBinarySensor(
                    description,
                    coordinator,
                    check_availability=(
                        entry.data[CONF_ADVANCED].get(
                            CONF_DISABLE_AVAILABLE_CHECK, False
                        )
                    ),
                )
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
