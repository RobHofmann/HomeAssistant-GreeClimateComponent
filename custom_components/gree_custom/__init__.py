"""Gree climate integration init."""

from __future__ import annotations

# Standard library imports
import asyncio
import logging

from homeassistant.components.diagnostics.util import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_PORT, CONF_TIMEOUT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.typing import Any, ConfigType

from .aiogree.const import (
    DEFAULT_CONNECTION_MAX_ATTEMPTS,
    DEFAULT_CONNECTION_TIMEOUT,
    DEFAULT_DEVICE_PORT,
    DEFAULT_DEVICE_UID,
)
from .aiogree.device import GreeDevice
from .aiogree.errors import GreeBindingError

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
    Platform.BINARY_SENSOR,
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
        "Setup entry '%s': %s at %s",
        entry.entry_id,
        entry.data[CONF_MAC],
        entry.data[CONF_HOST],
    )
    _LOGGER.debug(
        "Setup entry '%s': %s\ndata=%s",
        entry.entry_id,
        entry,
        async_redact_data(entry.data, ["encryption_key"]),
    )

    conf = entry.data
    if (
        conf is None
        or conf[CONF_MAC] is None
        or conf[CONF_HOST] is None
        or conf[CONF_ADVANCED] is None
    ):
        _LOGGER.error("Bad config entry, this should not happen")
        return False

    coordinators: dict[str, GreeCoordinator] = {}
    for d in conf.get(CONF_DEVICES, []):
        mac = str(d.get(CONF_MAC, "")) + "@" + conf.get(CONF_MAC)
        device = GreeDevice(
            name=d.get(CONF_DEV_NAME, "Gree HVAC"),
            ip_addr=conf.get(CONF_HOST),
            mac_addr=mac,
            port=conf[CONF_ADVANCED].get(CONF_PORT, DEFAULT_DEVICE_PORT),
            encryption_key=conf[CONF_ADVANCED].get(CONF_ENCRYPTION_KEY, ""),
            encryption_version=conf[CONF_ADVANCED].get(
                CONF_ENCRYPTION_VERSION, DEFAULT_ENCRYPTION_VERSION
            ),
            uid=conf[CONF_ADVANCED].get(CONF_UID, DEFAULT_DEVICE_UID),
            max_connection_attempts=conf[CONF_ADVANCED].get(
                CONF_MAX_ONLINE_ATTEMPTS, DEFAULT_CONNECTION_MAX_ATTEMPTS
            ),
            timeout=conf[CONF_ADVANCED].get(CONF_TIMEOUT, DEFAULT_CONNECTION_TIMEOUT),
        )
        try:
            _LOGGER.debug(
                "Setup entry '%s': Configuring Gree Device (%s, %s)",
                entry.entry_id,
                mac,
                conf.get(CONF_HOST),
            )
            await device.bind_device()
            # TODO: Add scan interval to config
            coordinators[device.mac_address] = GreeCoordinator(hass, entry, device)
            await coordinators[device.mac_address].async_config_entry_first_refresh()
            _LOGGER.debug("Setup entry '%s': Bound to device %s", entry.entry_id, mac)
        except TimeoutError as err:
            _LOGGER.exception(
                "Setup entry '%s': Conection to %s timed out", entry.entry_id, mac
            )
            raise ConfigEntryNotReady from err
        except GreeBindingError as err:
            _LOGGER.exception(
                "Setup entry '%s': Failed to bind to device %s", entry.entry_id, mac
            )
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
    device_configs: list[dict] = data.get(CONF_DEVICES, [])
    new_device_configs = [d for d in device_configs if d.get(CONF_MAC) != mac]

    if len(new_device_configs) == len(device_configs):
        # Nothing to remove
        return False

    data[CONF_DEVICES] = new_device_configs

    device_registry = dr.async_get(hass)
    device_registry.async_remove_device(device_entry.id)

    if new_device_configs:
        # There are still other devices, update the entry
        await hass.config_entries.async_update_entry(config_entry, data=data)
    else:
        # No other devices, remove the entry
        await hass.config_entries.async_remove(config_entry.entry_id)

    return True
