"""Config flow to configure the Gree integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol
from voluptuous.schema_builder import UNDEFINED

from homeassistant import config_entries
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import section
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
)

from .const import (
    ATTR_EXTERNAL_HUMIDITY_SENSOR,
    ATTR_EXTERNAL_TEMPERATURE_SENSOR,
    CONF_ADVANCED,
    CONF_DISABLE_AVAILABLE_CHECK,
    CONF_ENCRYPTION_KEY,
    CONF_ENCRYPTION_VERSION,
    CONF_FAN_MODES,
    CONF_FEATURES,
    CONF_HVAC_MODES,
    CONF_MAX_ONLINE_ATTEMPTS,
    CONF_SWING_HORIZONTAL_MODES,
    CONF_SWING_MODES,
    CONF_TEMP_SENSOR_OFFSET,
    CONF_UID,
    DEFAULT_FAN_MODES,
    DEFAULT_HVAC_MODES,
    DEFAULT_MAX_ONLINE_ATTEMPTS,
    DEFAULT_PORT,
    DEFAULT_SUPPORTED_FEATURES,
    DEFAULT_SWING_HORIZONTAL_MODES,
    DEFAULT_SWING_MODES,
    DEFAULT_UID,
    DOMAIN,
)
from .coordinator import GreeConfigEntry
from .gree_device import GreeDevice

_LOGGER = logging.getLogger(__name__)


def build_main_schema(data: Mapping | None) -> vol.Schema | None:
    """Builds the main option schema."""
    return vol.Schema(
        {
            vol.Required(
                CONF_NAME, default="AC" if data is None else data.get(CONF_NAME, "")
            ): str,
            vol.Required(
                CONF_HOST,
                default="192.168.1.103" if data is None else data.get(CONF_HOST, ""),
            ): str,
            vol.Required(
                CONF_MAC,
                default="C0:39:37:B1:22:80" if data is None else data.get(CONF_MAC, ""),
            ): str,
            vol.Required(CONF_ADVANCED): section(
                vol.Schema(
                    {
                        vol.Required(
                            CONF_PORT,
                            default=DEFAULT_PORT
                            if data is None or data[CONF_ADVANCED] is None
                            else data[CONF_ADVANCED].get(CONF_PORT, DEFAULT_PORT),
                        ): int,
                        vol.Required(
                            CONF_ENCRYPTION_VERSION,
                            default="Auto-Detect"
                            if data is None or data[CONF_ADVANCED] is None
                            else data[CONF_ADVANCED].get(
                                CONF_ENCRYPTION_VERSION, "Auto-Detect"
                            ),
                        ): vol.In(["Auto-Detect", "1", "2"]),
                        vol.Optional(
                            CONF_ENCRYPTION_KEY,
                            default=""
                            if data is None or data[CONF_ADVANCED] is None
                            else data[CONF_ADVANCED].get(CONF_ENCRYPTION_KEY, ""),
                        ): str,
                        vol.Required(
                            CONF_UID,
                            default=DEFAULT_UID
                            if data is None or data[CONF_ADVANCED] is None
                            else data[CONF_ADVANCED].get(CONF_UID, DEFAULT_UID),
                        ): int,
                    }
                ),
                {"collapsed": True},
            ),
        }
    )


def build_options_schema(
    hass: HomeAssistant, data: Mapping | None
) -> vol.Schema | None:
    """Builds the device option schema."""

    return vol.Schema(
        {
            vol.Optional(
                CONF_HVAC_MODES,
                default=DEFAULT_HVAC_MODES
                if data is None
                else data.get(CONF_HVAC_MODES, DEFAULT_HVAC_MODES),
            ): SelectSelector(
                config=SelectSelectorConfig(
                    options=DEFAULT_HVAC_MODES,
                    multiple=True,
                    translation_key=CONF_HVAC_MODES,
                )
            ),
            vol.Optional(
                CONF_FAN_MODES,
                default=DEFAULT_FAN_MODES
                if data is None
                else data.get(CONF_FAN_MODES, DEFAULT_FAN_MODES),
            ): SelectSelector(
                config=SelectSelectorConfig(
                    options=DEFAULT_FAN_MODES,
                    multiple=True,
                    translation_key=CONF_FAN_MODES,
                )
            ),
            vol.Optional(
                CONF_SWING_MODES,
                default=DEFAULT_SWING_MODES
                if data is None
                else data.get(CONF_SWING_MODES, DEFAULT_SWING_MODES),
            ): SelectSelector(
                config=SelectSelectorConfig(
                    options=DEFAULT_SWING_MODES,
                    multiple=True,
                    translation_key=CONF_SWING_MODES,
                )
            ),
            vol.Optional(
                CONF_SWING_HORIZONTAL_MODES,
                default=DEFAULT_SWING_HORIZONTAL_MODES
                if data is None
                else data.get(
                    CONF_SWING_HORIZONTAL_MODES, DEFAULT_SWING_HORIZONTAL_MODES
                ),
            ): SelectSelector(
                config=SelectSelectorConfig(
                    options=DEFAULT_SWING_HORIZONTAL_MODES,
                    multiple=True,
                    translation_key=CONF_SWING_HORIZONTAL_MODES,
                )
            ),
            vol.Optional(
                CONF_FEATURES,
                default=DEFAULT_SUPPORTED_FEATURES
                if data is None
                else data.get(CONF_FEATURES, DEFAULT_SUPPORTED_FEATURES),
            ): SelectSelector(
                config=SelectSelectorConfig(
                    options=DEFAULT_SUPPORTED_FEATURES,
                    multiple=True,
                    translation_key=CONF_FEATURES,
                )
            ),
            vol.Optional(
                CONF_MAX_ONLINE_ATTEMPTS,
                default=DEFAULT_MAX_ONLINE_ATTEMPTS
                if data is None
                else data.get(CONF_MAX_ONLINE_ATTEMPTS, DEFAULT_MAX_ONLINE_ATTEMPTS),
            ): cv.positive_int,
            vol.Optional(
                CONF_DISABLE_AVAILABLE_CHECK,
                default=False
                if data is None
                else data.get(CONF_DISABLE_AVAILABLE_CHECK, False),
            ): cv.boolean,
            vol.Optional(
                CONF_TEMP_SENSOR_OFFSET,
                default=False if data is None else data.get(CONF_TEMP_SENSOR_OFFSET, 0),
            ): cv.boolean,
            vol.Optional(
                ATTR_EXTERNAL_TEMPERATURE_SENSOR,
                default=UNDEFINED
                if data is None
                else data.get(ATTR_EXTERNAL_TEMPERATURE_SENSOR, UNDEFINED),
            ): EntitySelector(
                config=EntitySelectorConfig(
                    multiple=False,
                    domain="sensor",
                    device_class=SensorDeviceClass.TEMPERATURE,
                )
            ),
            vol.Optional(
                ATTR_EXTERNAL_HUMIDITY_SENSOR,
                default=UNDEFINED
                if data is None
                else data.get(ATTR_EXTERNAL_HUMIDITY_SENSOR, UNDEFINED),
            ): EntitySelector(
                config=EntitySelectorConfig(
                    multiple=False,
                    domain="sensor",
                    device_class=SensorDeviceClass.HUMIDITY,
                )
            ),
        }
    )


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow from user."""

    VERSION = 2

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._step_main_data: dict | None = None
        self._device: GreeDevice | None = None

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            try:
                self._device = GreeDevice(
                    user_input[CONF_NAME],
                    user_input[CONF_HOST],
                    user_input[CONF_MAC],
                    user_input[CONF_ADVANCED][CONF_PORT],
                    int(user_input[CONF_ADVANCED][CONF_ENCRYPTION_VERSION])
                    if user_input[CONF_ADVANCED][CONF_ENCRYPTION_VERSION]
                    != "Auto-Detect"
                    else 0,
                    user_input[CONF_ADVANCED][CONF_ENCRYPTION_KEY],
                    user_input[CONF_ADVANCED][CONF_UID],
                    max_connection_attempts=2,  # Use fewer attempts for testing the device
                )
                await self._device.fetch_device_status()
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception as err:  # noqa: BLE001
                errors["base"] = "unknown: " + repr(err)
            else:
                self._step_main_data = user_input
                self._step_main_data["advanced"].update(
                    {
                        CONF_ENCRYPTION_VERSION: self._device.encryption_version,
                        CONF_ENCRYPTION_KEY: self._device.encryption_key,
                    }
                )
                await self.async_set_unique_id(format_mac(self._device.unique_id))
                self._abort_if_unique_id_configured()

                return await self.async_step_device_options()

        return self.async_show_form(
            step_id="user", data_schema=build_main_schema(user_input), errors=errors
        )

    async def async_step_device_options(
        self, user_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:
        """Second step: configure features/modes."""
        if (
            user_input is not None
            and self._step_main_data is not None
            and self._device is not None
        ):
            data = {**self._step_main_data, **user_input}
            await self.async_set_unique_id(self._device.unique_id)
            self._abort_if_unique_id_configured()
            _LOGGER.debug("New entry with config: %s", data)
            return self.async_create_entry(
                title=self._step_main_data[CONF_NAME], data=data
            )

        return self.async_show_form(
            step_id="device_options",
            data_schema=build_options_schema(self.hass, user_input),
        )

    async def async_step_import(
        self, user_input: dict
    ) -> config_entries.ConfigFlowResult:
        """Handle import from configuration.yaml."""
        return await self.async_step_user(user_input)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None):
        """Handle reconfiguration of an existing entry."""
        entry: GreeConfigEntry = self._get_reconfigure_entry()

        _LOGGER.debug("Reconfiguring: %s", entry)
        await self.async_set_unique_id(entry.unique_id)

        if user_input is not None:
            self._abort_if_unique_id_mismatch()
            return self.async_update_reload_and_abort(
                entry,
                data_updates=user_input,
            )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=build_options_schema(
                self.hass, entry.data if entry.data is not None else user_input
            ),
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""
