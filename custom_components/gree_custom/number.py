"""Support for Gree number entities (e.g., target humidty control)."""

from collections.abc import Callable
from dataclasses import dataclass
import logging

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
)
from homeassistant.const import CONF_MAC, PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .aiogree.api import GreeProp, HumidityControlMode, OperationMode
from .aiogree.const import MAX_HUM_P, MIN_HUM_P
from .aiogree.device import GreeDevice
from .const import (
    CONF_ADVANCED,
    CONF_DEVICES,
    CONF_DISABLE_AVAILABLE_CHECK,
    CONF_FEATURES,
    CONF_RESTORE_STATES,
    DEFAULT_DISABLE_AVAILABLE_CHECK,
    DEFAULT_RESTORE_STATES,
    DEFAULT_SUPPORTED_FEATURES,
    GATTR_FEAT_HUMIDITY,
    GATTR_FEAT_HUMIDITY_TARGET,
)
from .coordinator import GreeConfigEntry, GreeCoordinator
from .entity import GreeEntity, GreeEntityDescription

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GreeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switches from a config entry."""

    entities: list[GreeNumber] = []

    for d in entry.data.get(CONF_DEVICES, []):
        mac = d.get(CONF_MAC, "")
        coordinator: GreeCoordinator = entry.runtime_data[mac]
        if not coordinator:
            _LOGGER.error(
                "Cannot create Gree numbers. No coordinator found for device '%s'",
                mac,
            )
            continue

        descriptions: list[GreeNumberDescription] = []

        conf_supported_features = d.get(CONF_FEATURES, DEFAULT_SUPPORTED_FEATURES)
        if (
            GATTR_FEAT_HUMIDITY in conf_supported_features
            and coordinator.device.supports_property(GreeProp.FEATURE_HUMIDITY)
        ):
            descriptions.append(
                GreeNumberDescription(
                    key=GATTR_FEAT_HUMIDITY_TARGET,
                    translation_key=GATTR_FEAT_HUMIDITY_TARGET,
                    device_class=NumberDeviceClass.HUMIDITY,
                    mode="auto",
                    native_max_value=MAX_HUM_P,
                    native_min_value=MIN_HUM_P,
                    native_step=5,
                    native_unit_of_measurement=PERCENTAGE,
                    value_func=lambda device: device.feature_humidity_control_target,
                    set_func=lambda device, value: (
                        device.set_feature_humidity_control_target(value)
                    ),
                    additional_available_func=lambda device: (
                        device.operation_mode is OperationMode.cool
                        and device.feature_humidity_control
                        is HumidityControlMode.target_dry
                    ),
                    updates_device=True,
                )
            )

        _LOGGER.debug(
            "Adding Select Entities for device '%s': %s",
            coordinator.device.mac_address,
            [d.key for d in descriptions],
        )

        entities.extend(
            GreeNumber(
                description,
                coordinator,
                d.get(CONF_RESTORE_STATES, DEFAULT_RESTORE_STATES),
                check_availability=(
                    not entry.data[CONF_ADVANCED].get(
                        CONF_DISABLE_AVAILABLE_CHECK, DEFAULT_DISABLE_AVAILABLE_CHECK
                    )
                ),
            )
            for description in descriptions
        )

    async_add_entities(entities)


@dataclass(frozen=True, kw_only=True)
class GreeNumberDescription(GreeEntityDescription, NumberEntityDescription):
    """Description of a Gree number."""

    entity_category = None
    entity_registry_enabled_default = True
    entity_registry_visible_default = True
    force_update = False
    icon = None
    has_entity_name = True
    name = None
    translation_key = None
    translation_placeholders = None
    unit_of_measurement = None
    max_value: None = None
    min_value: None = None
    step: None = None

    additional_available_func = lambda _: True  # noqa: E731
    value_func: Callable[[GreeDevice], int]
    set_func: Callable[[GreeDevice, int], None]
    updates_device: bool = True


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
