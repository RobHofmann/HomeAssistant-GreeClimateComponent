"""Gree Switch Entity for Home Assistant."""

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CONF_FEATURES,
    DEFAULT_SUPPORTED_FEATURES,
    GATTR_ANTI_DIRECT_BLOW,
    GATTR_BEEPER,
    GATTR_FEAT_ENERGY_SAVING,
    GATTR_FEAT_FRESH_AIR,
    GATTR_FEAT_HEALTH,
    GATTR_FEAT_LIGHT,
    GATTR_FEAT_SENSOR_LIGHT,
    GATTR_FEAT_SLEEP_MODE,
    GATTR_FEAT_SMART_HEAT_8C,
    GATTR_FEAT_XFAN,
)
from .coordinator import GreeConfigEntry, GreeCoordinator
from .entity import GreeEntity, GreeEntityDescription
from .gree_api import OperationMode
from .gree_device import GreeDevice

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class GreeSwitchDescription(GreeEntityDescription, SwitchEntityDescription):
    """Description of a Gree switch."""

    set_func: Callable[[GreeDevice, bool], None]
    device_class = SwitchDeviceClass.SWITCH
    value_func: Callable[[GreeDevice], bool]
    updates_device: bool = True


SWITCH_TYPES: list[GreeSwitchDescription] = [
    GreeSwitchDescription(
        key=GATTR_FEAT_FRESH_AIR,
        translation_key=GATTR_FEAT_FRESH_AIR,
        available_func=lambda device: device.available,
        value_func=lambda device: device.feature_fresh_air,
        set_func=lambda device, value: device.set_feature_fresh_air(value),
    ),
    GreeSwitchDescription(
        key=GATTR_FEAT_XFAN,
        translation_key=GATTR_FEAT_XFAN,
        available_func=lambda device: device.available
        and device.operation_mode in [OperationMode.Cool, OperationMode.Dry],
        value_func=lambda device: device.feature_x_fan,
        set_func=lambda device, value: device.set_feature_xfan(value),
    ),
    GreeSwitchDescription(
        key=GATTR_FEAT_SLEEP_MODE,
        translation_key=GATTR_FEAT_SLEEP_MODE,
        available_func=lambda device: device.available
        and device.operation_mode
        in [OperationMode.Cool, OperationMode.Dry, OperationMode.Heat],
        value_func=lambda device: device.feature_sleep,
        set_func=lambda device, value: device.set_feature_sleep(value),
    ),
    GreeSwitchDescription(
        key=GATTR_FEAT_SMART_HEAT_8C,
        translation_key=GATTR_FEAT_SMART_HEAT_8C,
        available_func=lambda device: device.available,
        value_func=lambda device: device.feature_smart_heat,
        set_func=lambda device, value: device.set_feature_smart_heat(value),
    ),
    GreeSwitchDescription(
        key=GATTR_FEAT_HEALTH,
        translation_key=GATTR_FEAT_HEALTH,
        available_func=lambda device: device.available,
        value_func=lambda device: device.feature_health,
        set_func=lambda device, value: device.set_feature_health(value),
    ),
    GreeSwitchDescription(
        key=GATTR_ANTI_DIRECT_BLOW,
        translation_key=GATTR_ANTI_DIRECT_BLOW,
        available_func=lambda device: device.available,
        value_func=lambda device: device.feature_anti_direct_blow,
        set_func=lambda device, value: device.set_feature_anti_direct_blow(value),
    ),
    GreeSwitchDescription(
        key=GATTR_FEAT_ENERGY_SAVING,
        translation_key=GATTR_FEAT_ENERGY_SAVING,
        available_func=lambda device: device.available,
        value_func=lambda device: device.feature_energy_saving,
        set_func=lambda device, value: device.set_feature_energy_saving(value),
    ),
    GreeSwitchDescription(
        key=GATTR_FEAT_LIGHT,
        translation_key=GATTR_FEAT_LIGHT,
        available_func=lambda device: device.available,
        value_func=lambda device: device.feature_light,
        set_func=lambda device, value: device.set_feature_light(value),
        entity_category=EntityCategory.CONFIG,
    ),
    GreeSwitchDescription(
        key=GATTR_FEAT_SENSOR_LIGHT,
        translation_key=GATTR_FEAT_SENSOR_LIGHT,
        available_func=lambda device: device.available and device.feature_light,
        value_func=lambda device: device.feature_light_sensor,
        set_func=lambda device, value: device.set_feature_light_sensor(value),
        entity_category=EntityCategory.CONFIG,
    ),
    GreeSwitchDescription(
        key=GATTR_BEEPER,
        translation_key=GATTR_BEEPER,
        available_func=lambda device: device.available,
        value_func=lambda device: device.beeper,
        set_func=lambda device, value: device.set_beeper(value),
        entity_category=EntityCategory.CONFIG,
        updates_device=False,  # Local entity
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GreeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switches from a config entry."""

    coordinator = entry.runtime_data
    supported_features: list[str]

    if entry.data[CONF_FEATURES] is None:
        _LOGGER.warning("Undefined supported features")
        supported_features = DEFAULT_SUPPORTED_FEATURES
    else:
        supported_features = entry.data[CONF_FEATURES]

    _LOGGER.debug("Adding Switch Entities: %s", supported_features)

    entities = [
        GreeSwitch(description, coordinator, restore_state=True)
        for description in SWITCH_TYPES
        if description.key in supported_features
    ]

    async_add_entities(entities)


class GreeSwitch(GreeEntity, SwitchEntity, RestoreEntity):  # pyright: ignore[reportIncompatibleVariableOverride]
    """Defines a Gree Switch entity."""

    entity_description: GreeSwitchDescription

    def __init__(
        self,
        description: GreeSwitchDescription,
        coordinator: GreeCoordinator,
        restore_state: bool = True,
    ) -> None:
        """Initialize switch."""
        super().__init__(coordinator, restore_state)

        self.entity_description = description  # pyright: ignore[reportIncompatibleVariableOverride]
        self._attr_unique_id = f"{self._device.name}_{description.key}"
        _LOGGER.debug("Initialized sensor %s", self._attr_unique_id)

    @property
    def available(self):  # pyright: ignore[reportIncompatibleVariableOverride]
        """Return True if entity is available."""
        return self.entity_description.available_func(self._device)

    @property
    def is_on(self) -> bool | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """Return true if the switch is on."""
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
                if last_state.state in ("on", "off"):
                    value: bool = last_state.state == "on"
                    try:
                        self.entity_description.set_func(self._device, value)

                        if self.entity_description.updates_device:
                            await self._device.update_device_status()

                        self._attr_is_on = value
                    except Exception as err:  # noqa: BLE001
                        _LOGGER.error(
                            "Failed to restore state for %s: %s",
                            self.entity_id,
                            repr(err),
                        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        if not self.available:
            raise HomeAssistantError("Entity unavailable")

        try:
            self.entity_description.set_func(self._device, True)

            if self.entity_description.updates_device:
                await self._device.update_device_status()

            # notify coordinator listeners of state change so that dependent entities are updated immediately
            self.coordinator.async_update_listeners()

            if self.entity_description.key not in [
                GATTR_BEEPER
            ]:  # ignore HA-only dependent entities
                await self.coordinator.async_request_refresh()
        except Exception as err:
            raise HomeAssistantError("Failed to turn on switch") from err

        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        if not self.available:
            raise HomeAssistantError("Entity unavailable")

        try:
            self.entity_description.set_func(self._device, False)

            if self.entity_description.updates_device:
                await self._device.update_device_status()

            # notify coordinator listeners of state change so that dependent entities are updated immediately
            self.coordinator.async_update_listeners()

            if self.entity_description.key not in [
                GATTR_BEEPER
            ]:  # ignore HA-only dependent entities
                await self.coordinator.async_request_refresh()
        except Exception as err:
            raise HomeAssistantError("Failed to turn off switch") from err

        self.async_write_ha_state()
