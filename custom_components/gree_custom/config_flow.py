"""Config flow to configure the Gree integration."""

from collections.abc import Mapping
import copy
from ipaddress import IPv4Address, IPv4Network, ip_address, ip_network
import logging
from typing import TYPE_CHECKING, Any, override

from aiomqtt import MqttError

if TYPE_CHECKING:
    import probatio
else:
    try:
        import probatio
    except ImportError:
        import voluptuous as probatio

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import (
    SOURCE_REAUTH,
    SOURCE_RECONFIGURE,
    SOURCE_USER,
    ConfigEntryState,
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
    CONF_TOKEN,
)
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from homeassistant.helpers.storage import Store

from . import create_yaml_import_issue, delete_yaml_import_issue
from .aiogree.api import (
    GreeDiscoveredDevice,
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
from .config_schema import (
    SETUP_SCHEMA,
    setup_cloud_schema,
    setup_device_connection_options_schema,
    setup_device_options_schema,
    setup_local_schema,
    setup_picker_schema,
)
from .const import (
    CONF_ALL_DEVICE_CONNECTIONS,
    CONF_ALL_DEVICE_OPTIONS,
    CONF_CLOUD,
    CONF_DEVICE_CONNECTION,
    CONF_DEVICE_CONNECTION_CLOUD,
    CONF_DEVICE_CONNECTION_LOCAL,
    CONF_DEVICE_OPTIONS,
    CONF_DEVICES,
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
    CONF_PREFER_CLOUD,
    CONF_SWING_HORIZONTAL_MODES,
    CONF_SWING_MODES,
    CONF_UID,
    CONFENTRY_ID_LOCAL_ONLY,
    CURRENT_CONF_VERSION,
    DATA_YAML_UNIQUE_IDS,
    DEFAULT_DEVICE_UID,
    DEFAULT_DISCOVERY_RETRIES,
    DEFAULT_DISCOVERY_TIMEOUT,
    DEFAULT_ENCRYPTION_VERSION,
    DEFAULT_PREFER_CLOUD,
    DOMAIN,
    ENCRYPTION_VERSION_AUTO,
    MAX_UNICAST_SCAN_HOSTS,
)
from .coordinator import GreeConfigEntry
from .helpers import (
    async_disconnect_transports,
    create_discovered_from_config,
    create_mqtt_transport,
    get_config_entries,
    get_configured_macs_in_entries,
    get_discovery_addresses,
    get_entry_matching_mac,
)
from .migration import async_setup_from_flow

_LOGGER = logging.getLogger(__name__)


def _matches_cloud_account(
    stored: Mapping[str, Any] | None, cloud_conf: Mapping[str, Any]
) -> bool:
    """Tell if a stored cloud block is the same account as a YAML cloud block."""
    if not stored:
        return False

    return all(
        stored.get(key) == cloud_conf.get(key)
        for key in (CONF_EMAIL, CONF_REGION, CONF_PASSWORD)
    )


# Local settings of a controller. Every device behind it (VRF) uses the same values.
CONTROLLER_LOCAL_KEYS = (CONF_HOST, CONF_PORT, CONF_ENCRYPTION_VERSION)


def _bind_settings(connection: Mapping[str, Any]) -> tuple:
    """Return the connection settings that decide how a device binds.

    The poll interval, the availability check, the timeout and the retries
    do not change the bind, so they are left out.
    """
    local = connection.get(CONF_DEVICE_CONNECTION_LOCAL) or {}
    cloud = connection.get(CONF_DEVICE_CONNECTION_CLOUD) or {}

    return (
        connection.get(CONF_ENCRYPTION_KEY),
        connection.get(CONF_UID),
        local.get(CONF_MAC_CONTROLLER_LOCAL),
        local.get(CONF_HOST),
        local.get(CONF_PORT),
        local.get(CONF_ENCRYPTION_VERSION),
        cloud.get(CONF_PREFER_CLOUD),
        cloud.get(CONF_MAC_CONTROLLER_CLOUD),
    )


def _adds_connection(d: GreeDiscoveredDevice, dev_conf: Mapping[str, Any]) -> bool:
    """Tell if discovery found a connection that a configured device lacks.

    That is a local host for a device without one, or a cloud controller for
    a device without one.
    """
    connection = dev_conf.get(CONF_DEVICE_CONNECTION, {})
    local = connection.get(CONF_DEVICE_CONNECTION_LOCAL) or {}
    cloud = connection.get(CONF_DEVICE_CONNECTION_CLOUD) or {}

    return bool(
        (d.host and not local.get(CONF_HOST))
        or (d.mac_controller_mqtt and not cloud.get(CONF_MAC_CONTROLLER_CLOUD))
    )


def _apply_discovery_info(d: GreeDiscoveredDevice, connection: dict[str, Any]) -> None:
    """Put the host and controller MACs that discovery found in a connection."""
    if d.host:
        local = dict(connection.get(CONF_DEVICE_CONNECTION_LOCAL) or {})
        local[CONF_HOST] = d.host
        if d.mac_controller_local:
            local[CONF_MAC_CONTROLLER_LOCAL] = d.mac_controller_local
        connection[CONF_DEVICE_CONNECTION_LOCAL] = local

    if d.mac_controller_mqtt:
        cloud = dict(connection.get(CONF_DEVICE_CONNECTION_CLOUD) or {})
        cloud[CONF_MAC_CONTROLLER_CLOUD] = d.mac_controller_mqtt
        connection[CONF_DEVICE_CONNECTION_CLOUD] = cloud


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

        self._config_data: dict[str, Any] = {}
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
        self._options_by_model: dict[str, Any] = {}

        # Reconfigure: the device configs to write at the end, keyed by MAC
        self._pending_devices: dict[str, Any] | None = None

    async def async_step_import(self, import_config: dict) -> ConfigFlowResult:
        """Handle import from configuration.yaml."""

        cloud_conf: dict[str, Any] | None = import_config.get(CONF_CLOUD)
        devices: dict[str, Any] = dict(import_config[CONF_DEVICES])

        item_id = cloud_conf[CONF_EMAIL] if cloud_conf else CONFENTRY_ID_LOCAL_ONLY

        stored_cloud: dict[str, Any] | None = None
        if not cloud_conf:
            unique_id = CONFENTRY_ID_LOCAL_ONLY
        else:
            known_entry = next(
                (
                    entry
                    for entry in get_config_entries(self.hass)
                    if _matches_cloud_account(entry.data.get(CONF_CLOUD), cloud_conf)
                    and entry.unique_id
                ),
                None,
            )

            if known_entry and known_entry.unique_id:
                # Reuse the stored token so there is no login on every restart
                unique_id = known_entry.unique_id
                stored_cloud = dict(known_entry.data[CONF_CLOUD])
            else:
                cloud_api = GreeCloudApi(
                    region=GreeRegion(cloud_conf[CONF_REGION]),
                    username=cloud_conf[CONF_EMAIL],
                    password=cloud_conf[CONF_PASSWORD],
                )
                try:
                    credentials = await cloud_api.login()
                except Exception as err:  # noqa: BLE001
                    return self._abort_yaml_import(item_id, err)
                finally:
                    await cloud_api.close()

                unique_id = str(credentials.user_id)
                stored_cloud = {
                    **cloud_conf,
                    CONF_TOKEN: credentials.token,
                    CONF_UID: credentials.user_id,
                }

        # Reconfigure refuses entries the YAML manages. Kept in memory only,
        # so an entry is editable again after its YAML block is gone.
        self.hass.data.setdefault(DATA_YAML_UNIQUE_IDS, set()).add(unique_id)

        await self.async_set_unique_id(unique_id)

        self._drop_devices_of_other_entries(devices, unique_id)

        if not devices:
            create_yaml_import_issue(
                self.hass,
                item_id,
                "every device is already configured in another config entry",
            )
            return self.async_abort(reason="import_failed")

        delete_yaml_import_issue(self.hass, item_id)

        data = {
            CONF_CLOUD: stored_cloud,
            CONF_DEVICES: devices,
        }
        cloud_data: dict[str, Any] = stored_cloud or {}
        title = (
            f"Gree Account: {cloud_data.get(CONF_UID)} ({cloud_data.get(CONF_EMAIL)})"
            if cloud_data.get(CONF_EMAIL)
            else "Local-only Devices"
        )

        entry = self.hass.config_entries.async_entry_for_domain_unique_id(
            DOMAIN, unique_id
        )
        if entry:
            # remove devices that are no longer provided by the YAML
            # they will be re-added if they exist in another entry
            device_registry = dr.async_get(self.hass)
            for mac in entry.data.get(CONF_DEVICES, {}):
                if mac not in devices:
                    dev = device_registry.async_get_device(identifiers={(DOMAIN, mac)})
                    if dev:
                        device_registry.async_remove_device(dev.id)

            return self.async_update_reload_and_abort(
                entry,
                title=title,
                data=data,
                reason="reconfigure_successful",
                reload_even_if_entry_is_unchanged=False,
            )

        _LOGGER.debug(
            "YAML import: new entry with config: %s",
            async_redact_data(data, ["encryption_key", "password", "token"]),
        )
        return self.async_create_entry(
            title=title,
            data=data,
        )

    def _drop_devices_of_other_entries(
        self, devices: dict[str, Any], unique_id: str
    ) -> None:
        """Drop the devices that already belong to another config entry."""
        other_macs = get_configured_macs_in_entries(
            self.hass, ignore_entries=[unique_id]
        )

        for mac in list(devices):
            if mac in other_macs:
                _LOGGER.error(
                    "YAML import: device %s is already configured in entry '%s'"
                    " and is skipped",
                    mac,
                    other_macs[mac].title,
                )
                devices.pop(mac)

    def _abort_yaml_import(self, item_id: str, err: Exception) -> ConfigFlowResult:
        """Log a failed cloud login, raise a repair issue and stop the import."""
        _LOGGER.error("YAML import: cloud login failed for %s: %s", item_id, err)
        create_yaml_import_issue(self.hass, item_id, f"cloud login failed: {err}")
        return self.async_abort(reason="import_failed")

    async def async_step_migrate(self, migrate_data: dict) -> ConfigFlowResult:
        """Add the devices of 4.x config entries to the local-only entry.

        Started by `migration.py` when no YAML block manages the local devices.
        Unlike the YAML import, this only adds devices and never removes one.
        """
        devices: dict[str, Any] = dict(migrate_data[CONF_DEVICES])

        await self.async_set_unique_id(CONFENTRY_ID_LOCAL_ONLY)

        other_macs = get_configured_macs_in_entries(
            self.hass, ignore_entries=[CONFENTRY_ID_LOCAL_ONLY]
        )
        for mac in [m for m in devices if m in other_macs]:
            _LOGGER.info(
                "Migration from 4.x: device %s is already in entry '%s'",
                mac,
                other_macs[mac].title,
            )
            devices.pop(mac)

        entry = self.hass.config_entries.async_entry_for_domain_unique_id(
            DOMAIN, CONFENTRY_ID_LOCAL_ONLY
        )
        known: dict[str, Any] = dict(entry.data.get(CONF_DEVICES, {})) if entry else {}
        new_devices = {m: d for m, d in devices.items() if m not in known}

        if not new_devices:
            return self.async_abort(reason="already_configured")

        if entry:
            return self.async_update_reload_and_abort(
                entry,
                data={**entry.data, CONF_DEVICES: {**known, **new_devices}},
                reason="reconfigure_successful",
            )

        return self.async_create_entry(
            title="Local-only Devices",
            data={CONF_CLOUD: None, CONF_DEVICES: new_devices},
        )

    @override
    async def async_step_dhcp(
        self, discovery_info: DhcpServiceInfo
    ) -> ConfigFlowResult:
        """Handle discovery via dhcp."""

        _LOGGER.debug("Gree device discovered from dhcp: %s", discovery_info)

        if await async_setup_from_flow(self.hass):
            return self.async_abort(reason="legacy_migration_started")

        # Check what's under that device: Main device and sub-devices
        # If it does not respond locally, there's no use of this information
        discover = await gree_discover_device_local(
            discovery_info.ip,
            DEFAULT_DISCOVERY_TIMEOUT,
            DEFAULT_DISCOVERY_RETRIES,
            DEFAULT_DEVICE_UID,
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

                # update data. Behind a gateway the DHCP MAC is the gateway,
                # and the configured devices are its sub-units, so use the MAC
                # of the discovered device. Copy deep, so the entry sees a change.
                new_data = copy.deepcopy(dict(entry_match.data))
                new_data[CONF_DEVICES][d.mac][CONF_DEVICE_CONNECTION][
                    CONF_DEVICE_CONNECTION_LOCAL
                ][CONF_HOST] = discovery_info.ip
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
        if user_input is None and await async_setup_from_flow(self.hass):
            return self.async_abort(reason="legacy_migration_started")

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
        """Show the reconfigure menu. Every reconfigure step returns here.

        The changes collect in `_pending_devices`. Only `finish` writes them
        to the entry, with one reload.
        """
        reconfigure_entry = self._get_reconfigure_entry()

        if self._pending_devices is None:
            _LOGGER.debug("Reconfiguring: %s", reconfigure_entry.title)

            # The YAML puts its own values back at the next start
            if reconfigure_entry.unique_id in self.hass.data.get(
                DATA_YAML_UNIQUE_IDS, set()
            ):
                return self.async_abort(reason="yaml_managed")

            # Copy deep, so the edits do not change the live entry data
            self._pending_devices = copy.deepcopy(
                dict(reconfigure_entry.data.get(CONF_DEVICES, {}))
            )
            # Keep the account and its token when no step logs in again
            if cloud_conf := reconfigure_entry.data.get(CONF_CLOUD):
                self._config_data[CONF_CLOUD] = dict(cloud_conf)

            if reconfigure_entry.unique_id == CONFENTRY_ID_LOCAL_ONLY:
                await self.async_set_unique_id(CONFENTRY_ID_LOCAL_ONLY)

        menu_options = ["rediscover", "finish"]
        if self._pending_devices:
            menu_options = ["edit_device", "rediscover", "remove_devices", "finish"]

        return self.async_show_menu(
            step_id="reconfigure",
            menu_options=menu_options,
            description_placeholders={"device_cnt": str(len(self._pending_devices))},
        )

    def _pending_as_discovered(self) -> dict[str, GreeDiscoveredDevice]:
        """Return the pending devices in the shape the device forms use."""
        pending: dict[str, Any] = self._pending_devices or {}
        devices: dict[str, GreeDiscoveredDevice] = {}

        for mac, dev_conf in pending.items():
            devices[mac] = create_discovered_from_config(mac, dev_conf)
            devices[mac].name = dev_conf.get(CONF_DEVICE_OPTIONS, {}).get(CONF_NAME, "")

        return devices

    async def async_step_edit_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick one configured device and run its connection and option forms."""
        devices = self._pending_as_discovered()
        if not devices:
            return await self.async_step_reconfigure()

        if user_input is not None:
            self._selected_devices = [devices[user_input[CONF_DEVICES]]]
            self._current_setup_device_index = 0
            return await self.async_step_connection_options()

        return self.async_show_form(
            step_id="edit_device",
            data_schema=setup_picker_schema(
                next(iter(devices)), devices, multiple=False
            ),
        )

    async def async_step_remove_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick configured devices to remove from the entry."""
        devices = self._pending_as_discovered()

        if user_input is not None:
            pending: dict[str, Any] = self._pending_devices or {}
            for mac in user_input.get(CONF_DEVICES, []):
                pending.pop(mac, None)
            return await self.async_step_reconfigure()

        return self.async_show_form(
            step_id="remove_devices",
            data_schema=setup_picker_schema([], devices),
        )

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Write the reconfigured entry and reload it once."""
        return await self._async_finish()

    async def async_step_rediscover(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Run discovery again for the entry that is reconfigured."""
        self._discovered_devices_cloud = {}
        self._discovered_devices_local = {}
        self._current_setup_method_index = 0

        # The local-only entry only has the local method
        if self._get_reconfigure_entry().unique_id == CONFENTRY_ID_LOCAL_ONLY:
            self._selected_setup_methods = ["local"]
            return await self._setup_next_setup_method()

        # If entry has cloud, ask if user wants to add local
        # A user cannot remove cloud from an entry, because the entry is keyed by the cloud account
        # For that, remove the entry and add to the local-only entry
        # Cloud discovery needs a login: the stored token only works for MQTT

        if user_input is not None:
            self._selected_setup_methods = ["cloud"]
            if user_input.get("include_local", False):
                self._selected_setup_methods.append("local")
            return await self._setup_next_setup_method()

        # Pre-select the include local option if any devices have local configurations
        has_local = any(
            d.get(CONF_DEVICE_CONNECTION, {})
            .get(CONF_DEVICE_CONNECTION_LOCAL, {})
            .get(CONF_HOST)
            is not None
            for d in (self._pending_devices or {}).values()
        )

        return self.async_show_form(
            step_id="rediscover",
            data_schema=probatio.Schema(
                {
                    probatio.Required(
                        "include_local",
                        default=has_local,
                    ): cv.boolean
                }
            ),
        )

    def _store_pending_devices(self, device_configs: dict[str, Any]) -> None:
        """Put the configs from the device forms in the pending devices.

        When an edit changes the local settings of a controller, the other
        devices behind that controller get the same values.
        """
        if self._pending_devices is None:
            return

        for mac, dev_conf in device_configs.items():
            previous = self._pending_devices.get(mac)
            self._pending_devices[mac] = dev_conf

            if previous is None:
                continue

            old_local = (
                previous.get(CONF_DEVICE_CONNECTION, {}).get(
                    CONF_DEVICE_CONNECTION_LOCAL
                )
                or {}
            )
            new_local = (
                dev_conf[CONF_DEVICE_CONNECTION].get(CONF_DEVICE_CONNECTION_LOCAL) or {}
            )
            controller = new_local.get(CONF_MAC_CONTROLLER_LOCAL)
            changed = {
                key: new_local[key]
                for key in CONTROLLER_LOCAL_KEYS
                if key in new_local and new_local[key] != old_local.get(key)
            }
            if not controller or not changed:
                continue

            for other_mac, other_conf in self._pending_devices.items():
                if other_mac == mac or other_mac in device_configs:
                    continue

                other_local = other_conf.get(CONF_DEVICE_CONNECTION, {}).get(
                    CONF_DEVICE_CONNECTION_LOCAL
                )
                if other_local and (
                    other_local.get(CONF_MAC_CONTROLLER_LOCAL) == controller
                ):
                    _LOGGER.debug(
                        "Copying the controller settings of %s to %s",
                        mac,
                        other_mac,
                    )
                    other_local.update(changed)

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

                # Close the connection of an earlier attempt or edit first
                await async_disconnect_transports([self._mqtt_transport])

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
            data_schema=setup_cloud_schema(defaults),
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
                    max_retries=DEFAULT_DISCOVERY_RETRIES,
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
            data_schema=setup_local_schema(
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
        """Let users pick the devices to set up."""
        errors: dict[str, str] = {}

        if user_input is not None:
            selected: list[str] = user_input.get(CONF_DEVICES, [])

            if selected:
                self._selected_devices = [
                    self._discovered_devices[key] for key in selected
                ]
                self._current_setup_device_index = 0
                return await self.async_step_connection_options()

            # Reconfigure: picking nothing adds nothing
            if self.source == SOURCE_RECONFIGURE:
                return await self.async_step_reconfigure()

            errors[CONF_DEVICES] = "no_devices_selected"

        # Reconfigure only lists what adds something to the entry
        if self.source == SOURCE_RECONFIGURE:
            self._keep_new_rediscovered_devices()
            if not self._discovered_devices:
                return await self.async_step_no_new_devices()

        if not self._discovered_devices:
            return self.async_abort(reason="no_devices_to_add")

        return self.async_show_form(
            step_id="device_picker",
            data_schema=setup_picker_schema(
                list(self._discovered_devices), self._discovered_devices
            ),
            description_placeholders={
                "devices_found": str(len(self._discovered_devices))
            },
            errors=errors,
        )

    def _keep_new_rediscovered_devices(self) -> None:
        """Keep only the rediscovered devices that add something to the entry.

        A device is new when it is not in the pending devices, or when
        discovery found a connection it lacks (see `_adds_connection`). The
        other configured devices only get their host and controller MACs
        refreshed, like the DHCP step, without a form and without a bind.
        Rediscover never removes a device.
        """
        pending: dict[str, Any] = self._pending_devices or {}
        new_devices: dict[str, GreeDiscoveredDevice] = {}

        for mac, d in self._discovered_devices.items():
            dev_conf = pending.get(mac)
            if dev_conf is None or _adds_connection(d, dev_conf):
                new_devices[mac] = d
            else:
                _apply_discovery_info(
                    d, dev_conf.setdefault(CONF_DEVICE_CONNECTION, {})
                )

        self._discovered_devices = new_devices

    async def async_step_no_new_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Tell that rediscover found nothing new, then go back to the menu.

        An abort would drop the pending changes, and a menu cannot show an
        error, so this is a form without fields.
        """
        if user_input is not None:
            return await self.async_step_reconfigure()

        return self.async_show_form(step_id="no_new_devices")

    def _get_running_device(
        self, mac: str, user_input: Mapping[str, Any]
    ) -> GreeDevice | None:
        """Return the bound device of the loaded entry, when a new bind is not needed.

        Only during reconfigure, and only when the submitted settings bind the
        same way as the stored ones. This saves a bind, and for a cloud
        device it needs no cloud login.
        """
        if self.source != SOURCE_RECONFIGURE:
            return None

        entry = self._get_reconfigure_entry()
        stored = (
            entry.data.get(CONF_DEVICES, {}).get(mac, {}).get(CONF_DEVICE_CONNECTION)
        )
        if not stored or _bind_settings(stored) != _bind_settings(user_input):
            return None

        if entry.state is not ConfigEntryState.LOADED:
            return None

        coordinator = entry.runtime_data.get(mac)
        if coordinator is None or not coordinator.device.is_bound:
            return None

        _LOGGER.debug("Device %s is unchanged, using its running bind", mac)
        return coordinator.device

    async def _bind_device(
        self,
        d: GreeDiscoveredDevice,
        user_input: Mapping[str, Any],
        mac_local_controller: str,
        mac_mqtt_controller: str,
    ) -> GreeDevice:
        """Bind a device with the submitted connection settings."""
        local = user_input.get(CONF_DEVICE_CONNECTION_LOCAL, {})
        cloud = user_input.get(CONF_DEVICE_CONNECTION_CLOUD, {})
        device = GreeDevice(
            name=d.name,
            mac_addr=d.mac,
            preferred_encryption_key=user_input.get(CONF_ENCRYPTION_KEY, d.key),
            user_id=user_input.get(CONF_UID, d.user_id),
        )

        encryption_version_value = local.get(
            CONF_ENCRYPTION_VERSION, DEFAULT_ENCRYPTION_VERSION
        )

        ip = local.get(CONF_HOST, "")
        port = local.get(CONF_PORT, "")

        local_transport = self._local_transports.get(
            mac_local_controller, GreeUdpTransport(ip_addr=ip, port=port)
        )

        # Reconfigure without a cloud login uses the stored token
        if (
            self.source == SOURCE_RECONFIGURE
            and mac_mqtt_controller
            and not self._mqtt_transport
        ):
            self._mqtt_transport = create_mqtt_transport(
                self._config_data.get(CONF_CLOUD) or {}
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

        return device

    async def async_step_connection_options(  # noqa: C901
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Iterate through the selected devices to configure their connection options."""
        errors: dict[str, str] = {}
        d = self._selected_devices[self._current_setup_device_index]

        if user_input is not None:
            local = user_input.get(CONF_DEVICE_CONNECTION_LOCAL, {})
            cloud = user_input.get(CONF_DEVICE_CONNECTION_CLOUD, {})

            # Ensure the device can bind
            try:
                mac_local_controller = local.get(
                    CONF_MAC_CONTROLLER_LOCAL, d.mac_controller_local
                )
                mac_mqtt_controller = cloud.get(
                    CONF_MAC_CONTROLLER_CLOUD, d.mac_controller_mqtt
                )

                # An unchanged device during reconfigure keeps its running bind
                device = self._get_running_device(d.mac, user_input)
                if device is None:
                    device = await self._bind_device(
                        d, user_input, mac_local_controller, mac_mqtt_controller
                    )

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

        # During reconfigure inject previous connection options, plus what
        # rediscover found, so the user only confirms a new connection
        if not default and self.source == SOURCE_RECONFIGURE:
            pending_connection = (
                (self._pending_devices or {})
                .get(d.mac, {})
                .get(CONF_DEVICE_CONNECTION, None)
            )
            if pending_connection:
                default = copy.deepcopy(pending_connection)
                _apply_discovery_info(d, default)

        defaults = (
            default
            or self._connections_by_controller.get(d.mac_controller_local)
            or self._connections_by_controller.get(d.mac_controller_mqtt)
        )

        return self.async_show_form(
            step_id="connection_options",
            data_schema=setup_device_connection_options_schema(d, defaults),
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

            if device.device_model_id:
                self._options_by_model[device.device_model_id] = user_input

            if self._current_setup_device_index >= len(self._selected_devices) - 1:
                self._current_setup_device_index = 0

                # Reconfigure collects the changes and writes them on finish
                if self.source == SOURCE_RECONFIGURE:
                    self._store_pending_devices(self._collect_device_configs())
                    return await self.async_step_reconfigure()

                return await self._async_finish()

            self._current_setup_device_index += 1
            return await self.async_step_device_options()

        default: dict[str, Any] | None = user_input

        # During user setup find if the device is already configured
        if not default and self.source == SOURCE_USER:
            found_device_entry = get_entry_matching_mac(self.hass, d.mac)
            if found_device_entry:
                default = (
                    found_device_entry.data.get(CONF_DEVICES, {})
                    .get(d.mac, {})
                    .get(CONF_DEVICE_OPTIONS, None)
                )
            elif model_options := self._options_by_model.get(device.device_model_id):
                default = {
                    key: model_options[key]
                    for key in (
                        CONF_HVAC_MODES,
                        CONF_FAN_MODES,
                        CONF_SWING_MODES,
                        CONF_SWING_HORIZONTAL_MODES,
                        CONF_FEATURES,
                    )
                    if key in model_options
                }

        # During reconfigure inject previous device options
        if not default and self.source == SOURCE_RECONFIGURE:
            default = (
                (self._pending_devices or {})
                .get(d.mac, {})
                .get(CONF_DEVICE_OPTIONS, {})
            )

        data_schema = setup_device_options_schema(
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

    def _collect_device_configs(self) -> dict[str, Any]:
        """Return the configs of the devices that went through the device forms."""
        device_configs: dict[str, Any] = {}
        for d in self._selected_devices:
            mac = str(self._devices[d.mac].mac_address)
            device_configs[mac] = {
                CONF_DEVICE_CONNECTION: self._config_data[CONF_ALL_DEVICE_CONNECTIONS][
                    d.mac
                ],
                CONF_DEVICE_OPTIONS: self._config_data[CONF_ALL_DEVICE_OPTIONS][d.mac],
            }

        return device_configs

    async def _async_finish(self) -> ConfigFlowResult:  # noqa: C901
        """Create or update the entry."""

        # Close the flow connections before the entry opens its own
        await self._async_close_transports()

        if self.source == SOURCE_REAUTH:
            cloud_conf: dict[str, str] = self._config_data.get(CONF_CLOUD, {})
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(),
                title=f"Gree Account: {cloud_conf.get(CONF_UID)} ({cloud_conf.get(CONF_EMAIL)})",
                data_updates={CONF_CLOUD: cloud_conf},
            )

        device_registry = dr.async_get(self.hass)

        # Reconfigure writes the devices it collected in the menu steps
        device_configs: dict[str, Any] = (
            dict(self._pending_devices)
            if self.source == SOURCE_RECONFIGURE and self._pending_devices is not None
            else self._collect_device_configs()
        )

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

        cloud_conf: dict[str, str] = self._config_data.get(CONF_CLOUD, {})
        title = (
            f"Gree Account: {cloud_conf.get(CONF_UID)} ({cloud_conf.get(CONF_EMAIL)})"
            if cloud_conf.get(CONF_EMAIL)
            else "Local-only Devices"
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

    async def _async_close_transports(self) -> None:
        """Disconnect the transports this flow opened.

        The devices bound in the flow are throwaway, so they are not unbound
        first. A running device from `_get_running_device()` uses the entry
        transports, which are never in these fields.
        """
        transports = [self._mqtt_transport, *self._local_transports.values()]
        self._mqtt_transport = None
        self._local_transports = {}

        await async_disconnect_transports(transports)

    @callback
    @override
    def async_remove(self) -> None:
        """Close the flow transports when the flow ends or is closed.

        Home Assistant calls this when a step creates an entry or aborts,
        and when the user closes the flow.
        """
        if self._mqtt_transport or self._local_transports:
            self.hass.async_create_task(self._async_close_transports())
