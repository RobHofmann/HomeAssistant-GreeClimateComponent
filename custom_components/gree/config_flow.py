"""Config flow for Gree climate integration."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.const import (
    CONF_HOST,
    CONF_MAC,
    CONF_NAME,
    CONF_PORT,
    CONF_TIMEOUT,
)
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN
from .climate import (
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    DEFAULT_TARGET_TEMP_STEP,
    CONF_TARGET_TEMP_STEP,
    CONF_TEMP_SENSOR,
    CONF_LIGHTS,
    CONF_XFAN,
    CONF_HEALTH,
    CONF_POWERSAVE,
    CONF_SLEEP,
    CONF_EIGHTDEGHEAT,
    CONF_AIR,
    CONF_ENCRYPTION_KEY,
    CONF_UID,
    CONF_AUTO_XFAN,
    CONF_AUTO_LIGHT,
    CONF_TARGET_TEMP,
    CONF_HORIZONTAL_SWING,
    CONF_ANTI_DIRECT_BLOW,
    CONF_ENCRYPTION_VERSION,
    CONF_DISABLE_AVAILABLE_CHECK,
    CONF_MAX_ONLINE_ATTEMPTS,
    CONF_LIGHT_SENSOR,
    CONF_TEMP_SENSOR_OFFSET,
    CONF_LANGUAGE,
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Gree climate."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, any] = {}

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        """Handle the initial step."""
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(
                title=user_input.get(CONF_NAME) or "Gree Climate", data=self._data
            )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_MAC): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
                vol.Optional(CONF_NAME): str,
                vol.Optional(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): int,
                vol.Optional(CONF_ENCRYPTION_KEY): str,
                vol.Optional(CONF_UID): int,
                vol.Optional(CONF_ENCRYPTION_VERSION, default=1): int,
            }
        )
        return self.async_show_form(step_id="user", data_schema=data_schema)

    async def async_step_import(self, import_data: dict) -> FlowResult:
        """Handle configuration via YAML import."""
        return await self.async_step_user(import_data)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle an options flow for Gree climate."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = {**self.config_entry.options}
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_TARGET_TEMP_STEP,
                    default=options.get(
                        CONF_TARGET_TEMP_STEP, DEFAULT_TARGET_TEMP_STEP
                    ),
                ): vol.Coerce(float),
                vol.Optional(
                    CONF_TEMP_SENSOR, default=options.get(CONF_TEMP_SENSOR)
                ): vol.Any(
                    None,
                    selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="sensor")
                    ),
                ),
                vol.Optional(CONF_LIGHTS, default=options.get(CONF_LIGHTS)): vol.Any(
                    None,
                    selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="input_boolean")
                    ),
                ),
                vol.Optional(CONF_XFAN, default=options.get(CONF_XFAN)): vol.Any(
                    None,
                    selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="input_boolean")
                    ),
                ),
                vol.Optional(CONF_HEALTH, default=options.get(CONF_HEALTH)): vol.Any(
                    None,
                    selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="input_boolean")
                    ),
                ),
                vol.Optional(
                    CONF_POWERSAVE, default=options.get(CONF_POWERSAVE)
                ): vol.Any(
                    None,
                    selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="input_boolean")
                    ),
                ),
                vol.Optional(CONF_SLEEP, default=options.get(CONF_SLEEP)): vol.Any(
                    None,
                    selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="input_boolean")
                    ),
                ),
                vol.Optional(
                    CONF_EIGHTDEGHEAT, default=options.get(CONF_EIGHTDEGHEAT)
                ): vol.Any(
                    None,
                    selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="input_boolean")
                    ),
                ),
                vol.Optional(CONF_AIR, default=options.get(CONF_AIR)): vol.Any(
                    None,
                    selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="input_boolean")
                    ),
                ),
                vol.Optional(
                    CONF_TARGET_TEMP, default=options.get(CONF_TARGET_TEMP)
                ): vol.Any(
                    None,
                    selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="input_number")
                    ),
                ),
                vol.Optional(
                    CONF_AUTO_XFAN, default=options.get(CONF_AUTO_XFAN)
                ): vol.Any(
                    None,
                    selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="input_boolean")
                    ),
                ),
                vol.Optional(
                    CONF_AUTO_LIGHT, default=options.get(CONF_AUTO_LIGHT)
                ): vol.Any(
                    None,
                    selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="input_boolean")
                    ),
                ),
                vol.Optional(
                    CONF_HORIZONTAL_SWING,
                    default=options.get(CONF_HORIZONTAL_SWING, False),
                ): bool,
                vol.Optional(
                    CONF_ANTI_DIRECT_BLOW, default=options.get(CONF_ANTI_DIRECT_BLOW)
                ): vol.Any(
                    None,
                    selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="input_boolean")
                    ),
                ),
                vol.Optional(
                    CONF_DISABLE_AVAILABLE_CHECK,
                    default=options.get(CONF_DISABLE_AVAILABLE_CHECK, False),
                ): bool,
                vol.Optional(
                    CONF_MAX_ONLINE_ATTEMPTS,
                    default=options.get(CONF_MAX_ONLINE_ATTEMPTS, 3),
                ): int,
                vol.Optional(
                    CONF_LIGHT_SENSOR, default=options.get(CONF_LIGHT_SENSOR)
                ): vol.Any(
                    None,
                    selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="input_boolean")
                    ),
                ),
                vol.Optional(
                    CONF_TEMP_SENSOR_OFFSET,
                    default=options.get(CONF_TEMP_SENSOR_OFFSET),
                ): vol.Any(None, bool),
                vol.Optional(
                    CONF_LANGUAGE, default=options.get(CONF_LANGUAGE)
                ): vol.Any(None, str),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
