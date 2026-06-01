"""Helpers for the Gree integration."""

from ipaddress import IPv4Address, IPv4Network, ip_address, ip_network
import logging

from homeassistant.components import network
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .aiogree.api import GreeDiscoveredDevice, discover_gree_devices
from .aiogree.device import GreeDevice
from .const import (
    CONF_DISCOVERY_PREFS_KEY,
    CONF_DISCOVERY_PREFS_VERSION,
    CONF_EXTRA_SCAN_HOSTS,
    CONF_EXTRA_SCAN_NETWORKS,
    DEFAULT_DISCOVERY_TIMEOUT,
    MAX_UNICAST_SCAN_HOSTS,
)

_LOGGER = logging.getLogger(__name__)


async def _get_hass_broadcast_addr(hass: HomeAssistant) -> list[str]:
    """Returns the broadcast adresses from HA."""
    broadcast_addresses: list[str] = []

    try:
        # This returns every broadcast address for every enabled network adapter in HA
        # If only the default adapter is enabled, HA only returns 255.255.255.255
        ha_broadcast_addresses: set[
            network.IPv4Address
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
    pref_storage = Store(hass, CONF_DISCOVERY_PREFS_VERSION, CONF_DISCOVERY_PREFS_KEY)
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
    """This will try find the IP of this device controller MAC address and update it."""

    _LOGGER.debug(
        "Trying to find a new IP address for %s", device.mac_address_controller
    )

    previous_ip = device.ip

    # Perform device discovery
    discovery_addresses = await get_discovery_addresses(hass)
    discovered_devices: list[GreeDiscoveredDevice] = await discover_gree_devices(
        discovery_addresses, DEFAULT_DISCOVERY_TIMEOUT
    )

    # Search for a match device
    match_device: GreeDiscoveredDevice | None = next(
        (d for d in discovered_devices if d.mac == device.mac_address_controller),
        None,
    )

    if not match_device:
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
    device.set_ip(match_device.host)

    # Update config entry to save the new IP
    new_data = {**config_entry.data, CONF_HOST: device.ip}
    if not hass.config_entries.async_update_entry(
        config_entry, title=f"Gree System at {device.ip}", data=new_data
    ):
        _LOGGER.debug("Failed to save new IP in config entry data")

    _LOGGER.info(
        "IP for device with mac '%s' updated: %s -> %s",
        device.mac_address_controller,
        previous_ip,
        device.ip,
    )

    return True
