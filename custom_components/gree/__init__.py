"""Gree climate integration init."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, PLATFORMS
from .climate import OPTION_KEYS

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Gree component from yaml."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Gree from a config entry."""
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    combined_data = {**entry.data}
    for key, value in entry.options.items():
        if key not in OPTION_KEYS:
            _LOGGER.debug("Ignoring unexpected option key %s", key)
            continue
        if value is None:
            combined_data.pop(key, None)
        else:
            combined_data[key] = value
    hass.data[DOMAIN][entry.entry_id] = combined_data
    _LOGGER.debug("Setting up config entry %s with data: %s", entry.entry_id, combined_data)
    entry.async_on_unload(entry.add_update_listener(_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        _LOGGER.debug("Unloaded config entry %s", entry.entry_id)
        hass.data[DOMAIN].pop(entry.entry_id)
    return unloaded


async def _update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    _LOGGER.debug(
        "Options updated for entry %s: %s", entry.entry_id, entry.options
    )
    _LOGGER.debug(
        "Reloading config entry %s after options update", entry.entry_id
    )
    await hass.config_entries.async_reload(entry.entry_id)
