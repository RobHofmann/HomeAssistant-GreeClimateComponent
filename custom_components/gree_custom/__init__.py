"""Gree climate integration init."""

# Standard library imports
import json
import logging
from typing import Any

from aiomqtt.exceptions import MqttConnectError

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_EMAIL,
    CONF_HOST,
    CONF_PORT,
    CONF_REGION,
    CONF_SCAN_INTERVAL,
    CONF_TIMEOUT,
    CONF_TOKEN,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.typing import ConfigType

from .aiogree.cipher import EncryptionVersion
from .aiogree.cloud_api import GreeRegion
from .aiogree.device import GreeDevice
from .aiogree.errors import GreeConnectionError
from .aiogree.transport_mqtt import GreeMqttTransport
from .aiogree.transport_udp import GreeUdpTransport

# Local imports
from .const import (
    CONF_CLOUD,
    CONF_DEV_NAME,
    CONF_DEVICE_CONNECTION,
    CONF_DEVICE_CONNECTION_CLOUD,
    CONF_DEVICE_CONNECTION_LOCAL,
    CONF_DEVICE_OPTIONS,
    CONF_DEVICES,
    CONF_DISABLE_AVAILABLE_CHECK,
    CONF_ENCRYPTION_KEY,
    CONF_ENCRYPTION_VERSION,
    CONF_MAC_CONTROLLER_CLOUD,
    CONF_MAC_CONTROLLER_LOCAL,
    CONF_MAX_ONLINE_ATTEMPTS,
    CONF_PREFER_CLOUD,
    CONF_RESTORE_STATES,
    CONF_UID,
    DEFAULT_CONNECTION_MAX_ATTEMPTS,
    DEFAULT_CONNECTION_TIMEOUT,
    DEFAULT_DEVICE_PORT,
    DEFAULT_DEVICE_UID,
    DEFAULT_DISABLE_AVAILABLE_CHECK,
    DEFAULT_ENCRYPTION_VERSION,
    DEFAULT_PREFER_CLOUD,
    DEFAULT_RESTORE_STATES,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    ENCRYPTION_VERSION_AUTO,
)
from .coordinator import GreeConfigEntry, GreeCoordinator
from .helpers import try_find_new_ip
from .services import async_setup_services

ISSUE_DEVICE_CONNECTION_FAILED = "device_connection_failed"
PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Gree component."""

    async_setup_services(hass)

    # Setup YAML entries
    for gree_config in config.get(DOMAIN, []):
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": "import"},
                data=gree_config,
            )
        )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: GreeConfigEntry) -> bool:
    """Set up Gree from a config entry."""

    _LOGGER.info(
        "Setup entry '%s': %s",
        entry.entry_id,
        entry.title,
    )
    _LOGGER.debug(
        "Setup entry '%s': data=%s",
        entry.entry_id,
        json.dumps(async_redact_data(entry.data, ["encryption_key"])),
    )

    conf = entry.data
    if conf is None or not conf[CONF_DEVICES]:
        _LOGGER.error("Bad config entry, this should not happen")
        return False

    cloud_conf = conf.get(CONF_CLOUD, {})
    device_configs: dict[str, Any] = conf[CONF_DEVICES]
    coordinators: dict[str, GreeCoordinator] = {}
    mqtt_transport: GreeMqttTransport | None = None
    local_transports: dict[str, GreeUdpTransport] = {}

    cleanup_device_connection_issues(hass, entry.entry_id, set(device_configs.keys()))

    for mac, dev_config in device_configs.items():
        connection = dev_config.get(CONF_DEVICE_CONNECTION)
        options = dev_config.get(CONF_DEVICE_OPTIONS)
        if not connection or not options:
            _LOGGER.error("Bad data for device %s", mac)
            continue

        name = options.get(CONF_DEV_NAME)
        _LOGGER.debug("Creating device %s: %s", mac, name)

        connection_local = connection.get(CONF_DEVICE_CONNECTION_LOCAL, {})
        connection_cloud = connection.get(CONF_DEVICE_CONNECTION_CLOUD, {})

        mac_controller_local = connection_local.get(CONF_MAC_CONTROLLER_LOCAL)
        mac_controller_cloud = connection_cloud.get(CONF_MAC_CONTROLLER_CLOUD)

        if not mac_controller_local and not mac_controller_cloud:
            _LOGGER.error("Bad data for device %s. No controller MAC", mac)
            continue

        host = connection_local.get(CONF_HOST)
        port_val = connection_local.get(CONF_PORT)
        port = int(port_val) if port_val else DEFAULT_DEVICE_PORT
        uid = connection.get(CONF_UID, cloud_conf.get(CONF_UID, DEFAULT_DEVICE_UID))
        disable_available_check = connection.get(
            CONF_DISABLE_AVAILABLE_CHECK, DEFAULT_DISABLE_AVAILABLE_CHECK
        )
        max_online_attempts = connection_local.get(
            CONF_MAX_ONLINE_ATTEMPTS, DEFAULT_CONNECTION_MAX_ATTEMPTS
        )
        timeout = connection_local.get(CONF_TIMEOUT, DEFAULT_CONNECTION_TIMEOUT)
        scan_interval = connection.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        prefer_cloud = connection_cloud.get(CONF_PREFER_CLOUD, DEFAULT_PREFER_CLOUD)
        preferred_encryption_key = connection.get(CONF_ENCRYPTION_KEY)
        encryption_version_value = connection_local.get(
            CONF_ENCRYPTION_VERSION, DEFAULT_ENCRYPTION_VERSION
        )
        preferred_local_version = (
            None
            if encryption_version_value == ENCRYPTION_VERSION_AUTO
            else EncryptionVersion(int(encryption_version_value))
        )
        if host and port and mac_controller_local:
            if mac_controller_local not in local_transports:
                local_transports[mac_controller_local] = GreeUdpTransport(
                    ip_addr=host,
                    port=port,
                    max_retries=max_online_attempts,
                    timeout=timeout,
                )

        if mac_controller_cloud and cloud_conf and not mqtt_transport:
            _LOGGER.debug("Creating MQTT transport for %s", cloud_conf[CONF_EMAIL])

            userid: int = cloud_conf.get(CONF_UID, 0)
            token: str = cloud_conf.get(CONF_TOKEN, "")
            region: str = cloud_conf.get(CONF_REGION, "")

            if not userid or not token or not region:
                raise ConfigEntryAuthFailed("no_account_info")

            mqtt_transport = GreeMqttTransport(
                user_id=str(userid), token=token, region=GreeRegion(region)
            )

        device = GreeDevice(
            name=name,
            mac_addr=mac,
            preferred_encryption_key=preferred_encryption_key,
            user_id=uid,
        )

        try:
            await device.bind_with_transport(
                preferred_local_version=preferred_local_version,
                local_controller_mac=mac_controller_local,
                local_transport=None
                if prefer_cloud
                else local_transports.get(mac_controller_local),
                mqtt_controller_mac=mac_controller_cloud,
                mqtt_transport=mqtt_transport,
            )
        except MqttConnectError as err:
            raise ConfigEntryAuthFailed("bad_credentials") from err
        except GreeConnectionError:
            if not await try_find_new_ip(hass, device, entry):
                _LOGGER.exception("Error setting up device %s", mac)
                create_device_connection_issue(hass, entry.entry_id, mac, name)
        except Exception as err:
            _LOGGER.exception("Error setting up device %s", mac)
            create_device_connection_issue(hass, entry.entry_id, mac, name)
            raise ConfigEntryNotReady from err
        else:
            delete_device_connection_issue(hass, entry.entry_id, mac)

            coordinators[mac] = GreeCoordinator(
                hass=hass,
                config_entry=entry,
                scan_interval=scan_interval,
                check_avalilability=not disable_available_check,
                restore_states=options.get(CONF_RESTORE_STATES, DEFAULT_RESTORE_STATES),
                device_config=dev_config,
                device=device,
            )
            await coordinators[device.mac_address].async_config_entry_first_refresh()

            _LOGGER.debug("Setup entry '%s': Bound to device %s", entry.entry_id, mac)

    # Clear MQTT Transport if not used
    if mqtt_transport and not any(
        (c.device.is_bound and isinstance(c.device.transport, GreeMqttTransport))
        for c in coordinators.values()
    ):
        await mqtt_transport.disconnect()

    entry.runtime_data = {}
    entry.runtime_data = coordinators

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: GreeConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Remove a device from a config entry."""

    # Find MAC address for this device (from identifiers)
    mac: str | None = next(
        (
            identifier
            for domain, identifier in device_entry.identifiers
            if domain == DOMAIN
        ),
        None,
    )

    if mac is None:
        return False

    runtime_data: GreeCoordinator | None = config_entry.runtime_data.pop(mac, None)

    if not runtime_data:
        return False

    await runtime_data.async_shutdown()

    data: dict[str, Any] = dict(config_entry.data)
    device_configs: dict[str, Any] = data.get(CONF_DEVICES, {})
    new_device_configs = {k: v for k, v in device_configs.items() if k != mac}

    if len(new_device_configs) == len(device_configs):
        # Nothing to remove
        return False

    data[CONF_DEVICES] = new_device_configs

    device_registry = dr.async_get(hass)
    device_registry.async_remove_device(device_entry.id)

    if new_device_configs:
        # There are still other devices, update the entry
        hass.config_entries.async_update_entry(config_entry, data=data)
    else:
        # No other devices, remove the entry
        await hass.config_entries.async_remove(config_entry.entry_id)

    return True


def _device_issue_id(config_entry_id: str, device_id: str) -> str:
    return f"{ISSUE_DEVICE_CONNECTION_FAILED}_{config_entry_id}_{device_id}"


def create_device_connection_issue(
    hass: HomeAssistant,
    config_entry_id: str,
    device_id: str,
    device_name: str,
) -> None:
    """Create device conenction issue."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        _device_issue_id(config_entry_id, device_id),
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_DEVICE_CONNECTION_FAILED,
        translation_placeholders={
            "device": device_name,
        },
    )


def delete_device_connection_issue(
    hass: HomeAssistant,
    config_entry_id: str,
    device_id: str,
) -> None:
    """Delete device conenction issue."""
    ir.async_delete_issue(
        hass,
        DOMAIN,
        _device_issue_id(config_entry_id, device_id),
    )


def cleanup_device_connection_issues(
    hass: HomeAssistant,
    config_entry_id: str,
    configured_device_ids: set[str],
) -> None:
    """Cleanup all device connection issues for a given ConfigEntry which are not in its configuration."""
    registry = ir.async_get(hass)
    prefix = f"{ISSUE_DEVICE_CONNECTION_FAILED}_{config_entry_id}_"

    for domain, issue_id in registry.issues:
        if domain != DOMAIN or not issue_id.startswith(prefix):
            continue

        device_id = issue_id.removeprefix(prefix)

        if device_id not in configured_device_ids:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
