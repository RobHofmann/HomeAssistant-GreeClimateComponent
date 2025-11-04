"""Gree Climate Entity for Home Assistant."""

import logging

from attr import dataclass

from homeassistant.components.climate import (
    ATTR_FAN_MODE,
    ATTR_HVAC_MODE,
    ATTR_SWING_HORIZONTAL_MODE,
    ATTR_SWING_MODE,
    ClimateEntity,
    ClimateEntityDescription,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    ATTR_UNIT_OF_MEASUREMENT,
    CONF_MAC,
    EVENT_CORE_CONFIG_UPDATE,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import (
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import UNDEFINED
from homeassistant.util.unit_conversion import TemperatureConverter

from .const import (
    ATTR_EXTERNAL_HUMIDITY_SENSOR,
    ATTR_EXTERNAL_TEMPERATURE_SENSOR,
    CONF_ADVANCED,
    CONF_DEVICES,
    CONF_DISABLE_AVAILABLE_CHECK,
    CONF_FAN_MODES,
    CONF_HVAC_MODES,
    CONF_RESTORE_STATES,
    CONF_SWING_HORIZONTAL_MODES,
    CONF_SWING_MODES,
    CONF_TEMPERATURE_STEP,
    DEFAULT_FAN_MODES,
    DEFAULT_HVAC_MODES,
    DEFAULT_SWING_HORIZONTAL_MODES,
    DEFAULT_SWING_MODES,
    DEFAULT_TARGET_TEMP_STEP,
    DOMAIN,
    GATTR_FEAT_QUIET_MODE,
    GATTR_FEAT_TURBO,
    HVAC_MODES_GREE_TO_HA,
    HVAC_MODES_HA_TO_GREE,
    UNITS_GREE_TO_HA,
)
from .coordinator import GreeConfigEntry, GreeCoordinator
from .entity import GreeEntity, GreeEntityDescription
from .gree_api import (
    MAX_TEMP_C,
    MAX_TEMP_F,
    MIN_TEMP_C,
    MIN_TEMP_F,
    FanSpeed,
    GreeProp,
    HorizontalSwingMode,
    VerticalSwingMode,
)

_LOGGER = logging.getLogger(__name__)

GATTR_CLIMATE = "hvac"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GreeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors from a config entry."""

    entities: list[GreeClimate] = []

    for d in entry.data.get(CONF_DEVICES, []):
        coordinator: GreeCoordinator = entry.runtime_data[d.get(CONF_MAC, "")]
        if not coordinator:
            _LOGGER.error(
                "Cannot create Gree Climate. No coordinator found for device '%s'",
                d.get(CONF_MAC, ""),
            )

        hvac_modes: list[HVACMode] = [
            HVACMode[mode.upper()]
            for mode in (
                d[CONF_HVAC_MODES]
                if d[CONF_HVAC_MODES] is not None
                else DEFAULT_HVAC_MODES
            )
        ]

        fan_modes: list[str] = (
            d[CONF_FAN_MODES] if d[CONF_FAN_MODES] is not None else DEFAULT_FAN_MODES
        )

        swing_modes: list[str] = (
            d[CONF_SWING_MODES]
            if d[CONF_SWING_MODES] is not None
            else DEFAULT_SWING_MODES
        )

        swing_horizontal_modes: list[str] = (
            d[CONF_SWING_HORIZONTAL_MODES]
            if d[CONF_SWING_HORIZONTAL_MODES] is not None
            else DEFAULT_SWING_HORIZONTAL_MODES
        )

        if not hvac_modes:
            _LOGGER.info(
                "Climate Entity will not be created because no Climate options and features are available for the device"
            )
            return

        _LOGGER.debug(
            "Adding Climate Entity for device '%s'",
            coordinator.device.mac_address_sub,
        )

        entities.append(
            GreeClimate(
                GreeClimateDescription(
                    key=GATTR_CLIMATE,
                    translation_key=GATTR_CLIMATE,
                    available_func=lambda device: device.available,
                ),
                coordinator,
                hvac_modes,
                fan_modes,
                swing_modes,
                swing_horizontal_modes,
                temperature_step=entry.data.get(
                    CONF_TEMPERATURE_STEP, DEFAULT_TARGET_TEMP_STEP
                ),
                restore_state=(entry.data.get(CONF_RESTORE_STATES, True)),
                check_availability=(
                    entry.data[CONF_ADVANCED].get(CONF_DISABLE_AVAILABLE_CHECK, False)
                    is False
                ),
                external_temperature_sensor_id=entry.data.get(
                    ATTR_EXTERNAL_TEMPERATURE_SENSOR
                ),
                external_humidity_sensor_id=entry.data.get(
                    ATTR_EXTERNAL_HUMIDITY_SENSOR
                ),
            )
        )

    async_add_entities(entities)


@dataclass(frozen=True, kw_only=True)
class GreeClimateDescription(GreeEntityDescription, ClimateEntityDescription):
    """Description of a Gree Climate entity."""

    device_class = None
    entity_category = None
    entity_registry_enabled_default = True
    entity_registry_visible_default = True
    force_update = False
    icon = None
    has_entity_name = True
    name = UNDEFINED
    translation_key = None
    translation_placeholders = None
    unit_of_measurement = None


class GreeClimate(GreeEntity, ClimateEntity, RestoreEntity):  # pyright: ignore[reportIncompatibleVariableOverride]
    """Climate Entity."""

    def __init__(
        self,
        description: GreeClimateDescription,
        coordinator: GreeCoordinator,
        hvac_modes: list[HVACMode],
        fan_modes: list[str],
        swing_modes: list[str],
        swing_horizontal_modes: list[str],
        temperature_step: int,
        restore_state: bool = True,
        check_availability: bool = True,
        external_temperature_sensor_id: str | None = None,
        external_humidity_sensor_id: str | None = None,
    ) -> None:
        """Initialize the Gree Climate entity."""
        super().__init__(description, coordinator, restore_state, check_availability)

        self.entity_description = description
        self._attr_name = None  # Main entity

        self._external_temperature_sensor = external_temperature_sensor_id
        self._external_humidity_sensor = external_humidity_sensor_id

        self._attr_target_temperature_step = temperature_step

        self._attr_hvac_modes = hvac_modes

        if hvac_modes and HVACMode.OFF in hvac_modes:
            self._attr_supported_features |= ClimateEntityFeature.TURN_OFF

        if any(mode != HVACMode.OFF for mode in hvac_modes):
            self._attr_supported_features |= ClimateEntityFeature.TURN_ON

        if any(
            mode in hvac_modes for mode in (HVACMode.HEAT, HVACMode.COOL, HVACMode.AUTO)
        ):
            self._attr_supported_features |= ClimateEntityFeature.TARGET_TEMPERATURE

        if fan_modes:
            self._attr_supported_features |= ClimateEntityFeature.FAN_MODE
            self._attr_fan_modes = fan_modes
        else:
            self._attr_fan_modes = None

        if swing_modes:
            self._attr_supported_features |= ClimateEntityFeature.SWING_MODE
            self._attr_swing_modes = swing_modes
        else:
            self._attr_swing_modes = None

        if swing_horizontal_modes:
            self._attr_supported_features |= ClimateEntityFeature.SWING_HORIZONTAL_MODE
            self._attr_swing_horizontal_modes = swing_horizontal_modes
        else:
            self._attr_swing_horizontal_modes = None

        self._update_attributes()
        _LOGGER.debug(
            "Initialized climate: %s (check_availability=%s) Features:\n%s",
            self._attr_unique_id,
            self.check_availability,
            repr(self._attr_supported_features),
        )

    async def async_added_to_hass(self):
        """When this entity is added to hass."""
        await super().async_added_to_hass()

        self._update_attributes()

        # Restore last HA state to device if applicable
        if self.restore_state:
            await self._restore_entity_state()

        # When using an external temperature sensor, subscribe to its state changes for updating the current temperature
        if (
            self._external_temperature_sensor
            and self._external_temperature_sensor != "None"
        ):
            self._update_current_temperature_from_external(
                self.hass.states.get(self._external_temperature_sensor)
            )
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    [self._external_temperature_sensor],
                    self._external_temperature_sensor_listener,
                )
            )

        # When using an external himidity sensor, subscribe to its state changes for updating the current humidity
        if self._external_humidity_sensor and self._external_humidity_sensor != "None":
            self._update_current_humidity_from_external(
                self.hass.states.get(self._external_humidity_sensor)
            )
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    [self._external_humidity_sensor],
                    self._external_humidity_sensor_listener,
                )
            )

        # Refresh entity when HA unit system changes
        self.async_on_remove(
            self.hass.bus.async_listen(
                EVENT_CORE_CONFIG_UPDATE, self._handle_unit_change
            )
        )

    async def _restore_entity_state(self):
        last_state = await self.async_get_last_state()
        if last_state is not None:
            _LOGGER.debug(
                "Restoring state for %s:\n%s",
                self.entity_id,
                last_state,
            )

            # hvac mode
            if last_state.state not in [None, STATE_UNKNOWN, STATE_UNAVAILABLE]:
                last_hvac_mode: HVACMode | None = HVACMode(last_state.state)
                if (
                    last_hvac_mode
                    and last_hvac_mode != self._attr_hvac_mode
                    and last_hvac_mode in self._attr_hvac_modes
                ):
                    try:
                        await self.async_set_hvac_mode(last_hvac_mode)
                    except Exception:
                        _LOGGER.exception(
                            "Failed to restore the hvac_mode: %s", last_hvac_mode
                        )
                else:
                    _LOGGER.debug(
                        "No need to restore the hvac_mode: %s",
                        last_hvac_mode,
                    )

            # fan mode
            last_fan_mode: str | None = last_state.attributes.get(ATTR_FAN_MODE)
            if (
                last_fan_mode not in [None, STATE_UNKNOWN, STATE_UNAVAILABLE]
                and self._attr_fan_modes
                and last_fan_mode != self._attr_fan_mode
                and last_fan_mode in self._attr_fan_modes
            ):
                try:
                    await self.async_set_fan_mode(last_fan_mode)
                except Exception:
                    _LOGGER.exception(
                        "Failed to restore the fan_mode: %s", last_fan_mode
                    )
            else:
                _LOGGER.debug(
                    "No need to restore the fan_mode: %s",
                    last_fan_mode,
                )

            # swings
            last_swing_mode: str | None = last_state.attributes.get(ATTR_SWING_MODE)
            if (
                last_swing_mode not in [None, STATE_UNKNOWN, STATE_UNAVAILABLE]
                and self._attr_swing_modes
                and last_swing_mode != self._attr_swing_mode
                and last_swing_mode in self._attr_swing_modes
            ):
                try:
                    await self.async_set_swing_mode(last_swing_mode)
                except Exception:
                    _LOGGER.exception(
                        "Failed to restore the swing_mode: %s", last_swing_mode
                    )
            else:
                _LOGGER.debug(
                    "No need to restore the swing_mode: %s",
                    last_swing_mode,
                )

            last_swing_horizontal_mode: str | None = last_state.attributes.get(
                ATTR_SWING_HORIZONTAL_MODE
            )
            if (
                last_swing_horizontal_mode
                not in [None, STATE_UNKNOWN, STATE_UNAVAILABLE]
                and self.swing_horizontal_modes
                and last_swing_horizontal_mode != self.swing_horizontal_mode
                and last_swing_horizontal_mode in self.swing_horizontal_modes
            ):
                try:
                    await self.async_set_swing_horizontal_mode(
                        last_swing_horizontal_mode
                    )
                except Exception:
                    _LOGGER.exception(
                        "Failed to restore the swing_horizontal_mode: %s",
                        last_swing_horizontal_mode,
                    )
            else:
                _LOGGER.debug(
                    "No need to restore the swing_horizontal_mode: %s",
                    last_swing_horizontal_mode,
                )

            # target temp
            last_target_temperature: float | None = last_state.attributes.get(
                ATTR_TEMPERATURE
            )
            if last_target_temperature is not None and last_target_temperature not in [
                STATE_UNKNOWN,
                STATE_UNAVAILABLE,
            ]:
                # since the ºC and ºF ranges don't overlap we can guess the last state units
                last_unit: UnitOfTemperature = (
                    UnitOfTemperature.CELSIUS
                    if last_target_temperature <= MAX_TEMP_C
                    else UnitOfTemperature.FAHRENHEIT
                )
                last_target_temperature = TemperatureConverter.convert(
                    last_target_temperature,
                    last_unit,
                    self._attr_temperature_unit,
                )
                if (
                    self._attr_supported_features
                    & ClimateEntityFeature.TARGET_TEMPERATURE
                    and last_target_temperature != self._attr_target_temperature
                ):
                    try:
                        await self.async_set_temperature(
                            **{ATTR_TEMPERATURE: last_target_temperature}
                        )
                    except Exception:
                        _LOGGER.exception(
                            "Failed to restore the target_temperature: %s%s",
                            last_target_temperature,
                            last_unit,
                        )
                else:
                    _LOGGER.debug(
                        "No need to restore the target_temperature: %s%s",
                        last_target_temperature,
                        self.temperature_unit,
                    )

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        _LOGGER.debug("Updating Climate Entity for %s", self.device.unique_id)
        self._update_attributes()

    @callback
    def _external_temperature_sensor_listener(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """Update current temperature based on external sensor updates."""
        new_state = event.data.get("new_state")
        self._update_current_temperature_from_external(new_state)

    def _update_current_temperature_from_external(self, new_state: State | None):
        """Update current temperature based on external sensor data."""
        if new_state and new_state.state not in (
            STATE_UNKNOWN,
            STATE_UNAVAILABLE,
        ):
            try:
                unit: str = new_state.attributes.get(
                    ATTR_UNIT_OF_MEASUREMENT, UnitOfTemperature.CELSIUS
                )
                value = float(new_state.state)

            except (ValueError, TypeError) as ex:
                _LOGGER.error(
                    "Unable to update from external temp sensor %s: %s",
                    self._external_temperature_sensor,
                    ex,
                )
            else:
                _LOGGER.debug(
                    "Using external temperature sensor: %s, value: %s, unit: %s",
                    self._external_temperature_sensor,
                    value,
                    unit,
                )
                # Update internal state based on the other entity
                self._attr_current_temperature = self.hass.config.units.temperature(
                    value, unit
                )
                self.async_write_ha_state()

    @callback
    def _external_humidity_sensor_listener(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """Update current humidity based on external sensor updates."""
        new_state = event.data.get("new_state")
        self._update_current_humidity_from_external(new_state)

    def _update_current_humidity_from_external(self, new_state: State | None) -> None:
        """Update current humidity based on external sensor updates."""
        if new_state and new_state.state not in (
            STATE_UNKNOWN,
            STATE_UNAVAILABLE,
        ):
            try:
                value = float(new_state.state)

            except (ValueError, TypeError) as ex:
                _LOGGER.error(
                    "Unable to update from humidity temp sensor %s: %s",
                    self._external_humidity_sensor,
                    ex,
                )
            else:
                _LOGGER.debug(
                    "Using external humidity sensor: %s, value: %s",
                    self._external_humidity_sensor,
                    value,
                )
                self._attr_current_humidity = value

    async def _handle_unit_change(self, event):
        """Handle HA unit system change (°C <-> °F)."""
        # Force refresh from coordinator
        await self.coordinator.async_request_refresh()

    def _update_attributes(self):
        """Updates the entity attributes with the device values."""
        self._attr_available = self.device.available

        if (
            self._attr_supported_features
            & (
                ClimateEntityFeature.TURN_ON
                | ClimateEntityFeature.TURN_OFF
                | ClimateEntityFeature.TARGET_TEMPERATURE
            )
            or HVACMode.FAN_ONLY in self._attr_hvac_modes
        ):
            self._attr_hvac_mode = self.get_hvac_mode()

        if self._attr_supported_features & ClimateEntityFeature.FAN_MODE:
            self._attr_fan_mode = self.get_fan_mode()
        if self._attr_supported_features & ClimateEntityFeature.SWING_MODE:
            self._attr_swing_mode = self.get_swing_mode()
        if self._attr_supported_features & ClimateEntityFeature.SWING_HORIZONTAL_MODE:
            self._attr_swing_horizontal_mode = self.get_swing_horizontal_mode()

        self._attr_temperature_unit = self.get_temp_units()
        self._attr_target_temperature = self.get_current_target_temp()

        if (
            self._external_temperature_sensor is None
            or self._external_temperature_sensor == "None"
        ):
            self._attr_current_temperature = self.get_current_temp()

        if (
            self._external_humidity_sensor is None
            or self._external_humidity_sensor == "None"
        ):
            self._attr_current_humidity = self.get_current_humidity()

        if self._attr_supported_features & ClimateEntityFeature.TARGET_TEMPERATURE:
            self._attr_max_temp = (
                MAX_TEMP_C
                if self._attr_temperature_unit == UnitOfTemperature.CELSIUS
                else MAX_TEMP_F
            )

            self._attr_min_temp = (
                MIN_TEMP_C
                if self._attr_temperature_unit == UnitOfTemperature.CELSIUS
                else MIN_TEMP_F
            )

        if self.hass:
            self.async_write_ha_state()

    async def async_turn_on(self):
        """Turn on."""
        _LOGGER.debug("turn_on(%s)", self.device.unique_id)

        if not self.available:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="entity_unavailable"
            )

        try:
            self.device.set_power_mode(True)

            # If Auto Light is enabled, turn the display lights on
            if self.coordinator.feature_auto_light:
                self.device.set_feature_light(True)

            await self.device.update_device_status()

            self.async_write_ha_state()

            # notify coordinator listeners of state change so that dependent entities are updated immediately
            self.coordinator.async_update_listeners()
        except Exception as err:
            _LOGGER.exception("Error in '%s'", "async_turn_on")
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="generic"
            ) from err

        finally:
            await self.coordinator.async_request_refresh()

    async def async_turn_off(self):
        """Turn off."""
        _LOGGER.debug("turn_off(%s)", self.device.unique_id)

        if not self.available:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="entity_unavailable"
            )

        try:
            self.device.set_power_mode(False)

            # If Auto Light is enabled, turn the display lights off
            if self.coordinator.feature_auto_light:
                self.device.set_feature_light(False)

            await self.device.update_device_status()

            self.async_write_ha_state()

            # notify coordinator listeners of state change so that dependent entities are updated immediately
            self.coordinator.async_update_listeners()

        except Exception as err:
            _LOGGER.exception("Error in '%s'", "async_turn_off")
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="generic"
            ) from err

        finally:
            await self.coordinator.async_request_refresh()

    def get_hvac_mode(self) -> HVACMode:
        """Converts Gree Operation Modes to HA."""
        return (
            HVACMode.OFF
            if not self.device.power_mode
            else HVAC_MODES_GREE_TO_HA[self.device.operation_mode]
        )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode):
        """Set the HVAC Mode."""
        _LOGGER.debug("set_hvac_mode(%s, %s)", self.device.unique_id, hvac_mode)

        if not self.available:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="entity_unavailable"
            )

        try:
            if hvac_mode == HVACMode.OFF:
                await self.async_turn_off()
                # This will be called in the turn on
                # await self._device.update_device_status()
            else:
                self.device.set_operation_mode(HVAC_MODES_HA_TO_GREE[hvac_mode])

                # The Auto X-FAN enables that feature if the device is set to a hvac mode that supports X-FAN
                if self.coordinator.feature_auto_xfan:
                    self.device.set_feature_xfan(
                        hvac_mode in (HVACMode.COOL, HVACMode.DRY)
                    )

                await self.async_turn_on()

                # This will be called in the turn on
                # await self._device.update_device_status()

            # notify coordinator listeners of state change so that dependent entities are updated immediately
            self.coordinator.async_update_listeners()

            await self.coordinator.async_request_refresh()
        except Exception as err:
            _LOGGER.exception("Error in '%s'", "async_set_hvac_mode")
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="generic"
            ) from err

        self.async_write_ha_state()

    def get_fan_mode(self) -> str:
        """Converts Gree Fan Modes to HA. Accounts for the 2 special modes."""
        if GATTR_FEAT_QUIET_MODE in self._attr_hvac_modes and self.device.feature_quiet:
            return GATTR_FEAT_QUIET_MODE

        if GATTR_FEAT_TURBO in self._attr_hvac_modes and self.device.feature_turbo:
            return GATTR_FEAT_TURBO

        return self.device.fan_speed.name

    async def async_set_fan_mode(self, fan_mode: str):
        """Set new target fan mode."""
        _LOGGER.debug(
            "set_fan_mode(%s, %s -> %s)",
            self.device.unique_id,
            self.get_fan_mode(),
            fan_mode,
        )

        if not self.available:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="entity_unavailable"
            )

        if fan_mode == GATTR_FEAT_TURBO and self._attr_hvac_mode in (
            HVACMode.DRY,
            HVACMode.FAN_ONLY,
        ):
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="turbo_availability"
            )

        if fan_mode == GATTR_FEAT_QUIET_MODE and self._attr_hvac_mode not in (
            HVACMode.DRY,
            HVACMode.COOL,
        ):
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="quiet_availability"
            )

        try:
            self.device.set_feature_quiet(fan_mode == GATTR_FEAT_QUIET_MODE)
            self.device.set_feature_turbo(fan_mode == GATTR_FEAT_TURBO)

            if fan_mode not in (GATTR_FEAT_QUIET_MODE, GATTR_FEAT_TURBO):
                self.device.set_fan_speed(FanSpeed[fan_mode])

            await self.device.update_device_status()

            # notify coordinator listeners of state change so that dependent entities are updated immediately
            self.coordinator.async_update_listeners()

            await self.coordinator.async_request_refresh()
        except Exception as err:
            _LOGGER.exception("Error in '%s'", "async_set_fan_mode")
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="generic"
            ) from err

        self.async_write_ha_state()

    def get_swing_mode(self) -> str:
        """Converts Gree Swing Modes to HA."""
        return self.device.vertical_swing_mode.name

    async def async_set_swing_mode(self, swing_mode):
        """Set new target swing operation."""
        _LOGGER.debug("async_set_swing_mode(%s, %s)", self.device.unique_id, swing_mode)

        if not self.available:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="entity_unavailable"
            )

        try:
            self.device.set_vertical_swing_mode(VerticalSwingMode[swing_mode])
            await self.device.update_device_status()

            # notify coordinator listeners of state change so that dependent entities are updated immediately
            self.coordinator.async_update_listeners()

            await self.coordinator.async_request_refresh()
        except Exception as err:
            _LOGGER.exception("Error in '%s'", "async_set_swing_mode")
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="generic"
            ) from err

        self.async_write_ha_state()

    def get_swing_horizontal_mode(self) -> str:
        """Converts Gree Swing Horizontal Modes to HA."""
        return self.device.horizontal_swing_mode.name

    async def async_set_swing_horizontal_mode(self, swing_horizontal_mode):
        """Set new target horizontal swing operation."""
        _LOGGER.debug(
            "async_set_swing_horizontal_mode(%s, %s)",
            self.device.unique_id,
            swing_horizontal_mode,
        )

        if not self.available:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="entity_unavailable"
            )

        try:
            self.device.set_horizontal_swing_mode(
                HorizontalSwingMode[swing_horizontal_mode]
            )
            await self.device.update_device_status()

            # notify coordinator listeners of state change so that dependent entities are updated immediately
            self.coordinator.async_update_listeners()

            await self.coordinator.async_request_refresh()
        except Exception as err:
            _LOGGER.exception("Error in '%s'", "async_set_swing_horizontal_mode")
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="generic"
            ) from err

        self.async_write_ha_state()

    def get_temp_units(self) -> UnitOfTemperature:
        """Returns the device units of temperature."""
        return UNITS_GREE_TO_HA[self.device.target_temperature_unit]

    def get_current_temp(self) -> float | None:
        """Returns the current temperature of the room. Accounting for units."""

        # Gree API always return current temperature in ºC
        # so here we need to convert to the unit of the entity (same as device)
        if (
            self.hass
            and self.device.supports_property(GreeProp.SENSOR_TEMPERATURE)
            and self.device.indoors_temperature_c is not None
        ):
            return TemperatureConverter.convert(
                float(self.device.indoors_temperature_c),
                UnitOfTemperature.CELSIUS,
                self._attr_temperature_unit,
            )

        return None

    def get_current_humidity(self) -> float | None:
        """Returns the current humidity of the room."""

        # Gree API always return current humidity in %
        if (
            self.device.supports_property(GreeProp.SENSOR_HUMIDITY)
            and self.device.humidity is not None
        ):
            return float(self.device.humidity)

        return None

    def get_current_target_temp(self) -> float | None:
        """Returns the current target temperature set on the device."""
        # Device already return in the temperature_units
        return self.device.target_temperature

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        _LOGGER.debug("async_set_temperature(%s, %s)", self.device.unique_id, kwargs)

        temperature: float | None = kwargs.get(ATTR_TEMPERATURE)
        hvac_mode: HVACMode | None = kwargs.get(ATTR_HVAC_MODE)

        if temperature is None:
            _LOGGER.error("No temperature received to set as target")
            return

        if not self.available:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="entity_unavailable"
            )

        try:
            # TODO: Confirm that HA sends the values in this entity's temperature_unit which matches the device unit
            self.device.set_target_temperature(temperature)

            if hvac_mode and hvac_mode in self._attr_hvac_modes:
                # This will call the set_hvac_mode which internally will send to device
                await self.async_set_hvac_mode(hvac_mode)
            else:
                await self.device.update_device_status()

                # notify coordinator listeners of state change so that dependent entities are updated immediately
                self.coordinator.async_update_listeners()

                await self.coordinator.async_request_refresh()
        except Exception as err:
            _LOGGER.exception("Error in '%s'", "async_set_temperature")
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="generic"
            ) from err

        self.async_write_ha_state()
