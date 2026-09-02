"""Config flow to configure the Gree integration."""

from collections.abc import Mapping
from ipaddress import IPv4Address, IPv4Network, ip_address, ip_network
import logging
from typing import Any, override

from aiomqtt import MqttError
import voluptuous as vol

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN, SensorDeviceClass
from homeassistant.config_entries import (
    SOURCE_REAUTH,
    SOURCE_RECONFIGURE,
    SOURCE_USER,
    ConfigFlow,
    ConfigFlowResult,
)
from homeassistant.const import (
    CONF_BASE,
    CONF_DISCOVERY,
    CONF_EMAIL,
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_REGION,
    CONF_SCAN_INTERVAL,
    CONF_TIMEOUT,
    CONF_TOKEN,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import section
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
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
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from homeassistant.helpers.storage import Store

from .aiogree.api import (
    GreeDiscoveredDevice,
    GreeProp,
    gree_discover_device_local,
    gree_discover_devices_cloud,
    gree_discover_devices_local,
    gree_merge_discovered_devices,
)
from .aiogree.cipher import EncryptionVersion
from .aiogree.cloud_api import GreeCloudApi, GreeRegion
from .aiogree.device import GreeDevice
from .aiogree.errors import (
    GreeBindingError,
    GreeCloudLoginError,
    GreeConnectionError,
    GreeError,
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
    CURRENT_CONF_VERSION,
    DEFAULT_CONNECTION_MAX_ATTEMPTS,
    DEFAULT_CONNECTION_TIMEOUT,
    DEFAULT_DEVICE_PORT,
    DEFAULT_DEVICE_UID,
    DEFAULT_DISABLE_AVAILABLE_CHECK,
    DEFAULT_DISCOVERY_TIMEOUT,
    DEFAULT_ENCRYPTION_KEY,
    DEFAULT_ENCRYPTION_VERSION,
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
from .helpers import (
    create_discovered_from_config,
    get_config_entries,
    get_configured_macs_in_entries,
    get_discovery_addresses,
    get_entity_ids_from_unique_ids,
    get_entry_matching_mac,
)

_LOGGER = logging.getLogger(__name__)


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
                description={
                    "suggested_value": defaults.get(CONF_EXTRA_SCAN_NETWORKS, [])
                },
            ): TextSelector(TextSelectorConfig(multiple=True, multiline=False)),
            vol.Optional(
                CONF_EXTRA_SCAN_HOSTS,
                description={
                    "suggested_value": defaults.get(CONF_EXTRA_SCAN_HOSTS, [])
                },
            ): TextSelector(TextSelectorConfig(multiple=True, multiline=False)),
        }
    )


def _setup_picker_schema(
    default: list[str], options: dict[str, GreeDiscoveredDevice]
) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_DEVICES, default=default): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value=m, label=d.friendly_name)
                        for m, d in options.items()
                    ],
                    multiple=True,
                )
            )
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
                                defaults_local.get(CONF_PORT)
                                or device_info.port
                                or DEFAULT_DEVICE_PORT
                            ),
                        ): cv.port,
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
                                translation_key=CONF_ENCRYPTION_VERSION,
                                options=[
                                    ENCRYPTION_VERSION_AUTO,
                                    *(
                                        str(version.value)
                                        for version in EncryptionVersion
                                    ),
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
                            default=defaults_cloud.get(CONF_MAC_CONTROLLER_CLOUD)
                            or device_info.mac_controller_mqtt,
                        ): str,
                    }
                )
            ),
        }
    )


def _setup_device_options_schema(  # noqa: C901
    hass: HomeAssistant, device: GreeDevice, default_values: Mapping | None
) -> vol.Schema:
    defaults = default_values or {}

    schema: dict = {}
    schema.update(
        {
            vol.Required(
                CONF_NAME,
                default=defaults.get(CONF_NAME, device.name),
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
            vol.Optional(
                ATTR_EXTERNAL_TEMPERATURE_SENSOR,
                description={
                    "suggested_value": defaults.get(
                        ATTR_EXTERNAL_TEMPERATURE_SENSOR, ""
                    )
                },
            ): EntitySelector(
                config=EntitySelectorConfig(
                    domain=SENSOR_DOMAIN,
                    device_class=SensorDeviceClass.TEMPERATURE,
                    multiple=False,
                    exclude_entities=get_entity_ids_from_unique_ids(
                        hass,
                        SENSOR_DOMAIN,
                        [
                            f"{device.mac_address}_indoor_temperature",
                            f"{device.mac_address}_outdoor_temperature",
                        ],
                    ),
                )
            ),
            vol.Optional(
                ATTR_EXTERNAL_HUMIDITY_SENSOR,
                description={
                    "suggested_value": defaults.get(ATTR_EXTERNAL_HUMIDITY_SENSOR, "")
                },
            ): EntitySelector(
                config=EntitySelectorConfig(
                    domain=SENSOR_DOMAIN,
                    device_class=SensorDeviceClass.HUMIDITY,
                    multiple=False,
                    exclude_entities=get_entity_ids_from_unique_ids(
                        hass,
                        SENSOR_DOMAIN,
                        [
                            f"{device.mac_address}_room_humidity",
                        ],
                    ),
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

    VERSION = CURRENT_CONF_VERSION

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
        self._cloud_api: GreeCloudApi | None = None

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
    async def async_step_dhcp(
        self, discovery_info: DhcpServiceInfo
    ) -> ConfigFlowResult:
        """Handle discovery via dhcp."""

        _LOGGER.debug("Gree device discovered from dhcp: %s", discovery_info)

        # Check what's under that device: Main device and sub-devices
        # If it does not respond locally, there's no use of this information
        discover = await gree_discover_device_local(
            discovery_info.ip, DEFAULT_DISCOVERY_TIMEOUT, DEFAULT_DEVICE_UID
        )

        entries_to_reload: list[GreeConfigEntry] = []
        for d in list(discover):
            entry_match = get_entry_matching_mac(self.hass, d.mac)

            if entry_match:
                _LOGGER.debug(
                    "Device '%s' is already configured in entry %s",
                    discovery_info,
                    entry_match.title,
                )

                discover.remove(d)

                # update data
                new_data = dict(entry_match.data)
                new_data[CONF_DEVICES][discovery_info.macaddress][
                    CONF_DEVICE_CONNECTION
                ][CONF_DEVICE_CONNECTION_LOCAL][CONF_HOST] = discovery_info.ip
                # TODO: Check if this only returns True if the IP Changed
                if (
                    self.hass.config_entries.async_update_entry(
                        entry_match, data=new_data
                    )
                    and entry_match.unique_id
                ):
                    if entry_match not in entries_to_reload:
                        _LOGGER.debug(
                            "Entry '%s' marked for reload",
                            entry_match.title,
                        )
                        entries_to_reload.append(entry_match)

        for e in entries_to_reload:
            _LOGGER.debug(
                "Entry '%s' reloading",
                e.title,
            )
            self.hass.config_entries.async_schedule_reload(e.entry_id)

        return self.async_abort(reason="reconfigure_successful")

    @override
    async def async_step_user(self, user_input: dict | None = None) -> ConfigFlowResult:
        """Handle the initial step - how to add devices."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._selected_setup_methods = user_input[CONF_DISCOVERY]

            if not self._selected_setup_methods:
                errors[CONF_DISCOVERY] = "no_methods_selected"

            if not errors:
                if self._selected_setup_methods == ["local"]:
                    await self.async_set_unique_id(CONFENTRY_ID_LOCAL_ONLY)
                else:
                    # Cloud must come first
                    self._selected_setup_methods = sorted(
                        self._selected_setup_methods, key=lambda x: x != "cloud"
                    )

                self._current_setup_method_index = 0
                return await self._setup_next_setup_method()

        return self.async_show_form(
            step_id="user", data_schema=SETUP_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Process a Reauth request."""
        reauth_entry = self._get_reauth_entry()
        _LOGGER.debug("Reauth entry: %s", reauth_entry.title)

        return await self.async_step_cloud_add()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of an existing entry."""
        reconfigure_entry = self._get_reconfigure_entry()
        reconfigure_data = dict(reconfigure_entry.data)
        _LOGGER.debug("Reconfiguring: %s", reconfigure_entry.title)

        # If on the local-only entry, exit early and continue with the local method only
        if reconfigure_entry.unique_id == CONFENTRY_ID_LOCAL_ONLY:
            self._selected_setup_methods = ["local"]
            self._current_setup_method_index = 0
            await self.async_set_unique_id(CONFENTRY_ID_LOCAL_ONLY)
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

        # Pre-select the include local option if any devices have local configurations
        has_local = any(
            d.get(CONF_DEVICE_CONNECTION, {})
            .get(CONF_DEVICE_CONNECTION_LOCAL, {})
            .get(CONF_HOST)
            is not None
            for d in reconfigure_data.get(CONF_DEVICES, {}).values()
        )

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

    async def _setup_next_setup_method(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Invoke the next selected setup method."""

        if self._current_setup_method_index >= len(self._selected_setup_methods):
            discovered = gree_merge_discovered_devices(
                local_devices=list(self._discovered_devices_local.values()),
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

    async def async_step_cloud_add(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Gather cloud info for later discovery."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._cloud_api = GreeCloudApi(
                region=GreeRegion(user_input[CONF_REGION]),
                username=user_input[CONF_EMAIL],
                password=user_input[CONF_PASSWORD],
            )
            try:
                credentials = await self._cloud_api.login()

                # Also create the transport here so possible errors are shown
                self._mqtt_transport = GreeMqttTransport(
                    user_id=str(credentials.user_id),
                    token=credentials.token,
                    region=self._cloud_api.region,
                )
                await self._mqtt_transport.connect()

                # Use the user_id as the unique_id since it is more stable than the email
                await self.async_set_unique_id(str(self._cloud_api.user_id))

                # Exit early if there is a config entry with this user_id
                if self.source == SOURCE_USER:
                    self._abort_if_unique_id_configured()

                # Ensure reconfigure is of the same user_id
                self._abort_if_unique_id_mismatch()

                self._config_data[CONF_CLOUD] = {
                    **user_input,
                    CONF_TOKEN: credentials.token,
                    CONF_UID: credentials.user_id,
                }

                # If a reauth simply exit and update the entry with new data if necessary
                if self.source == SOURCE_REAUTH:
                    return await self._async_finish()

                discovered = await gree_discover_devices_cloud(self._cloud_api)
                self._discovered_devices_cloud = {d.mac: d for d in discovered}

                _LOGGER.info(
                    "Discovered %d devices from the cloud account: %s",
                    len(self._discovered_devices_cloud),
                    self._cloud_api.username,
                )
                return await self._setup_next_setup_method()

            except GreeCloudLoginError:
                errors[CONF_BASE] = "cloud_bad_login"
            except MqttError:
                errors[CONF_BASE] = "cloud_bad_login"
            except GreeError:
                errors[CONF_BASE] = "cloud_unknown"

            finally:
                await self._cloud_api.close()

        # During reconfigure or reauth, inject existing configuration
        defaults: dict[str, Any] = user_input or {}
        if not user_input:
            if self.source == SOURCE_RECONFIGURE:
                defaults = self._get_reconfigure_entry().data.get(CONF_CLOUD, {})
            elif self.source == SOURCE_REAUTH:
                defaults = self._get_reauth_entry().data.get(CONF_CLOUD, {})

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

                # Discover local devices: main devices and sub-devices of controllers (VRF)
                discovered = await gree_discover_devices_local(
                    broadcast_addresses=await get_discovery_addresses(self.hass),
                    timeout=DEFAULT_DISCOVERY_TIMEOUT,
                    user_id=0,
                )

                # if reconfiguring the local-only: Only consider local discovered that are not in other cloud entries
                # if reconfiguring cloud with local: Only consider local discovered that are not in other cloud entries
                # if adding a local-only: Only consider new local
                # if adding a cloud with local: Only consider local that match cloud discovered

                if self.source == SOURCE_RECONFIGURE:
                    to_ignore = [CONFENTRY_ID_LOCAL_ONLY]
                    if self.unique_id:
                        to_ignore.append(self.unique_id)
                    other_configured = get_configured_macs_in_entries(
                        self.hass, ignore_entries=to_ignore
                    )
                else:
                    other_configured = get_configured_macs_in_entries(
                        self.hass,
                        ignore_entries=None
                        if self.unique_id == CONFENTRY_ID_LOCAL_ONLY
                        else [CONFENTRY_ID_LOCAL_ONLY],
                    )
                discovered = [
                    dev for dev in discovered if dev.mac not in other_configured
                ]

                # Because local discovery always happens after cloud discovery
                # Filter out discovered devices that are not in the cloud discovery
                if self._discovered_devices_cloud:
                    discovered = [
                        dev
                        for dev in discovered
                        if dev.mac in self._discovered_devices_cloud
                    ]

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

    async def async_step_device_picker(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Let users pick devices to add, edit or remove."""
        errors: dict[str, str] = {}

        if user_input is not None:
            selected: list[str] = user_input.get(CONF_DEVICES, [])

            if selected:
                self._selected_devices = [
                    self._discovered_devices[key] for key in selected
                ]

                return await self.async_step_connection_options()

            errors[CONF_DEVICES] = "no_devices_selected"

        selected = list(self._discovered_devices.keys())

        # Pre-fill for reconfigure
        if self.source == SOURCE_RECONFIGURE:
            configured_devices: dict[str, Any] = self._get_reconfigure_entry().data.get(
                CONF_DEVICES, {}
            )

            # Don't select things by default that were not there before
            selected = [m for m in selected if m in configured_devices]

            # Add back missing devices that weren't discovered but were in config
            for mac, dev_conf in configured_devices.items():
                if mac not in self._discovered_devices:
                    self._discovered_devices[mac] = create_discovered_from_config(
                        mac, dev_conf
                    )
                    selected.append(mac)

        if not self._discovered_devices:
            return self.async_abort(reason="no_devices_to_add")

        return self.async_show_form(
            step_id="device_picker",
            data_schema=_setup_picker_schema(selected, self._discovered_devices),
            description_placeholders={
                "devices_found": str(len(self._discovered_devices))
            },
            errors=errors,
        )

    async def async_step_connection_options(  # noqa: C901
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Iterate through the selected devices to configure their connection options."""
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
                mac_local_controller = local.get(
                    CONF_MAC_CONTROLLER_LOCAL, d.mac_controller_local
                )
                mac_mqtt_controller = cloud.get(
                    CONF_MAC_CONTROLLER_CLOUD, d.mac_controller_mqtt
                )
                encryption_version_value = local.get(
                    CONF_ENCRYPTION_VERSION, DEFAULT_ENCRYPTION_VERSION
                )

                ip = local.get(CONF_HOST, "")
                port = local.get(CONF_PORT, "")

                local_transport = self._local_transports.get(
                    mac_local_controller, GreeUdpTransport(ip_addr=ip, port=port)
                )

                await device.bind_with_transport(
                    preferred_local_version=(
                        None
                        if encryption_version_value == ENCRYPTION_VERSION_AUTO
                        else EncryptionVersion(int(encryption_version_value))
                    ),
                    local_controller_mac=mac_local_controller,
                    local_transport=(
                        local_transport
                        if not cloud.get(CONF_PREFER_CLOUD, DEFAULT_PREFER_CLOUD)
                        else None
                    ),
                    mqtt_controller_mac=mac_mqtt_controller,
                    mqtt_transport=self._mqtt_transport,
                )

                if mac_local_controller:
                    self._local_transports[mac_local_controller] = local_transport

                # Save the correct version if local succeeded
                if (
                    isinstance(device.transport, GreeUdpTransport)
                    and device.encryption_version
                ):
                    user_input[CONF_DEVICE_CONNECTION_LOCAL][
                        CONF_ENCRYPTION_VERSION
                    ] = str(device.encryption_version.value)

                user_input[CONF_ENCRYPTION_KEY] = device.encryption_key
                self._config_data[CONF_ALL_DEVICE_CONNECTIONS][d.mac] = user_input

                if mac_local_controller:
                    self._connections_by_controller[mac_local_controller] = user_input
                if mac_mqtt_controller:
                    self._connections_by_controller[mac_mqtt_controller] = user_input

                self._devices[d.mac] = device

                if self._current_setup_device_index >= len(self._selected_devices) - 1:
                    self._current_setup_device_index = 0
                    return await self.async_step_device_options()

                self._current_setup_device_index += 1
                return await self.async_step_connection_options()

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

        default = user_input

        # During user setup find if the device is already configured so we can prefill a cloud device with already configured local device
        found_device_entry = get_entry_matching_mac(self.hass, d.mac)
        if not default and self.source == SOURCE_USER and found_device_entry:
            default = (
                found_device_entry.data.get(CONF_DEVICES, {})
                .get(d.mac, {})
                .get(CONF_DEVICE_CONNECTION, None)
            )

        # During reconfigure inject previous connection options
        if not default and self.source == SOURCE_RECONFIGURE:
            default = (
                self._get_reconfigure_entry()
                .data.get(CONF_DEVICES, {})
                .get(d.mac, {})
                .get(CONF_DEVICE_CONNECTION, None)
            )

        defaults = (
            default
            or self._connections_by_controller.get(d.mac_controller_local)
            or self._connections_by_controller.get(d.mac_controller_mqtt)
        )

        return self.async_show_form(
            step_id="connection_options",
            data_schema=_setup_device_connection_options_schema(d, defaults),
            description_placeholders={
                "device_name": str(d.friendly_name),
                "device_idx": str(self._current_setup_device_index + 1),
                "device_cnt": str(len(self._selected_devices)),
                "discovered_ip": str(d.host or "None"),
                "discovered_mac_local": str(d.mac_controller_local or "None"),
                "discovered_mac_cloud": str(d.mac_controller_mqtt or "None"),
            },
            errors=errors,
        )

    async def async_step_device_options(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Iterate through the selected devices to configure their options."""
        errors: dict[str, str] = {}
        d = self._selected_devices[self._current_setup_device_index]
        device = self._devices[d.mac]

        if user_input is not None:
            self._config_data[CONF_ALL_DEVICE_OPTIONS][d.mac] = user_input
            self._options_by_controller[device.mac_address_controller] = user_input

            if self._current_setup_device_index >= len(self._selected_devices) - 1:
                self._current_setup_device_index = 0
                return await self._async_finish()

            self._current_setup_device_index += 1
            return await self.async_step_device_options()

        default = user_input

        # During user setup find if the device is already configured
        if not default and self.source == SOURCE_USER:
            found_device_entry = get_entry_matching_mac(self.hass, d.mac)
            if found_device_entry:
                default = (
                    found_device_entry.data.get(CONF_DEVICES, {})
                    .get(d.mac, {})
                    .get(CONF_DEVICE_OPTIONS, None)
                )

        # During reconfigure inject previous device options
        if not default and self.source == SOURCE_RECONFIGURE:
            default = (
                self._get_reconfigure_entry()
                .data.get(CONF_DEVICES, {})
                .get(d.mac, {})
                .get(CONF_DEVICE_OPTIONS, {})
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
                "device_name": str(d.friendly_name),
            },
            errors=errors,
        )

    async def _async_finish(self) -> ConfigFlowResult:  # noqa: C901
        """Create or update the entry."""

        if self.source == SOURCE_REAUTH:
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(),
                data_updates={CONF_CLOUD: self._config_data.get(CONF_CLOUD, {})},
            )

        device_registry = dr.async_get(self.hass)

        device_configs: dict[str, Any] = {}
        for d in self._selected_devices:
            mac = str(self._devices[d.mac].mac_address)
            device_configs[mac] = {
                CONF_DEVICE_CONNECTION: self._config_data[CONF_ALL_DEVICE_CONNECTIONS][
                    d.mac
                ],
                CONF_DEVICE_OPTIONS: self._config_data[CONF_ALL_DEVICE_OPTIONS][d.mac],
            }

        local_entry = next(
            iter(
                get_config_entries(self.hass, match_entries=[CONFENTRY_ID_LOCAL_ONLY])
            ),
            None,
        )

        # Handling migration from Local-only to Cloud entry
        if self.unique_id != CONFENTRY_ID_LOCAL_ONLY:
            if local_entry:
                local_devices = dict(local_entry.data.get(CONF_DEVICES, {}))
                moved_any = False
                for mac in list(local_devices.keys()):
                    if mac in self._discovered_devices_cloud:
                        # Move this device to the new cloud entry
                        if mac not in device_configs:
                            device_configs[mac] = local_devices[mac]
                        local_devices.pop(mac)
                        moved_any = True

                        # remove from registry, it will be added by the new entry
                        dev = device_registry.async_get_device(
                            identifiers={(DOMAIN, mac)}
                        )
                        if dev:
                            device_registry.async_remove_device(dev.id)

                if moved_any:
                    if local_devices:
                        new_local_data = {
                            **local_entry.data,
                            CONF_DEVICES: local_devices,
                        }
                        self.hass.config_entries.async_update_entry(
                            local_entry, data=new_local_data
                        )
                        self.hass.config_entries.async_schedule_reload(
                            local_entry.entry_id
                        )
                    else:
                        # No other devices, remove the entry
                        await self.hass.config_entries.async_remove(
                            local_entry.entry_id
                        )

        # For adding a local entry which comes only with new local devices despite it
        # being possible for the entry to exist already with other devices
        # Readd the ones not picked in this flow but are in the local entry already
        if (
            self.source == SOURCE_USER
            and self.unique_id == CONFENTRY_ID_LOCAL_ONLY
            and local_entry
        ):
            device_configs = {
                **local_entry.data.get(CONF_DEVICES, {}),
                **device_configs,
            }

        data = {
            CONF_CLOUD: self._config_data.get(CONF_CLOUD),
            CONF_DEVICES: device_configs,
        }

        # Determine update target
        update_entry = None
        if self.source == SOURCE_RECONFIGURE:
            update_entry = self._get_reconfigure_entry()
        elif self.unique_id == CONFENTRY_ID_LOCAL_ONLY:
            update_entry = next(
                iter(
                    get_config_entries(
                        self.hass, match_entries=[CONFENTRY_ID_LOCAL_ONLY]
                    )
                ),
                None,
            )

        title = self._config_data.get(CONF_CLOUD, {}).get(
            CONF_EMAIL, "Local-only Devices"
        )

        if update_entry:
            # remove devices that are no longer provided by the entry
            # they will be re-added if they exist in another entry
            previous_configured: dict[str, Any] = update_entry.data.get(
                CONF_DEVICES, {}
            )
            for m in previous_configured:
                if self.source == SOURCE_RECONFIGURE and m not in device_configs:
                    dev = device_registry.async_get_device(identifiers={(DOMAIN, m)})
                    if dev:
                        device_registry.async_remove_device(dev.id)

            if update_entry.unique_id == CONFENTRY_ID_LOCAL_ONLY and not device_configs:
                # No other devices, remove the local-only entry
                # If a cloud entry, ignore and keep it so we preserve account data if the user wants
                await self.hass.config_entries.async_remove(update_entry.entry_id)
                return self.async_abort(reason="reconfigure_successful")

            return self.async_update_reload_and_abort(
                update_entry,
                title=title,
                data_updates=data,
                reason="reconfigure_successful",
            )

        _LOGGER.debug(
            "New entry with config: %s",
            async_redact_data(data, ["encryption_key"]),
        )
        return self.async_create_entry(
            title=title,
            data=data,
        )
