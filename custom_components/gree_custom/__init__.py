"""Gree climate integration init."""

from __future__ import annotations

# Standard library imports
import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.typing import ConfigType

from .aiogree.const import (
    DEFAULT_CONNECTION_MAX_ATTEMPTS,
    DEFAULT_DEVICE_PORT,
    DEFAULT_DEVICE_UID,
)
from .aiogree.device import GreeDevice, GreeDeviceNotBoundError

# Local imports
from .const import (
    CONF_ADVANCED,
    CONF_DEV_NAME,
    CONF_DEVICES,
    CONF_ENCRYPTION_KEY,
    CONF_ENCRYPTION_VERSION,
    CONF_MAX_ONLINE_ATTEMPTS,
    CONF_UID,
    DEFAULT_ENCRYPTION_VERSION,
    DOMAIN,
)

# Home Assistant imports
from .coordinator import GreeConfigEntry, GreeCoordinator

PLATFORMS = [
    Platform.CLIMATE,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]
_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Gree component from yaml."""
    if DOMAIN not in config:
        return True

    for climate_config in config[DOMAIN]:
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": "import"},
                data=climate_config,
            )
        )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: GreeConfigEntry) -> bool:
    """Set up Gree from a config entry."""

    _LOGGER.info(
        "Setting up entry '%s' for: %s at %s",
        entry.entry_id,
        entry.data[CONF_MAC],
        entry.data[CONF_HOST],
    )
    _LOGGER.debug("Entry '%s' data: %s\n%s", entry.entry_id, entry, entry.data)

    conf = entry.data
    if conf is None or conf[CONF_ADVANCED] is None:
        _LOGGER.error("Bad config entry, this should not happen")
        return False

    coordinators: dict[str, GreeCoordinator] = {}
    for d in conf.get(CONF_DEVICES, []):
        mac = str(d.get(CONF_MAC, ""))
        device = GreeDevice(
            d.get(CONF_DEV_NAME, "Gree HVAC"),
            conf.get(CONF_HOST, ""),
            mac,
            conf[CONF_ADVANCED].get(CONF_PORT, DEFAULT_DEVICE_PORT),
            conf[CONF_ADVANCED].get(CONF_ENCRYPTION_KEY, ""),
            conf[CONF_ADVANCED].get(
                CONF_ENCRYPTION_VERSION, DEFAULT_ENCRYPTION_VERSION
            ),
            conf[CONF_ADVANCED].get(CONF_UID, DEFAULT_DEVICE_UID),
            max_connection_attempts=conf[CONF_ADVANCED].get(
                CONF_MAX_ONLINE_ATTEMPTS, DEFAULT_CONNECTION_MAX_ATTEMPTS
            ),
        )
        try:
            async with asyncio.timeout(30):
                await device.bind_device()
            # TODO: Add scan interval to config
            coordinators[mac] = GreeCoordinator(hass, entry, device)
            await coordinators[mac].async_config_entry_first_refresh()
            _LOGGER.debug("Bound to device %s", mac)
        except TimeoutError as err:
            _LOGGER.debug("Conection to %s timed out", mac)
            raise ConfigEntryNotReady from err
        except GreeDeviceNotBoundError as err:
            _LOGGER.debug("Failed to bind to device %s", mac)
            raise ConfigEntryNotReady from err

    entry.runtime_data = coordinators

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: GreeConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Remove a config entry from a device."""

    # Find MAC address for this device (from identifiers)
    identifiers = device_entry.identifiers
    mac: str | None = None
    for domain, identifier in identifiers:
        if domain == DOMAIN:
            mac = identifier
            break

    if mac is None:
        return False

    runtime_data: GreeCoordinator | None = config_entry.runtime_data.pop(mac, None)

    if not runtime_data:
        return False

    data: dict = dict(config_entry.data)
    device_configs: list[dict] = data.get(CONF_DEVICES, [])
    for dconf in list(device_configs):
        if dconf.get(CONF_MAC, "") != mac:
            continue

        device_configs.remove(dconf)

    data[CONF_DEVICES] = device_configs

    device_registry = dr.async_get(hass)
    device_registry.async_remove_device(device_entry.id)

    if device_configs:
        # There are still other devices, update the entry
        hass.config_entries.async_update_entry(config_entry, data=data)
    else:
        # No other devices, remove the entry
        await hass.config_entries.async_remove(config_entry.entry_id)

    return True
