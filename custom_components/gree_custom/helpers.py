"""Helpers for the Gree integration."""

import logging

from homeassistant.components import network
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .aiogree.api import GreeDiscoveredDevice, discover_gree_devices
from .aiogree.device import GreeDevice
from .const import DEFAULT_DISCOVERY_TIMEOUT

_LOGGER = logging.getLogger(__name__)


async def get_hass_broadcast_addr(hass: HomeAssistant) -> list[str]:
    """Returns the broadcast adresses from HA."""
    broadcast_addresses: list[str] = []

    try:
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
    discovered_devices: list[GreeDiscoveredDevice] = await discover_gree_devices(
        await get_hass_broadcast_addr(hass), DEFAULT_DISCOVERY_TIMEOUT
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
    if not hass.config_entries.async_update_entry(config_entry, data=new_data):
        _LOGGER.debug("Failed to save new IP in config entry data")

    _LOGGER.info(
        "IP for device with mac '%s' updated: %s -> %s",
        device.mac_address_controller,
        previous_ip,
        device.ip,
    )

    return True
