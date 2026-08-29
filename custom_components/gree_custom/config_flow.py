"""Config flow to configure the Gree integration."""

from collections.abc import Mapping
from ipaddress import IPv4Address, IPv4Network, ip_address, ip_network
import logging
from typing import Any, override

from aiomqtt import MqttError
import voluptuous as vol

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import (
    CONF_BASE,
    CONF_DISCOVERY,
    CONF_EMAIL,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_REGION,
    CONF_SCAN_INTERVAL,
    CONF_TIMEOUT,
    CONF_TOKEN,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import section
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.helpers.storage import Store

from .aiogree.api import (
    GreeDiscoveredDevice,
    GreeProp,
    gree_discover_devices_cloud,
    gree_discover_devices_local,
    gree_merge_discovered_devices,
)
from .aiogree.cipher import EncryptionVersion
from .aiogree.cloud_api import GreeCloudApi, GreeRegion
from .aiogree.device import GreeDevice
from .aiogree.errors import (
    GreeBindingError,
    GreeCloudError,
    GreeCloudLoginError,
    GreeConnectionError,
)
from .aiogree.transport_mqtt import GreeMqttTransport
from .aiogree.transport_udp import GreeUdpTransport
from .const import (
    ATTR_EXTERNAL_HUMIDITY_SENSOR,
    ATTR_EXTERNAL_TEMPERATURE_SENSOR,
    ATTR_FEATURES_TO_PROP_MAP,
    CONF_ALL_DEVICE_CONNECTIONS,
    CONF_ALL_DEVICE_OPTIONS,
    CONF_CLOUD,
    CONF_DEV_NAME,
    CONF_DEVICE_CONNECTION,
    CONF_DEVICE_CONNECTION_CLOUD,
    CONF_DEVICE_CONNECTION_LOCAL,
    CONF_DEVICE_OPTIONS,
    CONF_DEVICES,
    CONF_DISABLE_AVAILABLE_CHECK,
    CONF_DISCOVERY_PREFS_KEY,
    CONF_DISCOVERY_PREFS_VERSION,
    CONF_ENCRYPTION_KEY,
    CONF_ENCRYPTION_VERSION,
    CONF_EXTRA_SCAN_HOSTS,
    CONF_EXTRA_SCAN_NETWORKS,
    CONF_FAN_MODES,
    CONF_FEATURES,
    CONF_HVAC_MODES,
    CONF_MAC_CONTROLLER_CLOUD,
    CONF_MAC_CONTROLLER_LOCAL,
    CONF_MAX_ONLINE_ATTEMPTS,
    CONF_PREFER_CLOUD,
    CONF_RESTORE_STATES,
    CONF_SWING_HORIZONTAL_MODES,
    CONF_SWING_MODES,
    CONF_TEMPERATURE_STEP,
    CONF_UID,
    CONFENTRY_ID_LOCAL_ONLY,
    DEFAULT_CONNECTION_MAX_ATTEMPTS,
    DEFAULT_CONNECTION_TIMEOUT,
    DEFAULT_DEVICE_UID,
    DEFAULT_DISABLE_AVAILABLE_CHECK,
    DEFAULT_DISCOVERY_TIMEOUT,
    DEFAULT_ENCRYPTION_KEY,
    DEFAULT_ENCRYPTION_VERSION,
    DEFAULT_EXTERNAL_SENSOR,
    DEFAULT_FAN_MODES,
    DEFAULT_HVAC_MODES,
    DEFAULT_PREFER_CLOUD,
    DEFAULT_RESTORE_STATES,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SWING_HORIZONTAL_MODES,
    DEFAULT_SWING_MODES,
    DEFAULT_TARGET_TEMP_STEP,
    DOMAIN,
    ENCRYPTION_VERSION_AUTO,
    GATTR_FEAT_QUIET_MODE,
    GATTR_FEAT_TURBO,
    MAX_UNICAST_SCAN_HOSTS,
    MIN_SCAN_INTERVAL,
)
from .coordinator import GreeConfigEntry
from .helpers import get_discovery_addresses

_LOGGER = logging.getLogger(__name__)


def get_temperature_sensor_options(hass: HomeAssistant) -> list[str]:
    """Get list of available temperature sensor entities."""
    options: list[str] = [
        DEFAULT_EXTERNAL_SENSOR
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


SETUP_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DISCOVERY, default=["cloud", "local"]): SelectSelector(
            SelectSelectorConfig(
                options=["cloud", "local"],
                multiple=True,
                translation_key=CONF_DISCOVERY,
            )
        )
    }
)


def _setup_cloud_schema(defaults_values: dict | None = None) -> vol.Schema:
    defaults = defaults_values or {}

    return vol.Schema(
        {
            vol.Required(
                CONF_EMAIL,
                default=defaults.get(CONF_EMAIL, ""),
            ): str,
            vol.Required(
                CONF_PASSWORD,
                default=defaults.get(CONF_PASSWORD, ""),
            ): str,
            vol.Required(
                CONF_REGION,
                default=defaults.get(CONF_REGION),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=[region.value for region in GreeRegion],
                    multiple=False,
                )
            ),
        }
    )


def _setup_local_schema(default_values: dict | None = None) -> vol.Schema:
    defaults = default_values or {}

    return vol.Schema(
        {
            vol.Optional(
                CONF_EXTRA_SCAN_NETWORKS,
                default=defaults.get(CONF_EXTRA_SCAN_NETWORKS, []),
            ): TextSelector(TextSelectorConfig(multiple=True, multiline=False)),
            vol.Optional(
                CONF_EXTRA_SCAN_HOSTS,
                default=defaults.get(CONF_EXTRA_SCAN_HOSTS, []),
            ): TextSelector(TextSelectorConfig(multiple=True, multiline=False)),
        }
    )


def _setup_device_connection_options_schema(
    device_info: GreeDiscoveredDevice, default_values: dict | None = None
) -> vol.Schema:
    defaults: dict = default_values or {}
    defaults_local = defaults.get(CONF_DEVICE_CONNECTION_LOCAL, {})
    defaults_cloud = defaults.get(CONF_DEVICE_CONNECTION_CLOUD, {})

    return vol.Schema(
        {
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL)),
            vol.Required(
                CONF_DISABLE_AVAILABLE_CHECK,
                default=defaults.get(
                    CONF_DISABLE_AVAILABLE_CHECK,
                    DEFAULT_DISABLE_AVAILABLE_CHECK,
                ),
            ): cv.boolean,
            vol.Optional(
                CONF_ENCRYPTION_KEY,
                default=(
                    defaults.get(CONF_ENCRYPTION_KEY)
                    or device_info.key
                    or DEFAULT_ENCRYPTION_KEY
                ),
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
            vol.Required(
                CONF_UID,
                default=defaults.get(CONF_UID, device_info.user_id),
            ): cv.positive_int,
            vol.Required(CONF_DEVICE_CONNECTION_LOCAL): section(
                vol.Schema(
                    {
                        vol.Optional(
                            CONF_MAC_CONTROLLER_LOCAL,
                            default=(
                                defaults_local.get(CONF_MAC_CONTROLLER_LOCAL)
                                or device_info.mac_controller_local
                            ),
                        ): str,
                        vol.Optional(
                            CONF_HOST,
                            default=(
                                defaults_local.get(CONF_HOST) or device_info.host or ""
                            ),
                        ): str,
                        vol.Optional(
                            CONF_PORT,
                            default=(
                                defaults_local.get(CONF_PORT) or device_info.port or ""
                            ),
                        ): vol.Any(cv.port, ""),
                        vol.Required(
                            CONF_TIMEOUT,
                            default=defaults_local.get(
                                CONF_TIMEOUT, DEFAULT_CONNECTION_TIMEOUT
                            ),
                        ): cv.positive_int,
                        vol.Required(
                            CONF_ENCRYPTION_VERSION,
                            default=defaults_local.get(
                                CONF_ENCRYPTION_VERSION, DEFAULT_ENCRYPTION_VERSION
                            ),
                        ): SelectSelector(
                            SelectSelectorConfig(
                                options=[
                                    SelectOptionDict(
                                        value=ENCRYPTION_VERSION_AUTO,
                                        label="Auto-Detect",
                                    ),
                                    *[
                                        SelectOptionDict(
                                            value=str(version.value), label=version.name
                                        )
                                        for version in EncryptionVersion
                                    ],
                                ],
                                mode=SelectSelectorMode.DROPDOWN,
                            )
                        ),
                        vol.Required(
                            CONF_MAX_ONLINE_ATTEMPTS,
                            default=defaults_local.get(
                                CONF_MAX_ONLINE_ATTEMPTS,
                                DEFAULT_CONNECTION_MAX_ATTEMPTS,
                            ),
                        ): cv.positive_int,
                    }
                )
            ),
            vol.Required(CONF_DEVICE_CONNECTION_CLOUD): section(
                vol.Schema(
                    {
                        vol.Required(
                            CONF_PREFER_CLOUD,
                            default=defaults_cloud.get(
                                CONF_PREFER_CLOUD,
                                DEFAULT_PREFER_CLOUD,
                            ),
                        ): cv.boolean,
                        vol.Optional(
                            CONF_MAC_CONTROLLER_CLOUD,
                            default=defaults_cloud.get(
                                CONF_MAC_CONTROLLER_CLOUD,
                                device_info.mac_controller_mqtt,
                            ),
                        ): str,
                    }
                )
            ),
        }
    )


def _setup_device_options_schema(
    hass: HomeAssistant, device: GreeDevice, default_values: Mapping | None
) -> vol.Schema:
    defaults = default_values or {}

    schema: dict = {}
    schema.update(
        {
            vol.Required(
                CONF_DEV_NAME,
                default=defaults.get(CONF_DEV_NAME, device.name),
            ): str
        }
    )

    if device.supports_property(GreeProp.OP_MODE):
        schema.update(
            {
                vol.Optional(
                    CONF_HVAC_MODES,
                    default=defaults.get(CONF_HVAC_MODES, DEFAULT_HVAC_MODES),
                ): SelectSelector(
                    config=SelectSelectorConfig(
                        options=DEFAULT_HVAC_MODES,
                        multiple=True,
                        translation_key=CONF_HVAC_MODES,
                    )
                ),
            }
        )

    fan_mapping = {
        GreeProp.FAN_SPEED: DEFAULT_FAN_MODES,
        GreeProp.FEAT_TURBO_MODE: [GATTR_FEAT_TURBO],
        GreeProp.FEAT_QUIET_MODE: [GATTR_FEAT_QUIET_MODE],
    }
    valid_fan_modes = []
    for prop, modes in fan_mapping.items():
        if device.supports_property(prop):
            valid_fan_modes.extend(modes)

    if valid_fan_modes:
        schema.update(
            {
                vol.Optional(
                    CONF_FAN_MODES,
                    default=defaults.get(CONF_FAN_MODES, valid_fan_modes),
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
                    default=defaults.get(CONF_SWING_MODES, DEFAULT_SWING_MODES),
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
                    default=defaults.get(
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

    valid_features = []
    for feat, props in ATTR_FEATURES_TO_PROP_MAP.items():
        if all(device.supports_property(p) for p in props):
            valid_features.append(feat)

    if valid_features:
        schema.update(
            {
                vol.Optional(
                    CONF_FEATURES,
                    default=defaults.get(CONF_FEATURES, valid_features),
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
                    default=defaults.get(
                        CONF_TEMPERATURE_STEP, DEFAULT_TARGET_TEMP_STEP
                    ),
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
                default=defaults.get(
                    ATTR_EXTERNAL_TEMPERATURE_SENSOR, DEFAULT_EXTERNAL_SENSOR
                ),
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
                default=defaults.get(
                    ATTR_EXTERNAL_HUMIDITY_SENSOR, DEFAULT_EXTERNAL_SENSOR
                ),
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
                default=defaults.get(CONF_RESTORE_STATES, DEFAULT_RESTORE_STATES),
            ): cv.boolean,
        }
    )

    return vol.Schema(schema)


class SetupConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow for the integration."""

    VERSION = 3

    def __init__(self) -> None:
        """Initialize the flow."""
        self._selected_setup_methods: list[str] = []
        self._current_setup_method_index = 0
        self._pref_storage: Store | None = None

        self._extra_networks: list[str] = []
        self._extra_hosts: list[str] = []

        self._config_data: dict = {}
        self._config_data["device_connections"] = {}
        self._config_data["device_options"] = {}

        self._reconfigure_entry: GreeConfigEntry | None = None
        self._reconfigure_data: dict[str, Any] | None = None

        self._reauth_entry: GreeConfigEntry | None = None
        self._reauth_data: dict[str, Any] | None = None

        self._cloud_api: GreeCloudApi

        self._discovered_devices_cloud: dict[str, GreeDiscoveredDevice] = {}
        self._discovered_devices_local: dict[str, GreeDiscoveredDevice] = {}
        self._discovered_devices: dict[str, GreeDiscoveredDevice] = {}

        self._selected_devices: list[GreeDiscoveredDevice] = []
        self._current_setup_device_index = 0

        self._mqtt_transport: GreeMqttTransport | None = None
        self._local_transports: dict[str, GreeUdpTransport] = {}
        self._devices: dict[str, GreeDevice] = {}

        self._connections_by_controller: dict[str, Any] = {}
        self._options_by_controller: dict[str, Any] = {}

    @override
    async def async_step_user(self, user_input: dict | None = None) -> ConfigFlowResult:
        """Handle the initial step - show discovery or manual entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._selected_setup_methods = user_input[CONF_DISCOVERY]

            if not self._selected_setup_methods:
                errors[CONF_DISCOVERY] = "no_methods_selected"

            if not errors:
                if self._selected_setup_methods == ["local"]:
                    await self.async_set_unique_id(CONFENTRY_ID_LOCAL_ONLY)
                    self._abort_if_unique_id_configured()

                self._current_setup_method_index = 0
                return await self._setup_next_setup_method()

        return self.async_show_form(
            step_id="user", data_schema=SETUP_SCHEMA, errors=errors
        )

    async def _setup_next_setup_method(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Invoke the next selected setup method."""

        if self._current_setup_method_index >= len(self._selected_setup_methods):
            filtered_local = list(self._discovered_devices_local.values())
            # Only use local devices that are in the cloud list
            # local-only devices should be added in a different config entry
            if self._discovered_devices_cloud:
                filtered_local = [
                    dev
                    for dev in self._discovered_devices_local.values()
                    if dev.mac in self._discovered_devices_cloud
                ]

            discovered = gree_merge_discovered_devices(
                local_devices=filtered_local,
                cloud_devices=list(self._discovered_devices_cloud.values()),
            )
            self._discovered_devices = {d.mac: d for d in discovered}

            return await self.async_step_device_picker()

        method = self._selected_setup_methods[self._current_setup_method_index]
        self._current_setup_method_index += 1

        match method:
            case "cloud":
                return await self.async_step_cloud_add()
            case "local":
                return await self.async_step_local_add()
            case _:
                return await self._setup_next_setup_method()

    async def async_step_cloud_add(  # noqa: C901
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Gather cloud info for later discovery."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._cloud_api = GreeCloudApi(
                region=GreeRegion(user_input.get(CONF_REGION, "")),
                username=user_input.get(CONF_EMAIL, ""),
                password=user_input.get(CONF_PASSWORD, ""),
            )
            try:
                await self._cloud_api.login()

                if self._cloud_api.token:
                    # Also create the transport here so possible errors are shown
                    self._mqtt_transport = GreeMqttTransport(
                        user_id=str(self._cloud_api.user_id),
                        token=self._cloud_api.token,
                        region=self._cloud_api.region,
                    )
                    await self._mqtt_transport.connect()
                else:
                    errors[CONF_BASE] = "cloud_unknown"

            except GreeCloudLoginError:
                errors[CONF_BASE] = "cloud_bad_login"
            except GreeCloudError:
                errors[CONF_BASE] = "cloud_unknown"
            except MqttError:
                errors[CONF_BASE] = "cloud_bad_login"

            else:
                await self.async_set_unique_id(str(self._cloud_api.user_id))

                if self._reconfigure_entry or self._reauth_entry:
                    self._abort_if_unique_id_mismatch()
                else:
                    self._abort_if_unique_id_configured()

                self._config_data[CONF_CLOUD] = user_input
                self._config_data[CONF_CLOUD][CONF_TOKEN] = self._cloud_api.token
                self._config_data[CONF_CLOUD][CONF_UID] = self._cloud_api.user_id

                # If a reauth simply exit and update the entry with new data if necessary
                if self._reauth_entry:
                    return self._async_finish()

                discovered = await gree_discover_devices_cloud(self._cloud_api)
                self._discovered_devices_cloud = {d.mac: d for d in discovered}
                _LOGGER.info(
                    "Discovered %d devices from the cloud account: %s",
                    len(self._discovered_devices_cloud),
                    self._cloud_api.username,
                )
                return await self._setup_next_setup_method()

            finally:
                await self._cloud_api.close()

        # During reconfigure or reauth, inject existing configuration
        defaults = None
        if user_input:
            defaults = user_input
        elif self._reconfigure_data:
            defaults = self._reconfigure_data.get(CONF_CLOUD)
        elif self._reauth_data:
            defaults = self._reauth_data.get(CONF_CLOUD)

        return self.async_show_form(
            step_id="cloud_add",
            data_schema=_setup_cloud_schema(defaults),
            errors=errors,
        )

    def _evaluate_and_cap_max_hosts(
        self, extra_networks: list[str], extra_hosts: list[str]
    ) -> dict[str, str]:
        errors: dict[str, str] = {}
        num_hosts = 0
        for cidr in extra_networks:
            try:
                net = ip_network(cidr, strict=False)
            except ValueError:
                errors[CONF_EXTRA_SCAN_NETWORKS] = "invalid_network"
                break

            if not isinstance(net, IPv4Network):
                errors[CONF_EXTRA_SCAN_NETWORKS] = "invalid_network"
                break

            # /31 => 2 usable, /32 => 1 usable, otherwise subtract net+broadcast
            usable = net.num_addresses if net.prefixlen >= 31 else net.num_addresses - 2
            if usable > MAX_UNICAST_SCAN_HOSTS:
                errors[CONF_EXTRA_SCAN_NETWORKS] = "network_too_large"
                break
            num_hosts += usable

        for ip in extra_hosts:
            try:
                addr = ip_address(ip)
            except ValueError:
                errors[CONF_EXTRA_SCAN_HOSTS] = "invalid_host"
                break

            if not isinstance(addr, IPv4Address):
                errors[CONF_EXTRA_SCAN_HOSTS] = "invalid_host"
                break
            num_hosts += 1

        if num_hosts > MAX_UNICAST_SCAN_HOSTS:
            errors[CONF_BASE] = "too_many_targets"

        return errors

    async def async_step_local_add(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Gather local discovery info for later."""
        errors: dict[str, str] = {}

        self._pref_storage = self._pref_storage or Store(
            self.hass, CONF_DISCOVERY_PREFS_VERSION, CONF_DISCOVERY_PREFS_KEY
        )

        if user_input is not None:
            self._extra_networks = user_input.get(CONF_EXTRA_SCAN_NETWORKS, [])
            self._extra_hosts = user_input.get(CONF_EXTRA_SCAN_HOSTS, [])

            errors = self._evaluate_and_cap_max_hosts(
                self._extra_networks, self._extra_hosts
            )

            if not errors:
                # Persist values in the HA storage for future config flows to access
                await self._pref_storage.async_save(
                    {
                        CONF_EXTRA_SCAN_NETWORKS: self._extra_networks,
                        CONF_EXTRA_SCAN_HOSTS: self._extra_hosts,
                    }
                )
                self._config_data["local"] = user_input

                # Discover local devices
                discovered = await gree_discover_devices_local(
                    broadcast_addresses=await get_discovery_addresses(self.hass),
                    timeout=DEFAULT_DISCOVERY_TIMEOUT,
                    user_id=0,
                )
                self._discovered_devices_local = {d.mac: d for d in discovered}
                _LOGGER.info(
                    "Discovered %d devices from local discovery",
                    len(self._discovered_devices_local),
                )
                return await self._setup_next_setup_method()

        # Pre-fill from previous run (in storage, if any) or from current submission
        prefs = await self._pref_storage.async_load() or {}
        default_networks: list[str] = self._extra_networks or prefs.get(
            CONF_EXTRA_SCAN_NETWORKS, []
        )
        default_hosts: list[str] = self._extra_hosts or prefs.get(
            CONF_EXTRA_SCAN_HOSTS, []
        )

        return self.async_show_form(
            step_id="local_add",
            data_schema=_setup_local_schema(
                {
                    CONF_EXTRA_SCAN_NETWORKS: default_networks,
                    CONF_EXTRA_SCAN_HOSTS: default_hosts,
                }
            ),
            errors=errors,
        )

    def _already_configured_macs(self) -> set[str]:
        return {
            subentry.unique_id
            for entry in self.hass.config_entries.async_entries(DOMAIN)
            for subentry in entry.subentries.values()
            if subentry.unique_id
        }

    async def async_step_device_picker(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Let users pick devices to add, edit or remove."""
        errors: dict[str, str] = {}

        if user_input is not None:
            selected: list[str] = user_input.get(CONF_DEVICES, [])

            if not selected:
                errors[CONF_DEVICES] = "no_devices_selected"

            if not errors:
                self._selected_devices = [
                    self._discovered_devices[key]
                    for key in selected
                    if key in self._discovered_devices
                ]
                self._local_transports = self._create_local_transports(
                    self._selected_devices
                )
                return await self.async_step_connection_options()

        selected = list(self._discovered_devices.keys())
        if self._reconfigure_data:
            configured_devices: dict[str, Any] = self._reconfigure_data.get(
                CONF_DEVICES, {}
            )

            # Don't select things by default that were not there before
            for d in self._discovered_devices:
                if d not in configured_devices:
                    selected.remove(d)

            # During a reconfigure inject previously configured devices to the picker if they were not discovered and mark as selected
            for mac, dev_conf in configured_devices.items():
                if mac and mac not in self._discovered_devices:
                    conn = dev_conf.get(CONF_DEVICE_CONNECTION, {})
                    local = conn.get(CONF_DEVICE_CONNECTION_LOCAL, {})
                    cloud = conn.get(CONF_DEVICE_CONNECTION_CLOUD, {})
                    dev = GreeDiscoveredDevice(
                        mac=mac,
                        mac_controller_local=local.get(CONF_MAC_CONTROLLER_LOCAL, ""),
                        mac_controller_mqtt=cloud.get(CONF_MAC_CONTROLLER_CLOUD, ""),
                        user_id=conn.get(CONF_UID, DEFAULT_DEVICE_UID),
                        key=conn.get(CONF_ENCRYPTION_KEY, ""),
                        host=local.get(CONF_HOST, ""),
                        port=local.get(CONF_PORT, ""),
                    )
                    self._discovered_devices[mac] = dev

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_DEVICES,
                    default=selected,
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(value=device_id, label=name.friendly_name)
                            for device_id, name in self._discovered_devices.items()
                        ],
                        multiple=True,
                    )
                )
            }
        )

        return self.async_show_form(
            step_id="device_picker",
            data_schema=data_schema,
            description_placeholders={
                "devices_found": str(len(self._discovered_devices))
            },
            errors=errors,
        )

    def _create_local_transports(
        self, target_devices: list[GreeDiscoveredDevice]
    ) -> dict[str, GreeUdpTransport]:
        """Create the required transport for each of the target devices."""

        # Transports should be one for each controller device, if local device
        # and the previously create MQTT transport for all the cloud devices.
        transports: dict[str, GreeUdpTransport] = {}
        local_transports: dict[str, GreeUdpTransport] = {}

        for d in target_devices:
            if d.host and d.port:
                if d.mac_controller_local not in local_transports:
                    local_transports[d.mac_controller_local] = GreeUdpTransport(
                        ip_addr=d.host, port=d.port
                    )
                    _LOGGER.debug(
                        "Created UDP transport for device '%s': %s",
                        d.mac,
                        local_transports[d.mac_controller_local],
                    )
                else:
                    _LOGGER.debug(
                        "Using previously created UDP transport for device '%s': %s",
                        d.mac,
                        local_transports[d.mac_controller_local],
                    )
                transports[d.mac] = local_transports[d.mac_controller_local]

        return transports

    async def async_step_connection_options(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Iterate throught the selected devices to configure their connection options."""
        errors: dict[str, str] = {}
        d = self._selected_devices[self._current_setup_device_index]

        if user_input is not None:
            local = user_input.get(CONF_DEVICE_CONNECTION_LOCAL, {})
            cloud = user_input.get(CONF_DEVICE_CONNECTION_CLOUD, {})
            device = GreeDevice(
                name=d.name,
                mac_addr=d.mac,
                preferred_encryption_key=user_input.get(CONF_ENCRYPTION_KEY, d.key),
                user_id=user_input.get(CONF_UID, d.user_id),
            )

            # Ensure the device can bind
            try:
                encryption_version_value = local.get(
                    CONF_ENCRYPTION_VERSION, DEFAULT_ENCRYPTION_VERSION
                )
                await device.bind_with_transport(
                    preferred_local_version=(
                        None
                        if encryption_version_value == ENCRYPTION_VERSION_AUTO
                        else EncryptionVersion(int(encryption_version_value))
                    ),
                    local_controller_mac=local.get(
                        CONF_MAC_CONTROLLER_LOCAL, d.mac_controller_local
                    ),
                    local_transport=(
                        self._local_transports.get(d.mac, None)
                        if not cloud.get(CONF_PREFER_CLOUD, DEFAULT_PREFER_CLOUD)
                        else None
                    ),
                    mqtt_controller_mac=cloud.get(
                        CONF_MAC_CONTROLLER_CLOUD, d.mac_controller_mqtt
                    ),
                    mqtt_transport=self._mqtt_transport,
                )
            except GreeBindingError:
                errors[CONF_BASE] = "cannot_bind"
                _LOGGER.exception("Error while binding")
            except GreeConnectionError:
                errors[CONF_BASE] = "cannot_connect"
                _LOGGER.exception("Cannot connect")
            except MqttError:
                errors[CONF_BASE] = "cannot_connect_mqtt"
                _LOGGER.exception("Cannot connect to MQTT")
            except Exception:
                errors[CONF_BASE] = "unknown"
                _LOGGER.exception("Unknown error while binding")

            if not errors:
                # Save the correct version if local succedded
                if (
                    isinstance(device.transport, GreeUdpTransport)
                    and device.encryption_version
                ):
                    user_input[CONF_DEVICE_CONNECTION_LOCAL][
                        CONF_ENCRYPTION_VERSION
                    ] = str(device.encryption_version.value)

                self._config_data[CONF_ALL_DEVICE_CONNECTIONS][d.mac] = user_input
                self._connections_by_controller[device.mac_address_controller] = (
                    user_input
                )
                self._devices[d.mac] = device

                if self._current_setup_device_index >= len(self._selected_devices) - 1:
                    self._current_setup_device_index = 0
                    return await self.async_step_device_options()

                self._current_setup_device_index += 1
                return await self.async_step_connection_options()

        # During reconfigure inject previous connection options
        default = user_input or (
            self._reconfigure_data.get(CONF_DEVICES, {})
            .get(d.mac, {})
            .get(CONF_DEVICE_CONNECTION, {})
            if self._reconfigure_data
            else {}
        )
        defaults = default or self._connections_by_controller.get(
            d.mac_controller_local
        )

        return self.async_show_form(
            step_id="connection_options",
            data_schema=_setup_device_connection_options_schema(d, defaults),
            description_placeholders={
                "device_idx": str(self._current_setup_device_index + 1),
                "device_cnt": str(len(self._selected_devices)),
                "device_name": str(d.name),
            },
            errors=errors,
        )

    async def async_step_device_options(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Iterate throught the selected devices to configure their options."""
        errors: dict[str, str] = {}
        d = self._selected_devices[self._current_setup_device_index]
        device = self._devices[d.mac]

        if user_input is not None:
            self._config_data[CONF_ALL_DEVICE_OPTIONS][d.mac] = user_input
            self._options_by_controller[device.mac_address_controller] = user_input

            if self._current_setup_device_index >= len(self._selected_devices) - 1:
                self._current_setup_device_index = 0
                return self._async_finish()

            self._current_setup_device_index += 1
            return await self.async_step_device_options()

        default = user_input or (
            self._reconfigure_data.get(CONF_DEVICES, {})
            .get(d.mac, {})
            .get(CONF_DEVICE_OPTIONS, {})
            if self._reconfigure_data
            else {}
        )
        data_schema = _setup_device_options_schema(
            hass=self.hass,
            device=device,
            default_values=(
                default
                or self._options_by_controller.get(device.mac_address_controller)
            ),
        )

        return self.async_show_form(
            step_id="device_options",
            data_schema=data_schema,
            description_placeholders={
                "device_idx": str(self._current_setup_device_index + 1),
                "device_cnt": str(len(self._selected_devices)),
                "device_mac": str(d.mac),
            },
            errors=errors,
        )

    def _async_finish(self) -> ConfigFlowResult:
        """Create or update the entry."""

        if self._reauth_entry:
            return self.async_update_reload_and_abort(
                self._reauth_entry,
                title=self._config_data.get(CONF_CLOUD, {}).get(
                    CONF_EMAIL, "Local-only Devices"
                ),
                data_updates={CONF_CLOUD: self._config_data.get(CONF_CLOUD, {})},
            )

        device_configs = {}
        for d in self._selected_devices:
            device_configs[str(self._devices[d.mac].mac_address)] = {
                CONF_DEVICE_CONNECTION: self._config_data[CONF_ALL_DEVICE_CONNECTIONS][
                    d.mac
                ],
                CONF_DEVICE_OPTIONS: self._config_data[CONF_ALL_DEVICE_OPTIONS][d.mac],
            }
        data = {
            CONF_CLOUD: self._config_data.get(CONF_CLOUD),
            CONF_DEVICES: device_configs,
        }

        if self._reconfigure_entry:
            return self.async_update_reload_and_abort(
                self._reconfigure_entry,
                title=self._config_data.get(CONF_CLOUD, {}).get(
                    CONF_EMAIL, "Local-only Devices"
                ),
                data=data,
            )

        _LOGGER.debug(
            "New entry with config: %s",
            async_redact_data(data, ["encryption_key"]),
        )
        return self.async_create_entry(
            title=self._config_data.get(CONF_CLOUD, {}).get(
                CONF_EMAIL, "Local-only Devices"
            ),
            data=data,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of an existing entry."""
        self._reconfigure_entry = self._get_reconfigure_entry()
        self._reconfigure_data = dict(self._reconfigure_entry.data)
        _LOGGER.debug("Reconfiguring: %s", self._reconfigure_entry.title)

        has_cloud = self._reconfigure_data.get(CONF_CLOUD) is not None
        has_local = any(
            d.get(CONF_DEVICE_CONNECTION, {})
            .get(CONF_DEVICE_CONNECTION_LOCAL, {})
            .get(CONF_HOST)
            is not None
            for d in self._reconfigure_data.get(CONF_DEVICES, {}).values()
        )

        # If on the local-only entry, continue with the local method only
        if has_local and not has_cloud:
            self._selected_setup_methods = ["local"]
            self._current_setup_method_index = 0
            return await self._setup_next_setup_method()

        # If entry has cloud, ask if user wants to add local
        # A user cannot remove cloud from an entry, because the entry is keyed by the cloud account
        # For that, remove the entry and add to the local-only entry
        if user_input is not None:
            self._selected_setup_methods = ["cloud"]
            if user_input.get("include_local", False):
                self._selected_setup_methods.append("local")
            self._current_setup_method_index = 0
            return await self._setup_next_setup_method()

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "include_local",
                        default=has_local,
                    ): cv.boolean
                }
            ),
        )

    async def async_step_reauth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Process a Reauth request."""
        self._reauth_entry = self._get_reauth_entry()
        self._reauth_data = dict(self._reauth_entry.data)
        _LOGGER.debug("Reauth entry: %s", self._reauth_entry.title)

        return await self.async_step_cloud_add()
