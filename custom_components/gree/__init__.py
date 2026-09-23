"""Gree climate integration init."""

from __future__ import annotations

# Standard library imports
import logging

# Third-party imports
import voluptuous as vol

# Home Assistant imports
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_MAC,
    CONF_NAME,
    CONF_PORT,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import IntegrationNotFound, async_get_integration
from homeassistant.setup import async_setup_component

# Local imports
from .const import (
    CONF_DISABLE_AVAILABLE_CHECK,
    CONF_ENCRYPTION_KEY,
    CONF_ENCRYPTION_VERSION,
    CONF_FAN_MODES,
    CONF_HVAC_MODES,
    CONF_SWING_HORIZONTAL_MODES,
    CONF_SWING_MODES,
    CONF_TEMP_SENSOR_OFFSET,
    CONF_UID,
    DEFAULT_FAN_MODES,
    DEFAULT_HVAC_MODES,
    DEFAULT_PORT,
    DEFAULT_SWING_HORIZONTAL_MODES,
    DEFAULT_SWING_MODES,
    DOMAIN,
    OPTION_KEYS,
)

PLATFORMS = [Platform.CLIMATE, Platform.SWITCH, Platform.NUMBER, Platform.SELECT, Platform.SENSOR]
_LOGGER = logging.getLogger(__name__)

# Version 5 of this integration uses its own domain, see _start_successor()
SUCCESSOR_DOMAIN = "gree_custom"

# YAML configuration schema
CLIMATE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_HOST): cv.string,
        vol.Required(CONF_MAC): cv.string,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
        vol.Optional(CONF_ENCRYPTION_KEY): cv.string,
        vol.Optional(CONF_UID): cv.positive_int,
        vol.Optional(CONF_ENCRYPTION_VERSION, default=1): vol.In([1, 2]),
        vol.Optional(CONF_HVAC_MODES, default=DEFAULT_HVAC_MODES): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(CONF_FAN_MODES, default=DEFAULT_FAN_MODES): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(CONF_SWING_MODES, default=DEFAULT_SWING_MODES): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(CONF_SWING_HORIZONTAL_MODES, default=DEFAULT_SWING_HORIZONTAL_MODES): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(CONF_DISABLE_AVAILABLE_CHECK, default=False): cv.boolean,
        vol.Optional(CONF_TEMP_SENSOR_OFFSET): cv.boolean,
    }
)

CONFIG_SCHEMA = vol.Schema({DOMAIN: vol.All(cv.ensure_list, [CLIMATE_SCHEMA])}, extra=vol.ALLOW_EXTRA)


def _start_successor(hass: HomeAssistant, config: ConfigType) -> None:
    """Start version 5 when it is installed next to this version.

    Version 5 uses the domain gree_custom and moves the devices of this
    version over when it starts. Home Assistant only sets up an integration
    that has a config entry or a YAML key, and after an update through HACS
    gree_custom has neither yet. So this version starts it.
    """

    async def _setup() -> None:
        try:
            await async_get_integration(hass, SUCCESSOR_DOMAIN)
        except IntegrationNotFound:
            return
        _LOGGER.info("Starting %s, which replaces this integration", SUCCESSOR_DOMAIN)
        await async_setup_component(hass, SUCCESSOR_DOMAIN, config)

    hass.async_create_task(_setup())


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Gree component from yaml."""
    _start_successor(hass, config)

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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Gree from a config entry."""
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    # Combine entry data with options
    combined_data = {**entry.data}
    for key, value in entry.options.items():
        if key not in OPTION_KEYS:
            _LOGGER.debug("Ignoring unexpected option key %s", key)
            continue
        if value is None:
            combined_data.pop(key, None)
        else:
            combined_data[key] = value

    # Create the Gree device instance here and store it
    from .climate import create_gree_device

    device = await create_gree_device(hass, combined_data)

    # Store both the config data and the device instance
    hass.data[DOMAIN][entry.entry_id] = {
        "config": combined_data,
        "device": device,
    }

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
    _LOGGER.debug("Options updated for entry %s: %s", entry.entry_id, entry.options)
    _LOGGER.debug("Reloading config entry %s after options update", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)
