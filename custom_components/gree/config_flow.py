"""Config flow for Gree climate integration."""

from __future__ import annotations

# Standard library imports
import logging

# Third-party imports
import voluptuous as vol

# Home Assistant imports
from homeassistant import config_entries
from homeassistant.const import (
    CONF_HOST,
    CONF_MAC,
    CONF_NAME,
    CONF_PORT,
    CONF_TIMEOUT,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

# Local imports
from .const import (
    CONF_DISABLE_AVAILABLE_CHECK,
    CONF_ENCRYPTION_KEY,
    CONF_ENCRYPTION_VERSION,
    CONF_FAN_MODES,
    CONF_HVAC_MODES,
    CONF_MAX_ONLINE_ATTEMPTS,
    CONF_SWING_HORIZONTAL_MODES,
    CONF_SWING_MODES,
    CONF_TEMP_SENSOR_OFFSET,
    CONF_UID,
    DEFAULT_FAN_MODES,
    DEFAULT_HVAC_MODES,
    DEFAULT_PORT,
    DEFAULT_SWING_HORIZONTAL_MODES,
    DEFAULT_SWING_MODES,
    DEFAULT_TIMEOUT,
    DOMAIN,
    OPTION_KEYS,
)

_LOGGER = logging.getLogger(__name__)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Gree climate."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, any] = {}

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        """Handle the initial step."""
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(title=user_input.get(CONF_NAME) or "Gree Climate", data=self._data)

        data_schema = vol.Schema(
            {
                vol.Required(CONF_NAME): str,
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_MAC): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
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
            _LOGGER.debug("Raw user options input: %s", user_input)
            normalized_input: dict[str, str | None] = {}
            # Only handle known option keys
            for key in OPTION_KEYS:
                if key in user_input:
                    value = user_input[key]
                    normalized_input[key] = value if value not in (None, "") else None
                elif key in self.config_entry.options:
                    normalized_input[key] = None
            _LOGGER.debug("Normalized options to save: %s", normalized_input)
            result = self.async_create_entry(title="", data=normalized_input)
            _LOGGER.debug("Creating entry with options: %s", normalized_input)
            return result

        options = {key: value for key, value in self.config_entry.options.items() if key in OPTION_KEYS}
        _LOGGER.debug("Current stored options: %s", options)
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_HVAC_MODES,
                    description={"suggested_value": options.get(CONF_HVAC_MODES, DEFAULT_HVAC_MODES)},
                    default=options.get(CONF_HVAC_MODES, DEFAULT_HVAC_MODES),
                ): vol.Any(None, selector.SelectSelector(selector.SelectSelectorConfig(options=DEFAULT_HVAC_MODES, multiple=True, custom_value=True, translation_key=CONF_HVAC_MODES))),
                vol.Optional(
                    CONF_FAN_MODES,
                    description={"suggested_value": options.get(CONF_FAN_MODES, DEFAULT_FAN_MODES)},
                    default=options.get(CONF_FAN_MODES, DEFAULT_FAN_MODES),
                ): vol.Any(None, selector.SelectSelector(selector.SelectSelectorConfig(options=DEFAULT_FAN_MODES, multiple=True, custom_value=True, translation_key=CONF_FAN_MODES))),
                vol.Optional(
                    CONF_SWING_MODES,
                    description={"suggested_value": options.get(CONF_SWING_MODES, DEFAULT_SWING_MODES)},
                    default=options.get(CONF_SWING_MODES, DEFAULT_SWING_MODES),
                ): vol.Any(None, selector.SelectSelector(selector.SelectSelectorConfig(options=DEFAULT_SWING_MODES, multiple=True, custom_value=True, translation_key=CONF_SWING_MODES))),
                vol.Optional(
                    CONF_SWING_HORIZONTAL_MODES,
                    description={"suggested_value": options.get(CONF_SWING_HORIZONTAL_MODES, DEFAULT_SWING_HORIZONTAL_MODES)},
                    default=options.get(CONF_SWING_HORIZONTAL_MODES, DEFAULT_SWING_HORIZONTAL_MODES),
                ): vol.Any(None, selector.SelectSelector(selector.SelectSelectorConfig(options=DEFAULT_SWING_HORIZONTAL_MODES, multiple=True, custom_value=True, translation_key=CONF_SWING_HORIZONTAL_MODES))),
                vol.Optional(
                    CONF_DISABLE_AVAILABLE_CHECK,
                    default=options.get(CONF_DISABLE_AVAILABLE_CHECK, False),
                ): bool,
                vol.Optional(
                    CONF_MAX_ONLINE_ATTEMPTS,
                    default=options.get(CONF_MAX_ONLINE_ATTEMPTS, 3),
                ): int,
                vol.Optional(
                    CONF_TEMP_SENSOR_OFFSET,
                    description={"suggested_value": options.get(CONF_TEMP_SENSOR_OFFSET)},
                ): vol.Any(None, bool),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
