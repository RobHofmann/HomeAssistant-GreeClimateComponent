"""Config flow to configure the Gree integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol
from voluptuous.schema_builder import UNDEFINED

from homeassistant import config_entries
from homeassistant.components.network import (
    IPv4Address,
    async_get_ipv4_broadcast_addresses,
)
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_NAME, CONF_PORT, CONF_TIMEOUT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import section
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
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
    CONF_RESTORE_STATES,
    CONF_SWING_HORIZONTAL_MODES,
    CONF_SWING_MODES,
    CONF_TEMPERATURE_STEP,
    CONF_UID,
    DEFAULT_FAN_MODES,
    DEFAULT_HVAC_MODES,
    DEFAULT_SUPPORTED_FEATURES,
    DEFAULT_SWING_HORIZONTAL_MODES,
    DEFAULT_SWING_MODES,
    DEFAULT_TARGET_TEMP_STEP,
    DOMAIN,
)
from .coordinator import GreeConfigEntry
from .gree_api import (
    DEFAULT_CONNECTION_MAX_ATTEMPTS,
    DEFAULT_CONNECTION_TIMEOUT,
    DEFAULT_DEVICE_PORT,
    DEFAULT_DEVICE_UID,
    EncryptionVersion,
    GreeDiscoveredDevice,
    discover_gree_devices,
)
from .gree_device import GreeDevice, GreeDeviceNotBoundError

_LOGGER = logging.getLogger(__name__)


def build_main_schema(data: Mapping | None) -> vol.Schema:
    """Builds the main option schema."""
    return vol.Schema(
        {
            vol.Required(
                CONF_NAME,
                default="Gree AC" if data is None else data.get(CONF_NAME, "Gree AC"),
            ): str,
            vol.Required(
                CONF_HOST,
                default="" if data is None else data.get(CONF_HOST, ""),
            ): str,
            vol.Required(
                CONF_MAC,
                default="" if data is None else data.get(CONF_MAC, ""),
            ): str,
            vol.Required(CONF_ADVANCED): section(
                vol.Schema(
                    {
                        vol.Required(
                            CONF_PORT,
                            default=DEFAULT_DEVICE_PORT
                            if data is None or data.get(CONF_ADVANCED) is None
                            else data[CONF_ADVANCED].get(
                                CONF_PORT, DEFAULT_DEVICE_PORT
                            ),
                        ): int,
                        vol.Required(
                            CONF_ENCRYPTION_VERSION,
                            default="Auto-Detect"
                            if data is None or data.get(CONF_ADVANCED) is None
                            else data[CONF_ADVANCED].get(
                                CONF_ENCRYPTION_VERSION, "Auto-Detect"
                            ),
                        ): vol.In(["Auto-Detect", "1", "2"]),
                        vol.Optional(
                            CONF_ENCRYPTION_KEY,
                            default=""
                            if data is None or data.get(CONF_ADVANCED) is None
                            else data[CONF_ADVANCED].get(CONF_ENCRYPTION_KEY, ""),
                        ): str,
                        vol.Required(
                            CONF_UID,
                            default=DEFAULT_DEVICE_UID
                            if data is None or data.get(CONF_ADVANCED) is None
                            else data[CONF_ADVANCED].get(CONF_UID, DEFAULT_DEVICE_UID),
                        ): cv.positive_int,
                        vol.Required(
                            CONF_DISABLE_AVAILABLE_CHECK,
                            default=False
                            if data is None
                            else data.get(CONF_DISABLE_AVAILABLE_CHECK, False),
                        ): cv.boolean,
                        vol.Required(
                            CONF_MAX_ONLINE_ATTEMPTS,
                            default=DEFAULT_CONNECTION_MAX_ATTEMPTS
                            if data is None
                            else data.get(
                                CONF_MAX_ONLINE_ATTEMPTS,
                                DEFAULT_CONNECTION_MAX_ATTEMPTS,
                            ),
                        ): cv.positive_int,
                        vol.Required(
                            CONF_TIMEOUT,
                            default=DEFAULT_CONNECTION_TIMEOUT
                            if data is None
                            else data.get(CONF_TIMEOUT, DEFAULT_CONNECTION_TIMEOUT),
                        ): cv.positive_int,
                    }
                ),
                {"collapsed": True},
            ),
        }
    )


def build_options_schema(hass: HomeAssistant, data: Mapping | None) -> vol.Schema:
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
            vol.Required(
                CONF_TEMPERATURE_STEP,
                default=DEFAULT_TARGET_TEMP_STEP
                if data is None
                else data.get(CONF_TEMPERATURE_STEP, DEFAULT_TARGET_TEMP_STEP),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0.5,
                    max=5,
                    step=0.5,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="ºC",
                )
            ),
            # Ideally we would use an Optional EntitySelector for external sensors.
            # Currently we can't because unsetting the value in the UI makes HA
            # populate the user_input with the previous set value, making the user
            # unable to unset the external sensors.
            vol.Required(
                ATTR_EXTERNAL_TEMPERATURE_SENSOR,
                default="None"
                if data is None
                else data.get(ATTR_EXTERNAL_TEMPERATURE_SENSOR, "None"),
            ): SelectSelector(
                config=SelectSelectorConfig(
                    options=get_temperature_sensor_options(hass),
                    multiple=False,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key=ATTR_EXTERNAL_TEMPERATURE_SENSOR,
                )
            ),
            vol.Required(
                ATTR_EXTERNAL_HUMIDITY_SENSOR,
                default=UNDEFINED
                if data is None
                else data.get(ATTR_EXTERNAL_HUMIDITY_SENSOR, UNDEFINED),
            ): SelectSelector(
                config=SelectSelectorConfig(
                    options=get_humidity_sensor_options(hass),
                    multiple=False,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key=ATTR_EXTERNAL_HUMIDITY_SENSOR,
                )
            ),
            vol.Required(
                CONF_RESTORE_STATES,
                default=True if data is None else data.get(CONF_RESTORE_STATES, True),
            ): cv.boolean,
        }
    )


def get_temperature_sensor_options(hass: HomeAssistant) -> list[str]:
    """Get list of available temperature sensor entities."""
    options: list[str] = [
        "None"
    ]  # Include None as option since otherwise the user can't unset the external sensor

    # Get all entities from the registry
    for state in hass.states.async_all():
        # Look for temperature sensors
        if state.entity_id.startswith("sensor."):
            # Check for explicit device_class
            if state.attributes.get("device_class") == "temperature":
                options.append(state.entity_id)

    return options


def get_humidity_sensor_options(hass: HomeAssistant) -> list[str]:
    """Get list of available temperature sensor entities."""
    options: list[str] = [
        "None"
    ]  # Include None as option since otherwise the user can't unset the external sensor

    # Get all entities from the registry
    for state in hass.states.async_all():
        # Look for temperature sensors
        if state.entity_id.startswith("sensor."):
            # Check for explicit device_class
            if state.attributes.get("device_class") == "humidity":
                options.append(state.entity_id)

    return options


DEVICE_OPTIONS_KEYS = {
    CONF_TIMEOUT,
    CONF_MAX_ONLINE_ATTEMPTS,
    CONF_DISABLE_AVAILABLE_CHECK,
    ATTR_EXTERNAL_HUMIDITY_SENSOR,
    ATTR_EXTERNAL_TEMPERATURE_SENSOR,
    CONF_FEATURES,
    CONF_SWING_HORIZONTAL_MODES,
    CONF_SWING_MODES,
    CONF_FAN_MODES,
    CONF_HVAC_MODES,
}  # keys in the device_options schema


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow from user."""

    VERSION = 2
    _discovered_devices: list[GreeDiscoveredDevice] | None = None
    _selected_device: GreeDiscoveredDevice | None = None
    _discovery_performed: bool = False

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._step_main_data: dict | None = None
        self._device: GreeDevice | None = None

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step - show discovery or manual entry."""
        if user_input is not None:
            if user_input.get("discovery") == "discover":
                return await self.async_step_manual_discovery()
            return await self.async_step_manual_add()

        # Show discovery vs manual choice
        data_schema = vol.Schema(
            {
                vol.Required("discovery", default="discover"): SelectSelector(
                    SelectSelectorConfig(
                        options=["discover", "manual"],
                        translation_key="discovery_method",
                    )
                )
            }
        )
        return self.async_show_form(step_id="user", data_schema=data_schema)

    async def async_step_manual_discovery(
        self, user_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle device discovery."""
        if user_input is not None:
            # User selected a discovered device
            selected_device = user_input["device"]

            assert self._discovered_devices

            for device in self._discovered_devices:
                device_id = f"{device.mac}_{device.host}"
                if device_id == selected_device:
                    # Check if already configured
                    await self.async_set_unique_id(format_mac(device.mac))
                    self._abort_if_unique_id_configured()

                    # Store selected device for next step
                    self._selected_device = device
                    return await self.async_step_manual_add()

            # If no matching device found, something went wrong - go to manual
            return await self.async_step_manual_add()

        # Discover devices
        self._discovery_performed = True
        self._discovered_devices = await self._discover_devices(self.hass)

        if not self._discovered_devices:
            # No devices found, go to manual entry
            return await self.async_step_manual_add()

        # Create device selection options
        device_options = {}
        for device in self._discovered_devices:
            device_id = f"{device.mac}_{device.host}"
            device_options[device_id] = f"IP: {device.host}, MAC: {device.mac}"

        data_schema = vol.Schema({vol.Required("device"): vol.In(device_options)})

        return self.async_show_form(
            step_id="manual_discovery",
            data_schema=data_schema,
            description_placeholders={
                "devices_found": str(len(self._discovered_devices))
            },
        )

    async def async_step_manual_add(
        self, user_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the manual add of a device."""
        errors = {}
        if user_input is not None:
            try:
                self._device = GreeDevice(
                    user_input[CONF_NAME],
                    user_input[CONF_HOST],
                    user_input[CONF_MAC],
                    user_input[CONF_ADVANCED][CONF_PORT],
                    user_input[CONF_ADVANCED][CONF_ENCRYPTION_KEY],
                    EncryptionVersion(
                        int(user_input[CONF_ADVANCED][CONF_ENCRYPTION_VERSION])
                    )
                    if user_input[CONF_ADVANCED][CONF_ENCRYPTION_VERSION]
                    != "Auto-Detect"
                    else None,
                    user_input[CONF_ADVANCED][CONF_UID],
                    max_connection_attempts=2,  # Use fewer attempts for testing the device
                    timeout=2,  # Use smaller timeout for testing the device
                )
                await self._device.bind_device()
            except CannotConnect:
                errors["base"] = "cannot_connect"
                _LOGGER.exception("Cannot connect")
            except GreeDeviceNotBoundError:
                errors["base"] = "cannot_connect"
                _LOGGER.exception("Error while binding")
            except Exception:
                errors["base"] = "unknown"
                _LOGGER.exception("Unknown error while binding")
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
        elif self._selected_device is not None:
            user_input = {}
            user_input[CONF_NAME] = self._selected_device.name
            user_input[CONF_HOST] = self._selected_device.host
            user_input[CONF_MAC] = self._selected_device.mac
            user_input[CONF_ADVANCED] = {}
            user_input[CONF_ADVANCED][CONF_PORT] = self._selected_device.port
            user_input[CONF_ADVANCED][CONF_UID] = self._selected_device.uid
        elif self._discovery_performed and self._selected_device is None:
            errors["base"] = "no_devices_found"

        return self.async_show_form(
            step_id="manual_add",
            data_schema=build_main_schema(user_input),
            errors=errors,
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
            _LOGGER.warning(user_input)
            data = self._merge_device_options(entry.data, user_input)
            self._abort_if_unique_id_mismatch()
            return self.async_update_reload_and_abort(
                entry,
                data=data,
            )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=build_options_schema(
                self.hass, entry.data if entry.data is not None else user_input
            ),
        )

    def _merge_device_options(self, data, device_options_data: Mapping) -> dict:
        """Removes optional keys if unset and updates the others."""
        old_data = dict(data)

        # Update or drop managed keys based on user_input

        for key in DEVICE_OPTIONS_KEYS:
            if key in device_options_data:
                old_data[key] = device_options_data[key]
            else:
                old_data.pop(key, None)
                _LOGGER.warning("Removing key %s", key)

        # If there are any unmanaged keys in user_input, merge them too
        old_data.update(
            {
                key: value
                for key, value in device_options_data.items()
                if key not in DEVICE_OPTIONS_KEYS
            }
        )

        return old_data

    async def _discover_devices(
        self, hass: HomeAssistant
    ) -> list[GreeDiscoveredDevice]:
        """Debug for discovering devices."""
        # Get broadcast addresses from Home Assistant's network helper
        broadcast_addresses: list[str] = []
        try:
            ha_broadcast_addresses: set[
                IPv4Address
            ] = await async_get_ipv4_broadcast_addresses(hass)
            ha_broadcast_strings: list[str] = [
                str(addr) for addr in ha_broadcast_addresses
            ]
            broadcast_addresses.extend(ha_broadcast_strings)
            _LOGGER.debug("Found broadcast addresses from HA: %s", ha_broadcast_strings)

        except Exception:
            _LOGGER.exception("Could not get HA broadcast addresses")

        return await discover_gree_devices(broadcast_addresses, 5)


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""
