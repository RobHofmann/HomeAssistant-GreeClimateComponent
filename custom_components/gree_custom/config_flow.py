"""Config flow to configure the Gree integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.network import (
    IPv4Address,
    async_get_ipv4_broadcast_addresses,
)
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_PORT, CONF_TIMEOUT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import section
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    ATTR_EXTERNAL_HUMIDITY_SENSOR,
    ATTR_EXTERNAL_TEMPERATURE_SENSOR,
    CONF_ADVANCED,
    CONF_DEV_NAME,
    CONF_DEVICES,
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
    DEFAULT_SWING_HORIZONTAL_MODES,
    DEFAULT_SWING_MODES,
    DEFAULT_TARGET_TEMP_STEP,
    DOMAIN,
    GATTR_ANTI_DIRECT_BLOW,
    GATTR_BEEPER,
    GATTR_FEAT_ENERGY_SAVING,
    GATTR_FEAT_FRESH_AIR,
    GATTR_FEAT_HEALTH,
    GATTR_FEAT_LIGHT,
    GATTR_FEAT_QUIET_MODE,
    GATTR_FEAT_SENSOR_LIGHT,
    GATTR_FEAT_SLEEP_MODE,
    GATTR_FEAT_SMART_HEAT_8C,
    GATTR_FEAT_TURBO,
    GATTR_FEAT_XFAN,
)
from .coordinator import GreeConfigEntry
from .gree_api import (
    DEFAULT_CONNECTION_MAX_ATTEMPTS,
    DEFAULT_CONNECTION_TIMEOUT,
    DEFAULT_DEVICE_PORT,
    DEFAULT_DEVICE_UID,
    EncryptionVersion,
    GreeDiscoveredDevice,
    GreeProp,
    discover_gree_devices,
)
from .gree_device import (
    CannotConnect,
    GreeDevice,
    GreeDeviceNotBoundError,
    GreeDeviceNotBoundErrorKey,
)

_LOGGER = logging.getLogger(__name__)


def build_main_schema(data: Mapping | None) -> vol.Schema:
    """Builds the main option schema."""
    if data:
        _LOGGER.debug("Building main schema with previous values: %s", data)

    return vol.Schema(
        {
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
                        ): vol.In(["Auto-Detect", 1, 2]),
                        vol.Optional(
                            CONF_ENCRYPTION_KEY,
                            default=""
                            if data is None or data.get(CONF_ADVANCED) is None
                            else data[CONF_ADVANCED].get(CONF_ENCRYPTION_KEY, ""),
                        ): TextSelector(
                            TextSelectorConfig(type=TextSelectorType.PASSWORD)
                        ),
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


def build_options_schema(
    hass: HomeAssistant, device: GreeDevice, data: Mapping | None
) -> vol.Schema:
    """Builds the device option schema."""
    if data:
        _LOGGER.debug("Building device options schema with previous values: %s", data)

    schema: dict = {}
    schema.update(
        {
            vol.Required(
                CONF_DEV_NAME,
                default=f"Gree AC {device.unique_id}"
                if data is None
                else data.get(CONF_DEV_NAME, f"Gree AC {device.unique_id}"),
            ): str
        }
    )

    if device.supports_property(GreeProp.OP_MODE):
        schema.update(
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
            }
        )

    valid_fan_modes = []
    if device.supports_property(GreeProp.FAN_SPEED):
        valid_fan_modes = DEFAULT_FAN_MODES
    if device.supports_property(GreeProp.FEAT_TURBO_MODE):
        valid_fan_modes.append(GATTR_FEAT_TURBO)
    if device.supports_property(GreeProp.FEAT_QUIET_MODE):
        valid_fan_modes.append(GATTR_FEAT_QUIET_MODE)

    if valid_fan_modes:
        schema.update(
            {
                vol.Optional(
                    CONF_FAN_MODES,
                    default=valid_fan_modes
                    if data is None
                    else data.get(CONF_FAN_MODES, valid_fan_modes),
                ): SelectSelector(
                    config=SelectSelectorConfig(
                        options=valid_fan_modes,
                        multiple=True,
                        translation_key=CONF_FAN_MODES,
                    )
                ),
            }
        )

    if device.supports_property(GreeProp.SWING_VERTICAL):
        schema.update(
            {
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
            }
        )

    if device.supports_property(GreeProp.SWING_HORIZONTAL):
        schema.update(
            {
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
            }
        )

    valid_features = [GATTR_BEEPER]
    if device.supports_property(GreeProp.FEAT_FRESH_AIR):
        valid_features.append(GATTR_FEAT_FRESH_AIR)
    if device.supports_property(GreeProp.FEAT_XFAN):
        valid_features.append(GATTR_FEAT_XFAN)
    if device.supports_property(GreeProp.FEAT_SLEEP_MODE) or device.supports_property(
        GreeProp.FEAT_SLEEP_MODE_SWING
    ):
        valid_features.append(GATTR_FEAT_SLEEP_MODE)
    if device.supports_property(GreeProp.FEAT_SMART_HEAT_8C):
        valid_features.append(GATTR_FEAT_SMART_HEAT_8C)
    if device.supports_property(GreeProp.FEAT_LIGHT):
        valid_features.append(GATTR_FEAT_LIGHT)
    if device.supports_property(GreeProp.FEAT_LIGHT) and device.supports_property(
        GreeProp.FEAT_SENSOR_LIGHT
    ):
        valid_features.append(GATTR_FEAT_SENSOR_LIGHT)
    if device.supports_property(GreeProp.FEAT_HEALTH):
        valid_features.append(GATTR_FEAT_HEALTH)
    if device.supports_property(GreeProp.FEAT_ANTI_DIRECT_BLOW):
        valid_features.append(GATTR_ANTI_DIRECT_BLOW)
    if device.supports_property(GreeProp.FEAT_ENERGY_SAVING):
        valid_features.append(GATTR_FEAT_ENERGY_SAVING)

    schema.update(
        {
            vol.Optional(
                CONF_FEATURES,
                default=valid_features
                if data is None
                else data.get(CONF_FEATURES, valid_features),
            ): SelectSelector(
                config=SelectSelectorConfig(
                    options=valid_features,
                    multiple=True,
                    translation_key=CONF_FEATURES,
                )
            )
        }
    )

    if device.supports_property(GreeProp.TARGET_TEMPERATURE):
        schema.update(
            {
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
                )
            }
        )

    schema.update(
        {
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
                default="None"
                if data is None
                else data.get(ATTR_EXTERNAL_HUMIDITY_SENSOR, "None"),
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
    return vol.Schema(schema)


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


def apply_schema_defaults(schema: vol.Schema, data: dict) -> dict:
    """Fill in defaults for missing required keys (including nested)."""
    data = dict(data or {})
    result = {}

    for key_obj, validator in schema.schema.items():
        key = key_obj.schema  # actual string name
        value = data.get(key, vol.UNDEFINED)

        # Extract default if missing
        if value is vol.UNDEFINED:
            default = getattr(key_obj, "default", vol.UNDEFINED)
            if default is not vol.UNDEFINED:
                value = default() if callable(default) else default

        # Handle nested schema recursively
        if isinstance(validator, vol.Schema) and isinstance(value, dict):
            value = apply_schema_defaults(validator, value)

        # Run individual field validator (type checks etc.)
        if value is not vol.UNDEFINED:
            value = validator(value) if callable(validator) else value

        result[key] = value

    return result


def format_mac_id(mac_addr: str) -> str:
    """Returns a formated mac address for use as unique id."""
    if "@" in mac_addr:
        _mac_addr_sub, _ = mac_addr.lower().split("@", 1)
        return format_mac(_mac_addr_sub)
    return format_mac(mac_addr)


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
    _discovery_selected_device: GreeDiscoveredDevice | None = None
    _discovery_performed: bool = False

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._step_main_data: dict | None = None
        self._main_mac: str = ""
        self._discovered_subdevices: list[GreeDiscoveredDevice] | None = None
        self._device_configs: dict = {}
        self._selected_subdevices_macs: list = []
        self._reconfiguring_entry: GreeConfigEntry | None = None
        self._devices: dict[str, GreeDevice] = {}
        self._is_reconfigure: bool = False

    async def async_step_import(
        self, import_config: dict
    ) -> config_entries.ConfigFlowResult:
        """Handle import from configuration.yaml."""
        _LOGGER.debug("Importing config entry: %s", import_config)

        mac = import_config.get(CONF_MAC, "")

        if not mac:
            _LOGGER.error("No MAC for imported device: %s", import_config)
            raise ValueError(f"No MAC for imported device: {import_config}")

        # Combine the schemas
        schema1 = build_main_schema(import_config)
        data = apply_schema_defaults(schema1, import_config)

        device: GreeDevice = GreeDevice(
            f"Temporary Device for {data[CONF_MAC]}",
            data[CONF_HOST],
            data[CONF_MAC],
            data[CONF_ADVANCED][CONF_PORT],
            data[CONF_ADVANCED][CONF_ENCRYPTION_KEY],
            EncryptionVersion(int(data[CONF_ADVANCED][CONF_ENCRYPTION_VERSION]))
            if data[CONF_ADVANCED][CONF_ENCRYPTION_VERSION] != "Auto-Detect"
            else None,
            data[CONF_ADVANCED][CONF_UID],
            max_connection_attempts=2,  # Use fewer attempts for testing the device
            timeout=2,  # Use smaller timeout for testing the device
        )
        await device.fetch_device_status()

        data[CONF_MAC] = device.mac_address
        data[CONF_ADVANCED][CONF_ENCRYPTION_VERSION] = (
            int(device.encryption_version) if device.encryption_version else 0
        )
        data[CONF_ADVANCED][CONF_ENCRYPTION_KEY] = device.encryption_key

        device_configs: list[dict] = import_config.get(CONF_DEVICES, [])

        # add the main device to the configs if not present
        if not self._get_device_conf(
            import_config, device.mac_address_sub
        ) and not self._get_device_conf(import_config, import_config[CONF_MAC]):
            device_configs.append({CONF_MAC: device.mac_address_sub})

        data[CONF_DEVICES] = []
        for dev_config in device_configs:
            mac = dev_config.get(CONF_MAC, "")

            if not mac:
                _LOGGER.error("No MAC for imported device: %s", dev_config)
                continue

            dev: GreeDevice = GreeDevice(
                f"Temporary Device for {mac}",
                data[CONF_HOST],
                mac,
                data[CONF_ADVANCED][CONF_PORT],
                data[CONF_ADVANCED][CONF_ENCRYPTION_KEY],
                EncryptionVersion(int(data[CONF_ADVANCED][CONF_ENCRYPTION_VERSION])),
                data[CONF_ADVANCED][CONF_UID],
                max_connection_attempts=2,  # Use fewer attempts for testing the device
                timeout=2,  # Use smaller timeout for testing the device
            )

            await dev.fetch_device_status()
            schema_dev = build_options_schema(self.hass, dev, dev_config)
            data[CONF_DEVICES].append(
                {
                    **apply_schema_defaults(schema_dev, import_config),
                    CONF_MAC: dev.mac_address_sub,
                }
            )

        unique_id = format_mac_id(device.mac_address)
        entry = next(
            (
                e
                for e in self.hass.config_entries.async_entries(DOMAIN)
                if e.unique_id == unique_id
            ),
            None,
        )

        await self.async_set_unique_id(unique_id)

        if entry:
            return self.async_update_reload_and_abort(
                entry,
                title=f"Gree System at {data[CONF_HOST]}",
                data=data,
            )

        return self.async_create_entry(
            title=f"Gree System at {data[CONF_HOST]}", data=data
        )

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
                device_id = device.mac
                if device_id == selected_device:
                    # Check if already configured
                    await self.async_set_unique_id(format_mac_id(device.mac))
                    self._abort_if_unique_id_configured()

                    # Store selected device for next step
                    self._discovery_selected_device = device
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
            device_id = device.mac
            if device.subdevices > 0:
                device_options[device_id] = (
                    f"IP: {device.host}, MAC: {device.mac}, Subdevices: {device.subdevices}"
                )
            else:
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
        self, user_input: dict | None = None, reconfigure_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the manual add of a device."""
        errors = {}

        if user_input is not None:
            try:
                _main_device = GreeDevice(
                    f"Gree Device {user_input[CONF_MAC]}",
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
                self._main_mac = _main_device.mac_address
                await self.async_set_unique_id(format_mac_id(self._main_mac))

                if self._is_reconfigure:
                    self._abort_if_unique_id_mismatch()
                else:
                    self._abort_if_unique_id_configured()

                self._devices[_main_device.mac_address_sub] = _main_device

                # self._discovered_subdevices = await get_sub_devices(
                #     _main_device.mac_address, user_input[CONF_HOST], 0, 2, 2
                # )
                self._discovered_subdevices = await self._devices[
                    _main_device.mac_address_sub
                ].fetch_sub_devices()

                # for d in self._discovered_subdevices:
                #     self._devices[d.mac] = GreeDevice(
                #         d.name,
                #         user_input[CONF_HOST],
                #         f"{d.mac}@{_main_device.mac_address}",
                #         user_input[CONF_ADVANCED][CONF_PORT],
                #         _main_device.encryption_key,
                #         _main_device.encryption_version,
                #         user_input[CONF_ADVANCED][CONF_UID],
                #         max_connection_attempts=2,  # Use fewer attempts for testing the device
                #         timeout=2,  # Use smaller timeout for testing the device
                #     )

                await self._devices[_main_device.mac_address_sub].fetch_device_status()
            except CannotConnect:
                errors["base"] = "cannot_connect"
                _LOGGER.exception("Cannot connect")
            except GreeDeviceNotBoundError:
                errors["base"] = "cannot_connect"
                _LOGGER.exception("Error while binding")
            except GreeDeviceNotBoundErrorKey:
                errors["base"] = "cannot_connect_key"
                _LOGGER.exception("Error while binding with wrong key")
            except Exception:
                errors["base"] = "unknown"
                _LOGGER.exception("Unknown error while binding")
            else:
                if self._step_main_data:
                    self._step_main_data.update(user_input)
                else:
                    self._step_main_data = user_input
                self._step_main_data[CONF_MAC] = _main_device.mac_address
                self._step_main_data[CONF_ADVANCED].update(
                    {
                        CONF_ENCRYPTION_VERSION: _main_device.encryption_version,
                        CONF_ENCRYPTION_KEY: _main_device.encryption_key,
                    }
                )

                return await self.async_step_device_options()

        elif self._discovery_selected_device is not None:
            user_input = {}
            # user_input[CONF_NAME] = self._selected_device.name
            user_input[CONF_HOST] = self._discovery_selected_device.host
            user_input[CONF_MAC] = self._discovery_selected_device.mac
            user_input[CONF_ADVANCED] = {}
            user_input[CONF_ADVANCED][CONF_PORT] = self._discovery_selected_device.port
            user_input[CONF_ADVANCED][CONF_UID] = self._discovery_selected_device.uid
        elif self._discovery_performed and self._discovery_selected_device is None:
            errors["base"] = "no_devices_found"
        elif reconfigure_input is not None:
            user_input = reconfigure_input
            self._step_main_data = reconfigure_input

        return self.async_show_form(
            step_id="manual_add",
            data_schema=build_main_schema(user_input),
            errors=errors,
        )

    async def async_step_device_options(
        self,
        user_input: dict | None = None,
        index: int | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Second step: configure features/modes."""
        if (
            user_input is not None
            and self._step_main_data is not None
            and self._devices[self._main_mac] is not None
        ):
            await self.async_set_unique_id(format_mac_id(self._main_mac))
            if self._is_reconfigure:
                self._abort_if_unique_id_mismatch()
            else:
                self._abort_if_unique_id_configured()

            # Configuring the main device
            # If it has no subdevices, finalyze entry
            # Otherwise repeat form while iterating the subdevices
            if index is None:
                self._device_configs[self._main_mac] = {
                    # Ignore the subdevice selection item
                    k: v
                    for k, v in user_input.items()
                    if k != CONF_DEVICES
                }

                self._selected_subdevices_macs = user_input.get(CONF_DEVICES, [])
                # Remove the device configs for the ones not selected so they are removed from the entry
                self._device_configs = {
                    k: v
                    for k, v in self._device_configs.items()
                    if k in self._selected_subdevices_macs or k == self._main_mac
                }

                if self._selected_subdevices_macs:
                    return await self.async_step_device_options(None, 0)

                if self._is_reconfigure:
                    return self._update_entry()
                return self._create_final_entry()

            # If configuring a subdevice iterate the chosen subdevices
            # If the last subdevice, finalyze the entry
            self._device_configs[self._selected_subdevices_macs[index]] = user_input
            if index + 1 < len(self._selected_subdevices_macs):
                return await self.async_step_device_options(None, index + 1)

            if self._is_reconfigure:
                return self._update_entry()
            return self._create_final_entry()

        if self._step_main_data is None:
            raise ValueError("No data from main options")

        if self._devices[self._main_mac] is None:
            raise ValueError("No device created in main options step")

        device: GreeDevice = self._devices[self._main_mac]

        if index is not None and self._discovered_subdevices:
            device = self._devices[self._selected_subdevices_macs[index]]

        await device.fetch_device_status()

        conf_input = user_input
        if self._is_reconfigure:
            conf_input = self._get_device_conf(
                self._step_main_data, device.mac_address_sub
            )

        schema = build_options_schema(self.hass, device, conf_input)

        # If we are configuring the main device,
        # add list of subdevices to include if any
        if index is None and self._discovered_subdevices:
            subdev_options = {d.mac: d.name for d in self._discovered_subdevices}
            selected_options = subdev_options.keys()

            # If reconfiguring, only preselect the devices already configured
            if self._is_reconfigure:
                configured_device_macs = [
                    device["mac"] for device in self._step_main_data["devices"]
                ]
                selected_options = [
                    mac for mac in subdev_options if mac in configured_device_macs
                ]
            schema.extend(
                {
                    vol.Required(
                        CONF_DEVICES, default=selected_options
                    ): cv.multi_select(subdev_options)
                }
            )

        return self.async_show_form(
            step_id="device_options",
            data_schema=schema,
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None):
        """Handle reconfiguration of an existing entry."""
        entry: GreeConfigEntry = self._get_reconfigure_entry()

        _LOGGER.debug("Reconfiguring: %s", entry)
        await self.async_set_unique_id(entry.unique_id)
        self._reconfiguring_entry = entry
        self._is_reconfigure = True

        return await self.async_step_manual_add(
            None, dict(entry.data) if entry.data is not None else None
        )

        # return self.async_show_form(
        #     step_id="reconfigure",
        #     data_schema=build_main_schema(
        #         entry.data if entry.data is not None else user_input
        #     ),
        #     errors=errors,
        # )

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

    def _create_final_entry(self):
        """Build final entry data."""
        data: dict = {}

        if self._step_main_data:
            data = self._step_main_data.copy()

        # build devices list: main + subdevices
        devices = []
        for mac, conf in self._device_configs.items():
            devices.append({**conf, CONF_MAC: mac})

        data[CONF_DEVICES] = devices

        _LOGGER.debug("New entry with config: %s", data)
        return self.async_create_entry(
            title=f"Gree System at {data[CONF_HOST]}", data=data
        )

    def _update_entry(self):
        """Build final entry data."""
        data: dict = {}

        if self._reconfiguring_entry is None:
            raise ValueError("Error updating entry which is not set")

        if self._step_main_data:
            data = self._step_main_data.copy()

        # build devices list: main + subdevices
        devices = []
        for mac, conf in self._device_configs.items():
            devices.append({**conf, CONF_MAC: mac})

        data[CONF_DEVICES] = devices

        _LOGGER.debug("Updating entry with config: %s", data)

        return self.async_update_reload_and_abort(
            self._reconfiguring_entry,
            title=f"Gree System at {data[CONF_HOST]}",
            data=data,
        )

    def _get_device_conf(self, config: dict, mac: str) -> dict | None:
        configured_devices = config.get(CONF_DEVICES, [])
        return next((d for d in configured_devices if d.get(CONF_MAC) == mac), None)
