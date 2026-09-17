"""Helpers for the Gree integration."""

from collections.abc import Mapping
from ipaddress import IPv4Address, IPv4Network, ip_address, ip_network
import logging
from typing import Any

from homeassistant.components import network
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .aiogree.api import GreeDiscoveredDevice, gree_discover_devices
from .aiogree.device import GreeDevice
from .aiogree.transport_udp import GreeUdpTransport
from .const import (
    CONF_DEVICE_CONNECTION,
    CONF_DEVICE_CONNECTION_CLOUD,
    CONF_DEVICE_CONNECTION_LOCAL,
    CONF_DEVICES,
    CONF_DISCOVERY_PREFS_KEY,
    CONF_DISCOVERY_PREFS_VERSION,
    CONF_ENCRYPTION_KEY,
    CONF_EXTRA_SCAN_HOSTS,
    CONF_EXTRA_SCAN_NETWORKS,
    CONF_MAC_CONTROLLER_CLOUD,
    CONF_MAC_CONTROLLER_LOCAL,
    CONF_UID,
    CURRENT_CONF_VERSION,
    DEFAULT_DEVICE_UID,
    DEFAULT_DISCOVERY_TIMEOUT,
    DOMAIN,
    MAX_UNICAST_SCAN_HOSTS,
)

_LOGGER = logging.getLogger(__name__)


async def _get_hass_broadcast_addr(hass: HomeAssistant) -> list[str]:
    """Return the broadcast addresses from HA."""
    broadcast_addresses: list[str] = []

    try:
        # This returns every broadcast address for every enabled network adapter in HA
        # If only the default adapter is enabled, HA only returns 255.255.255.255
        ha_broadcast_addresses: set[
            IPv4Address
        ] = await network.async_get_ipv4_broadcast_addresses(hass)

        ha_broadcast_strings: list[str] = [str(addr) for addr in ha_broadcast_addresses]
        broadcast_addresses.extend(ha_broadcast_strings)
        _LOGGER.debug("Found broadcast addresses from HA: %s", ha_broadcast_strings)

    except Exception:
        _LOGGER.exception("Could not get HA broadcast addresses")

    # Default broadcast addresses to try
    # default_broadcast_addresses = [
    #     "255.255.255.255",  # Limited broadcast
    #     "192.168.255.255",  # /16 broadcast for 192.168.x.x networks
    #     "10.255.255.255",  # /8 broadcast for 10.x.x.x networks
    #     "172.31.255.255",  # /12 broadcast for 172.16-31.x.x networks
    # ]
    # broadcast_addresses.extend(default_broadcast_addresses)
    # NOTE: Try to use the ones from HA only. Uncomment if people report bugs.

    return broadcast_addresses


def _expand_unicast_targets(
    networks: list[str] | None = None,
    hosts: list[str] | None = None,
) -> list[str]:
    """Expand IPv4 CIDRs + individual IPv4s into ordered deduplicated hosts.

    Raises ValueError if any network or total exceeds max_hosts.
    """
    targets: dict[str, None] = {}
    add = targets.setdefault

    for cidr in networks or ():
        net = ip_network(cidr, strict=False)

        if not isinstance(net, IPv4Network):
            raise TypeError(f"IPv6 not supported: {cidr}")

        # /31 => 2 usable, /32 => 1 usable, otherwise subtract net+broadcast
        usable = net.num_addresses if net.prefixlen >= 31 else net.num_addresses - 2

        if usable > MAX_UNICAST_SCAN_HOSTS:
            raise ValueError(
                f"Network {cidr} has {usable} hosts, exceeds limit of {MAX_UNICAST_SCAN_HOSTS}"
            )

        for host in net.hosts():
            add(str(host), None)

            if len(targets) > MAX_UNICAST_SCAN_HOSTS:
                raise ValueError(
                    f"Total unicast targets ({len(targets)}) exceed limit of {MAX_UNICAST_SCAN_HOSTS}"
                )

    for raw_ip in hosts or ():
        addr = ip_address(raw_ip)

        if not isinstance(addr, IPv4Address):
            raise TypeError(f"IPv6 not supported: {raw_ip}")

        add(str(addr), None)

        if len(targets) > MAX_UNICAST_SCAN_HOSTS:
            raise ValueError(
                f"Total unicast targets ({len(targets)}) exceed limit of {MAX_UNICAST_SCAN_HOSTS}"
            )

    _LOGGER.debug("Expanded unicast addresses: %s found", len(targets))
    return list(targets)


async def get_discovery_addresses(
    hass: HomeAssistant,
) -> list[str]:
    """Gathers a list of broadcast and unicast addresses."""

    addresses: list[str] = []

    # Collect HA broadcast addresses
    broadcast_addresses = await _get_hass_broadcast_addr(hass)
    addresses.extend(broadcast_addresses)

    # Collect unicast addresses from HASS prefs
    pref_storage: Store = Store(
        hass, CONF_DISCOVERY_PREFS_VERSION, CONF_DISCOVERY_PREFS_KEY
    )
    prefs = await pref_storage.async_load() or {}

    extra_networks: list[str] = prefs.get(CONF_EXTRA_SCAN_NETWORKS, [])
    extra_hosts: list[str] = prefs.get(CONF_EXTRA_SCAN_HOSTS, [])
    unicast_addresses = _expand_unicast_targets(extra_networks, extra_hosts)
    addresses.extend(unicast_addresses)

    return addresses


async def try_find_new_ip(
    hass: HomeAssistant,
    device: GreeDevice,
    config_entry: ConfigEntry,
) -> bool:
    """Try find the IP of this device controller MAC address and update it."""

    _LOGGER.debug(
        "Trying to find a new IP address for %s", device.mac_address_controller
    )

    if not device.transport or not isinstance(device.transport, GreeUdpTransport):
        _LOGGER.error("Can't find the IP of a device that is not local")
        return False

    previous_ip = device.transport.ip_addr

    # Perform device discovery
    discovery_addresses = await get_discovery_addresses(hass)
    discovered_devices: list[GreeDiscoveredDevice] = await gree_discover_devices(
        cloud_api=None,
        broadcast_addresses=discovery_addresses,
        timeout=DEFAULT_DISCOVERY_TIMEOUT,
    )

    # Search for a match device
    match_device: GreeDiscoveredDevice | None = next(
        (d for d in discovered_devices if d.mac == device.mac_address_controller),
        None,
    )

    if not match_device or not match_device.host:
        _LOGGER.debug(
            "No device with mac '%s' found in the discovered devices",
            device.mac_address_controller,
        )
        return False

    if previous_ip == match_device.host:
        _LOGGER.debug(
            "IP for device with mac '%s' is already correct",
            device.mac_address_controller,
        )
        return False

    # Update the device IP
    # await device.unbind_device()
    await device.transport.set_ip(match_device.host)

    _LOGGER.info(
        "IP for device with mac '%s' updated: %s -> %s",
        device.mac_address_controller,
        previous_ip,
        device.transport.ip_addr,
    )

    # Update config entry to save the new IP
    try:
        new_data = config_entry.data
        new_data[CONF_DEVICES][device.mac_address][CONF_DEVICE_CONNECTION][
            CONF_DEVICE_CONNECTION_LOCAL
        ][CONF_HOST] = device.transport.ip_addr

        if not hass.config_entries.async_update_entry(config_entry, data=new_data):
            _LOGGER.debug("Failed to save new IP in config entry data")
        else:
            _LOGGER.debug("Config entry updated with new IP")
    except KeyError:
        _LOGGER.exception("Config entry data does not contain the required keys")

    return True


def create_discovered_from_config(mac: str, conf: dict) -> GreeDiscoveredDevice:
    """Return a GreeDiscoveredDevice based on config data."""
    conn = conf.get(CONF_DEVICE_CONNECTION, {})
    local = conn.get(CONF_DEVICE_CONNECTION_LOCAL, {})
    cloud = conn.get(CONF_DEVICE_CONNECTION_CLOUD, {})
    return GreeDiscoveredDevice(
        mac=mac,
        mac_controller_local=local.get(CONF_MAC_CONTROLLER_LOCAL, ""),
        mac_controller_mqtt=cloud.get(CONF_MAC_CONTROLLER_CLOUD, ""),
        user_id=conn.get(CONF_UID, DEFAULT_DEVICE_UID),
        key=conn.get(CONF_ENCRYPTION_KEY, ""),
        host=local.get(CONF_HOST, ""),
        port=local.get(CONF_PORT, ""),
    )


def get_entity_ids_from_unique_ids(
    hass: HomeAssistant,
    entity_domain: str,
    unique_ids: list[str],
) -> list[str]:
    """Resolve a list of unique_ids to their entity_ids in the given domain/platform.

    Entities that aren't registered yet (unique_id not found) are skipped.
    """
    ent_reg = er.async_get(hass)

    entity_ids = [
        ent_reg.async_get_entity_id(entity_domain, DOMAIN, unique_id)
        for unique_id in unique_ids
    ]

    return [entity_id for entity_id in entity_ids if entity_id is not None]


def get_config_entries(
    hass: HomeAssistant,
    ignore_entries: list[str] | None = None,
    match_entries: list[str] | None = None,
) -> list[ConfigEntry]:
    """Get this integration config entries with filters."""
    entries: list[ConfigEntry] = hass.config_entries.async_entries(DOMAIN)

    return [
        entry
        for entry in entries
        if entry.version >= CURRENT_CONF_VERSION
        and (ignore_entries is None or entry.unique_id not in ignore_entries)
        and (match_entries is None or entry.unique_id in match_entries)
    ]


def get_entry_matching_mac(hass: HomeAssistant, target_mac: str) -> ConfigEntry | None:
    """Get a config entry that has the target_mac as a configured device."""
    entries: list[ConfigEntry] = get_config_entries(hass)

    matches: list[ConfigEntry] = [
        e for e in entries if target_mac in e.data.get(CONF_DEVICES, {})
    ]

    if len(matches) > 1:
        _LOGGER.error("A device must exist in only one entry")
    elif len(matches) == 1:
        return matches[0]

    return None


def get_configured_macs_in_entries(
    hass: HomeAssistant,
    ignore_entries: list[str] | None = None,
    match_entries: list[str] | None = None,
) -> Mapping[str, ConfigEntry]:
    """Get configured device macs and their respective config entry."""
    entries: list[ConfigEntry] = get_config_entries(
        hass, ignore_entries=ignore_entries, match_entries=match_entries
    )

    configured_macs: dict[str, ConfigEntry] = {}

    for e in entries:
        conf_devices: dict[str, Any] = e.data.get(CONF_DEVICES, {})
        for mac in conf_devices:
            configured_macs[mac] = e

    return configured_macs


def get_subdevices_mac_matching_controller(
    hass: HomeAssistant, controller_mac: str
) -> tuple[ConfigEntry, set[str]] | None:
    """Get sub-device macs that match a given controller and their respective config entry."""
    matched_entry: ConfigEntry | None = None
    matched_devices: set[str] = set()

    for entry in get_config_entries(hass):
        conf_devices: dict[str, Any] = entry.data.get(CONF_DEVICES, {})

        for mac, device in conf_devices.items():
            controller_local = (
                device.get(CONF_DEVICE_CONNECTION, {})
                .get(CONF_DEVICE_CONNECTION_LOCAL, {})
                .get(CONF_MAC_CONTROLLER_LOCAL)
            )

            if controller_mac != controller_local:
                continue

            if matched_entry is not None and matched_entry is not entry:
                _LOGGER.error("A device must exist in only one entry")
                return None

            matched_entry = entry
            matched_devices.add(mac)

    if matched_entry is None:
        return None

    return matched_entry, matched_devices
