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
    CONF_SWING_HORIZONTAL_MODES,
    CONF_SWING_MODES,
    CONF_TEMP_SENSOR_OFFSET,
    CONF_UID,
    DEFAULT_FAN_MODES,
    DEFAULT_HVAC_MODES,
    DEFAULT_PORT,
    DEFAULT_SWING_HORIZONTAL_MODES,
    DEFAULT_SWING_MODES,
    DOMAIN,
    OPTION_KEYS,
)
from .gree_protocol import test_connection, discover_gree_devices, detect_device_encryption

_LOGGER = logging.getLogger(__name__)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Gree climate."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, any] = {}
        self._discovered_devices: list[dict] = []
        self._selected_device: dict | None = None

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        """Handle the initial step - show discovery or manual entry."""
        if user_input is not None:
            if user_input.get("discovery") == "discover":
                return await self.async_step_discovery()
            else:
                return await self.async_step_manual()

        # Show discovery vs manual choice
        data_schema = vol.Schema(
            {
                vol.Required("discovery", default="discover"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=["discover", "manual"],
                        translation_key="discovery_method",
                    )
                )
            }
        )
        return self.async_show_form(step_id="user", data_schema=data_schema)

    async def async_step_discovery(self, user_input: dict | None = None) -> FlowResult:
        """Handle device discovery."""
        if user_input is not None:
            # User selected a discovered device
            selected_device = user_input["device"]

            for device in self._discovered_devices:
                device_id = f"{device['mac']}_{device['host']}"
                if device_id == selected_device:
                    # Check if already configured
                    await self.async_set_unique_id(device["mac"])
                    self._abort_if_unique_id_configured()

                    # Store selected device for next step
                    self._selected_device = device
                    return await self.async_step_detect_encryption()

            # If no matching device found, something went wrong - go to manual
            return await self.async_step_manual()

        # Discover devices
        self._discovered_devices = await discover_gree_devices(self.hass)

        if not self._discovered_devices:
            # No devices found, go to manual entry
            return await self.async_step_manual()

        # Create device selection options
        device_options = {}
        for device in self._discovered_devices:
            device_id = f"{device['mac']}_{device['host']}"
            device_options[device_id] = f"IP: {device['host']}, MAC: {device['mac']}"

        data_schema = vol.Schema({vol.Required("device"): vol.In(device_options)})

        return self.async_show_form(step_id="discovery", data_schema=data_schema, description_placeholders={"devices_found": str(len(self._discovered_devices))})

    async def async_step_detect_encryption(self, user_input: dict | None = None) -> FlowResult:
        """Detect encryption version and configure device."""
        if user_input is not None:
            # User entered device name, proceed with setup
            device_name = user_input[CONF_NAME]

            # Create final configuration
            self._data = {
                CONF_NAME: device_name,
                CONF_HOST: self._selected_device["host"],
                CONF_MAC: self._selected_device["mac"],
                CONF_PORT: self._selected_device["port"],
                CONF_ENCRYPTION_KEY: "",
                CONF_ENCRYPTION_VERSION: self._selected_device["encryption_version"],
            }

            # Test the connection
            is_connection_valid = await test_connection(self._data)
            if not is_connection_valid:
                return self.async_show_form(
                    step_id="detect_encryption",
                    data_schema=vol.Schema(
                        {
                            vol.Required(CONF_NAME, default=device_name): str,
                        }
                    ),
                    errors={"base": "cannot_connect"},
                )

            return self.async_create_entry(title=device_name, data=self._data)

        # Detect encryption version for selected device
        mac_addr = self._selected_device["mac"]
        ip_addr = self._selected_device["host"]
        port = self._selected_device["port"]

        encryption_version = await detect_device_encryption(mac_addr, ip_addr, port)

        if encryption_version is None:
            # Could not detect encryption, pre-fill manual form with discovered device info
            self._data = {
                CONF_NAME: self._selected_device["name"],
                CONF_HOST: self._selected_device["host"],
                CONF_MAC: self._selected_device["mac"],
                CONF_PORT: self._selected_device["port"],
                CONF_ENCRYPTION_KEY: "",
                CONF_ENCRYPTION_VERSION: 1,  # Default to version 1
            }
            # Show manual form with error about encryption detection failure
            return self.async_show_form(
                step_id="manual",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_NAME, default=self._data.get(CONF_NAME, "")): str,
                        vol.Required(CONF_HOST, default=self._data.get(CONF_HOST, "")): str,
                        vol.Required(CONF_MAC, default=self._data.get(CONF_MAC, "")): str,
                        vol.Required(CONF_PORT, default=self._data.get(CONF_PORT, DEFAULT_PORT)): int,
                        vol.Optional(CONF_ENCRYPTION_KEY, default=self._data.get(CONF_ENCRYPTION_KEY, "")): str,
                        vol.Optional(CONF_UID): int,
                        vol.Optional(CONF_ENCRYPTION_VERSION, default=self._data.get(CONF_ENCRYPTION_VERSION, 1)): int,
                    }
                ),
                errors={"base": "cannot_connect"},
            )

        # Store detected encryption version
        self._selected_device["encryption_version"] = encryption_version

        # Show device naming form with detected info
        data_schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=self._selected_device["name"]): str,
            }
        )

        return self.async_show_form(step_id="detect_encryption", data_schema=data_schema)

    async def async_step_manual(self, user_input: dict | None = None) -> FlowResult:
        """Handle manual device entry."""
        errors = {}
        if user_input is not None:
            self._data.update(user_input)

            # Check if already configured by MAC
            await self.async_set_unique_id(self._data[CONF_MAC])
            self._abort_if_unique_id_configured()

            is_connection_valid = await test_connection(self._data)
            if not is_connection_valid:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title=user_input[CONF_NAME], data=self._data)

        # Set defaults from user_input if present, else use hardcoded defaults
        defaults = user_input or self._data
        data_schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, "")): str,
                vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
                vol.Required(CONF_MAC, default=defaults.get(CONF_MAC, "")): str,
                vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): int,
                vol.Optional(CONF_ENCRYPTION_KEY, default=defaults.get(CONF_ENCRYPTION_KEY, "")): str,
                vol.Optional(CONF_UID): int,
                vol.Optional(CONF_ENCRYPTION_VERSION, default=defaults.get(CONF_ENCRYPTION_VERSION, 1)): int,
            }
        )
        return self.async_show_form(step_id="manual", data_schema=data_schema, errors=errors)

    async def async_step_import(self, import_data: dict) -> FlowResult:
        """Handle configuration via YAML import."""
        return await self.async_step_user(import_data)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle an options flow for Gree climate."""

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
                    CONF_TEMP_SENSOR_OFFSET,
                    description={"suggested_value": options.get(CONF_TEMP_SENSOR_OFFSET)},
                ): vol.Any(None, bool),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
