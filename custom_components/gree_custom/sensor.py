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
from homeassistant.const import CONF_MAC, PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .aiogree.api import GreeProp
from .aiogree.device import GreeDevice
from .const import (
    CONF_DEVICES,
    CONF_DISABLE_AVAILABLE_CHECK,
    GATTR_HUMIDITY,
    GATTR_INDOOR_TEMPERATURE,
    GATTR_OUTDOOR_TEMPERATURE,
)
from .coordinator import GreeConfigEntry, GreeCoordinator
from .entity import GreeEntity, GreeEntityDescription

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GreeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors from a config entry."""

    entities: list[GreeSensor] = []

    for d in entry.data.get(CONF_DEVICES, []):
        coordinator: GreeCoordinator = entry.runtime_data[d.get(CONF_MAC, "")]
        if not coordinator:
            _LOGGER.error(
                "Cannot create Gree Sensors. No coordinator found for device '%s'",
                d.get(CONF_MAC, ""),
            )

        descriptions: list[GreeSensorDescription] = []
        if coordinator.device.supports_property(GreeProp.SENSOR_TEMPERATURE):
            descriptions.append(
                GreeSensorDescription(
                    key=GATTR_INDOOR_TEMPERATURE,
                    translation_key=GATTR_INDOOR_TEMPERATURE,
                    device_class=SensorDeviceClass.TEMPERATURE,
                    state_class=SensorStateClass.MEASUREMENT,
                    native_unit_of_measurement=UnitOfTemperature.CELSIUS,
                    suggested_display_precision=0,
                    value_func=lambda device: device.indoors_temperature_c,
                    available_func=lambda device: (
                        device.available
                        and device.supports_property(GreeProp.SENSOR_TEMPERATURE)
                    ),
                )
            )
        if coordinator.device.supports_property(GreeProp.SENSOR_OUTSIDE_TEMPERATURE):
            descriptions.append(
                GreeSensorDescription(
                    key=GATTR_OUTDOOR_TEMPERATURE,
                    translation_key=GATTR_OUTDOOR_TEMPERATURE,
                    device_class=SensorDeviceClass.TEMPERATURE,
                    state_class=SensorStateClass.MEASUREMENT,
                    native_unit_of_measurement=UnitOfTemperature.CELSIUS,
                    suggested_display_precision=0,
                    value_func=lambda device: device.outdoors_temperature_c,
                    available_func=lambda device: (
                        device.available
                        and device.supports_property(
                            GreeProp.SENSOR_OUTSIDE_TEMPERATURE
                        )
                    ),
                )
            )
        if coordinator.device.supports_property(GreeProp.SENSOR_HUMIDITY):
            descriptions.append(
                GreeSensorDescription(
                    key=GATTR_HUMIDITY,
                    translation_key=GATTR_HUMIDITY,
                    device_class=SensorDeviceClass.HUMIDITY,
                    state_class=SensorStateClass.MEASUREMENT,
                    native_unit_of_measurement=PERCENTAGE,
                    suggested_display_precision=0,
                    value_func=lambda device: device.humidity,
                    available_func=lambda device: (
                        device.available
                        and device.supports_property(GreeProp.SENSOR_HUMIDITY)
                    ),
                )
            )

        _LOGGER.debug(
            "Adding Sensor Entities for device '%s': %s",
            coordinator.device.mac_address_sub,
            [d.key for d in descriptions],
        )

        entities.extend(
            GreeSensor(
                description,
                coordinator,
                restore_state=True,
                check_availability=(
                    entry.data.get(CONF_DISABLE_AVAILABLE_CHECK, False) is False
                ),
            )
            for description in descriptions
        )

    async_add_entities(entities)


@dataclass(frozen=True, kw_only=True)
class GreeSensorDescription(GreeEntityDescription, SensorEntityDescription):
    """Description of a Gree temperature sensor."""

    value_func: Callable[[GreeDevice], float | None]


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
            self._attr_unique_id,
            self.check_availability,
        )

    @property
    def native_value(self):  # pyright: ignore[reportIncompatibleVariableOverride]
        """Return the state of the sensor."""
        return self.entity_description.value_func(self.device)

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
