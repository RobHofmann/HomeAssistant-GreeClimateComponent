"""Gree Switch Entity for Home Assistant."""

from collections.abc import Callable
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

from .aiogree.api import OperationMode, SleepMode
from .aiogree.device import GreeDevice
from .const import (
    ATTR_AUTO_LIGHT,
    ATTR_AUTO_XFAN,
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
from .platform_helpers import iter_platform_context, supported_descriptions

_LOGGER = logging.getLogger(__name__)


class GreeSwitchDescription(
    GreeEntityDescription, SwitchEntityDescription, frozen_or_thawed=True
):
    """Description of a Gree switch."""

    set_func: Callable[[GreeDevice, GreeCoordinator, bool], None]
    device_class = SwitchDeviceClass.SWITCH
    value_func: Callable[[GreeDevice, GreeCoordinator], bool]
    updates_device: bool = True


SWITCH_TYPES: list[GreeSwitchDescription] = [
    GreeSwitchDescription(
        key=GATTR_FEAT_FRESH_AIR,
        translation_key=GATTR_FEAT_FRESH_AIR,
        value_func=lambda device, _: device.feature_fresh_air,
        set_func=lambda device, _, value: device.set_feature_fresh_air(value),
    ),
    GreeSwitchDescription(
        key=GATTR_FEAT_XFAN,
        translation_key=GATTR_FEAT_XFAN,
        additional_available_func=lambda device: (
            device.operation_mode in [OperationMode.cool, OperationMode.dry]
        ),
        value_func=lambda device, _: device.feature_x_fan,
        set_func=lambda device, _, value: device.set_feature_xfan(value),
    ),
    GreeSwitchDescription(
        feature_key_override=GATTR_FEAT_XFAN,
        key=ATTR_AUTO_XFAN,
        translation_key=ATTR_AUTO_XFAN,
        value_func=lambda _, coordinator: coordinator.feature_auto_xfan,
        set_func=lambda _, coordinator, value: coordinator.set_feature_auto_xfan(value),
        updates_device=False,
        entity_category=EntityCategory.CONFIG,
    ),
    GreeSwitchDescription(
        key=GATTR_FEAT_SLEEP_MODE,
        translation_key=GATTR_FEAT_SLEEP_MODE,
        additional_available_func=(
            lambda device: (
                device.operation_mode in [OperationMode.cool, OperationMode.heat]
            )
        ),
        value_func=lambda device, _: device.feature_sleep is not SleepMode.disabled,
        set_func=lambda device, _, value: device.set_feature_sleep(
            SleepMode.normal if value else SleepMode.disabled
        ),
    ),
    GreeSwitchDescription(
        key=GATTR_FEAT_SMART_HEAT_8C,
        translation_key=GATTR_FEAT_SMART_HEAT_8C,
        additional_available_func=(
            lambda device: device.operation_mode is OperationMode.heat
        ),
        value_func=lambda device, _: device.feature_smart_heat,
        set_func=lambda device, _, value: device.set_feature_smart_heat(value),
    ),
    GreeSwitchDescription(
        key=GATTR_FEAT_HEALTH,
        translation_key=GATTR_FEAT_HEALTH,
        value_func=lambda device, _: device.feature_health,
        set_func=lambda device, _, value: device.set_feature_health(value),
    ),
    GreeSwitchDescription(
        key=GATTR_ANTI_DIRECT_BLOW,
        translation_key=GATTR_ANTI_DIRECT_BLOW,
        value_func=lambda device, _: device.feature_anti_direct_blow,
        set_func=lambda device, _, value: device.set_feature_anti_direct_blow(value),
    ),
    GreeSwitchDescription(
        key=GATTR_FEAT_ENERGY_SAVING,
        translation_key=GATTR_FEAT_ENERGY_SAVING,
        additional_available_func=(
            lambda device: device.operation_mode is OperationMode.cool
        ),
        value_func=lambda device, _: device.feature_energy_saving,
        set_func=lambda device, _, value: device.set_feature_energy_saving(value),
    ),
    GreeSwitchDescription(
        key=GATTR_FEAT_LIGHT,
        translation_key=GATTR_FEAT_LIGHT,
        value_func=lambda device, _: device.feature_light,
        set_func=lambda device, _, value: device.set_feature_light(value),
        entity_category=EntityCategory.CONFIG,
    ),
    GreeSwitchDescription(
        key=GATTR_FEAT_SENSOR_LIGHT,
        translation_key=GATTR_FEAT_SENSOR_LIGHT,
        additional_available_func=lambda device: device.feature_light,
        value_func=lambda device, _: device.feature_light_sensor,
        set_func=lambda device, _, value: device.set_feature_light_sensor(value),
        entity_category=EntityCategory.CONFIG,
    ),
    GreeSwitchDescription(
        feature_key_override=GATTR_FEAT_LIGHT,
        key=ATTR_AUTO_LIGHT,
        translation_key=ATTR_AUTO_LIGHT,
        value_func=(lambda _, coordinator: coordinator.feature_auto_light),
        set_func=(
            lambda _, coordinator, value: coordinator.set_feature_auto_light(value)
        ),
        updates_device=False,
        entity_category=EntityCategory.CONFIG,
    ),
    GreeSwitchDescription(
        key=GATTR_BEEPER,
        translation_key=GATTR_BEEPER,
        value_func=lambda device, _: device.beeper,
        set_func=lambda device, _, value: device.set_beeper(value),
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

    entities: list[GreeSwitch] = []

    for ctx in iter_platform_context(entry, "Switches"):
        descriptions = supported_descriptions(
            SWITCH_TYPES,
            ctx.coordinator.device,
            ctx.device_config,
        )

        _LOGGER.debug(
            "Adding Switch Entities for device '%s': %s",
            ctx.coordinator.device.mac_address,
            [d.key for d in descriptions],
        )

        entities.extend(
            GreeSwitch(
                description,
                ctx.coordinator,
                restore_state=(
                    ctx.restore_state
                    if description.key
                    not in (
                        GATTR_BEEPER,
                        ATTR_AUTO_LIGHT,
                        ATTR_AUTO_XFAN,
                    )  # Always restore these
                    else True
                ),
                check_availability=(
                    ctx.check_availability
                    if description.key != GATTR_BEEPER  # Beeper is always available
                    else False
                ),
            )
            for description in descriptions
        )

    async_add_entities(entities)


class GreeSwitch(GreeEntity, SwitchEntity, RestoreEntity):  # pyright: ignore[reportIncompatibleVariableOverride]
    """Defines a Gree Switch entity."""

    entity_description: GreeSwitchDescription

    def __init__(
        self,
        description: GreeSwitchDescription,
        coordinator: GreeCoordinator,
        restore_state: bool = True,
        check_availability: bool = True,
    ) -> None:
        """Initialize switch."""
        super().__init__(description, coordinator, restore_state, check_availability)

        self.entity_description = description  # pyright: ignore[reportIncompatibleVariableOverride]
        _LOGGER.debug(
            "Initialized switch: %s (check_availability=%s)",
            self.unique_id,
            self.check_availability,
        )

    @property
    def is_on(self) -> bool | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """Return true if the switch is on."""
        return self.entity_description.value_func(self.device, self.coordinator)

    async def async_added_to_hass(self):
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        # Restore last HA state to device if applicable
        if self.restore_state:
            last_state = await self.async_get_last_state()
            if last_state is not None:
                _LOGGER.debug(
                    "Restoring state for %s: %s", self.unique_id, last_state.state
                )
                if last_state.state in ("on", "off"):
                    value: bool = last_state.state == "on"
                    try:
                        self.entity_description.set_func(
                            self.device, self.coordinator, value
                        )

                        if self.entity_description.updates_device:
                            await self.coordinator.push_device_status()

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
            self.entity_description.set_func(self.device, self.coordinator, True)

            if self.entity_description.updates_device:
                await self.coordinator.push_device_status()

            # notify coordinator listeners of state change so that dependent entities are updated immediately
            self.coordinator.async_update_listeners()

            if (
                self.entity_description.key != GATTR_BEEPER
            ):  # ignore HA-only dependent entities
                await self.coordinator.async_request_refresh()
        except Exception as err:
            raise HomeAssistantError("Failed to turn on switch") from err

        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        if not self.available:
            raise HomeAssistantError("Entity unavailable")

        try:
            self.entity_description.set_func(self.device, self.coordinator, False)

            if self.entity_description.updates_device:
                await self.coordinator.push_device_status()

            # notify coordinator listeners of state change so that dependent entities are updated immediately
            self.coordinator.async_update_listeners()

            if (
                self.entity_description.key != GATTR_BEEPER
            ):  # ignore HA-only dependent entities
                await self.coordinator.async_request_refresh()
        except Exception as err:
            raise HomeAssistantError("Failed to turn off switch") from err

        self.async_write_ha_state()
