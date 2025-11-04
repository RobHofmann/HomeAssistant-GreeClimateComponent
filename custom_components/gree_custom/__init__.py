"""Gree climate integration init."""

from __future__ import annotations

# Standard library imports
import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.typing import ConfigType

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
from .gree_api import (
    DEFAULT_CONNECTION_MAX_ATTEMPTS,
    DEFAULT_DEVICE_PORT,
    DEFAULT_DEVICE_UID,
)
from .gree_device import GreeDevice, GreeDeviceNotBoundError

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


def _update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    _LOGGER.debug("Options updated for entry %s: %s", entry.entry_id, entry.options)
    _LOGGER.debug("Reloading config entry %s after options update", entry.entry_id)
    hass.config_entries.async_schedule_reload(entry.entry_id)
