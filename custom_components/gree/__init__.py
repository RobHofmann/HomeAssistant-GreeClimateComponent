"""Gree climate integration init."""

from __future__ import annotations

# Standard library imports
import asyncio
import logging

# Third-party imports
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_NAME, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.typing import ConfigType

# Local imports
from .const import (
    CONF_ADVANCED,
    CONF_ENCRYPTION_KEY,
    CONF_ENCRYPTION_VERSION,
    CONF_MAX_ONLINE_ATTEMPTS,
    CONF_UID,
    DEFAULT_ENCRYPTION_VERSION,
    DEFAULT_MAX_ONLINE_ATTEMPTS,
    DEFAULT_PORT,
    DOMAIN,
)

# Home Assistant imports
from .coordinator import GreeConfigEntry, GreeCoordinator
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

    _LOGGER.debug("Setting up entry: %s\n%s", entry, entry.data)

    conf = entry.data
    if conf is None or conf[CONF_ADVANCED] is None:
        _LOGGER.error("Bad config entry, this should not happen")
        return False

    host: str = conf[CONF_HOST]

    new_device = GreeDevice(
        name=conf.get(CONF_NAME, "Gree HVAC"),
        ip_addr=host,
        mac_addr=str(conf.get(CONF_MAC, "")).replace(":", ""),
        port=conf[CONF_ADVANCED].get(CONF_PORT, DEFAULT_PORT),
        encryption_version=conf[CONF_ADVANCED].get(
            CONF_ENCRYPTION_VERSION, DEFAULT_ENCRYPTION_VERSION
        ),
        encryption_key=conf[CONF_ADVANCED].get(CONF_ENCRYPTION_KEY, ""),
        uid=conf[CONF_ADVANCED].get(CONF_UID, 0),
        max_connection_attempts=conf.get(
            CONF_MAX_ONLINE_ATTEMPTS, DEFAULT_MAX_ONLINE_ATTEMPTS
        ),
    )

    try:
        async with asyncio.timeout(30):
            await new_device.bind_device()
        _LOGGER.debug("Bound to device %s", host)
    except TimeoutError as err:
        _LOGGER.debug("Conection to %s timed out", host)
        raise ConfigEntryNotReady from err
    except GreeDeviceNotBoundError as err:
        _LOGGER.debug("Failed to bind to device %s", host)
        raise ConfigEntryNotReady from err

    coordinator = GreeCoordinator(hass, entry, new_device)

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    _LOGGER.debug("Options updated for entry %s: %s", entry.entry_id, entry.options)
    _LOGGER.debug("Reloading config entry %s after options update", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)
