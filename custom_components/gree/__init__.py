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
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryError, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import entity_sources
from homeassistant.helpers.typing import UNDEFINED, ConfigType
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

# Version 5 writes this record into the options of each entry it moves over,
# see _async_go_back_from_successor()
SUCCESSOR_MIGRATION_KEY = "gree_custom_migration"
SUCCESSOR_MIGRATION_VERSION = 1

# Key in hass.data[DOMAIN]: True when version 5 is installed
DATA_SUCCESSOR_INSTALLED = "_successor_installed"

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


async def _async_successor_installed(hass: HomeAssistant) -> bool:
    """Return True when version 5 (gree_custom) is installed."""
    try:
        await async_get_integration(hass, SUCCESSOR_DOMAIN)
    except IntegrationNotFound:
        return False
    return True


@callback
def _async_go_back_from_successor(hass: HomeAssistant) -> None:
    """Give the rows that version 5 moved over back to the entries of this version.

    Runs in async_setup when version 5 is not installed, so before any entry of
    this version sets up its platforms. Version 5 leaves a record in the
    options of each entry it moved over. With it, the entities and the device
    move back, so entity IDs, areas and names stay, and the entry is enabled
    again. Without a record there is nothing to do.
    """
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    loaded = entity_sources(hass)

    for entry in hass.config_entries.async_entries(DOMAIN):
        record = entry.options.get(SUCCESSOR_MIGRATION_KEY)
        if not isinstance(record, dict) or record.get("version") != SUCCESSOR_MIGRATION_VERSION:
            continue

        _LOGGER.info("Going back from %s: restoring entry '%s'", SUCCESSOR_DOMAIN, entry.title)

        # The entities move first: moving a device removes the entities that
        # still belong to its old config entry
        devices = {
            device_id: {tuple(identifier) for identifier in identifiers}
            for device_id, identifiers in (record.get("devices") or {}).items()
            if dev_reg.async_get(device_id) is not None
        }
        target_device_id = next(iter(devices), None)

        for entity_id, old_unique_id in (record.get("entities") or {}).items():
            row = ent_reg.async_get(entity_id)
            if row is None:
                _async_create_removed_row(ent_reg, entry, entity_id, old_unique_id, target_device_id)
                continue
            if row.platform != SUCCESSOR_DOMAIN:
                _LOGGER.info("Going back from %s: %s is not moved, it is not a %s entity", SUCCESSOR_DOMAIN, entity_id, SUCCESSOR_DOMAIN)
                continue
            if existing := ent_reg.async_get_entity_id(row.domain, DOMAIN, old_unique_id):
                _LOGGER.info("Going back from %s: %s is not moved, because %s already exists", SUCCESSOR_DOMAIN, entity_id, existing)
                continue
            if entity_id in loaded:
                _LOGGER.info("Going back from %s: %s is not moved, it is still loaded", SUCCESSOR_DOMAIN, entity_id)
                continue

            # Home Assistant checks a new unique ID against the old platform, so an
            # unchanged one would clash with the row itself
            try:
                ent_reg.async_update_entity_platform(
                    entity_id,
                    DOMAIN,
                    new_config_entry_id=entry.entry_id,
                    new_unique_id=old_unique_id if old_unique_id != row.unique_id else UNDEFINED,
                    new_device_id=target_device_id,
                )
            except ValueError as err:
                _LOGGER.warning("Going back from %s: cannot move %s: %s", SUCCESSOR_DOMAIN, entity_id, err)
                continue
            _LOGGER.info("Going back from %s: moved %s to entry '%s'", SUCCESSOR_DOMAIN, entity_id, entry.title)

        for device_id, identifiers in devices.items():
            _async_move_device_back(hass, dev_reg, entry, device_id, identifiers)

        options = {key: value for key, value in entry.options.items() if key != SUCCESSOR_MIGRATION_KEY}
        hass.config_entries.async_update_entry(entry, options=options)

        if entry.disabled_by is not None:
            # Enabling reloads the entry, and a reload sets up this integration.
            # Awaiting that here, inside async_setup, would wait for itself. As a
            # task the entry is enabled before Home Assistant sets up the entries
            # of this integration, so it loads with the others.
            _LOGGER.info("Going back from %s: enabling entry '%s'", SUCCESSOR_DOMAIN, entry.title)
            hass.async_create_task(hass.config_entries.async_set_disabled_by(entry.entry_id, None))


@callback
def _async_create_removed_row(
    ent_reg: er.EntityRegistry,
    entry: ConfigEntry,
    entity_id: str,
    old_unique_id: str,
    device_id: str | None,
) -> None:
    """Create the row of an entity that version 5 removed, with its old entity ID.

    Version 5 removes the switches a unit does not provide. Without a row, this
    version would create them again under a new entity ID.
    """
    domain, object_id = entity_id.split(".", 1)
    if ent_reg.async_get_entity_id(domain, DOMAIN, old_unique_id):
        return

    row = ent_reg.async_get_or_create(
        domain,
        DOMAIN,
        old_unique_id,
        suggested_object_id=object_id,
        config_entry=entry,
        device_id=device_id,
    )
    _LOGGER.info("Going back from %s: created %s again as %s", SUCCESSOR_DOMAIN, entity_id, row.entity_id)


@callback
def _async_move_device_back(
    hass: HomeAssistant,
    dev_reg: dr.DeviceRegistry,
    entry: ConfigEntry,
    device_id: str,
    identifiers: set[tuple[str, str]],
) -> None:
    """Move a device row back to `entry` with its identifiers from before version 5.

    Home Assistant removes the entities of version 5 that are still linked to
    the device, because their config entry no longer owns it.
    """
    device = dev_reg.async_get(device_id)
    if device is None or device.identifiers == identifiers:
        return

    _LOGGER.info(
        "Going back from %s: moving device '%s' to entry '%s'",
        SUCCESSOR_DOMAIN,
        device.name_by_user or device.name,
        entry.title,
    )
    try:
        try:
            dev_reg.async_update_device(
                device_id,
                new_identifiers=identifiers,
                new_config_entry_id=entry.entry_id,
            )
        except TypeError:
            # Home Assistant before `new_config_entry_id` moved a device this way
            for old_entry_id in device.config_entries:
                old_entry = hass.config_entries.async_get_entry(old_entry_id)
                if old_entry is None or old_entry.domain != SUCCESSOR_DOMAIN:
                    continue
                dev_reg.async_update_device(
                    device_id,
                    new_identifiers=identifiers,
                    add_config_entry_id=entry.entry_id,
                    remove_config_entry_id=old_entry_id,
                )
    except HomeAssistantError as err:
        # For example a device row of this entry that already has these identifiers
        _LOGGER.warning("Going back from %s: cannot move device %s: %s", SUCCESSOR_DOMAIN, device_id, err)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Gree component from yaml."""
    successor_installed = await _async_successor_installed(hass)
    hass.data.setdefault(DOMAIN, {})[DATA_SUCCESSOR_INSTALLED] = successor_installed
    if successor_installed:
        _start_successor(hass, config)
    else:
        _async_go_back_from_successor(hass)

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

    # Version 5 moved this device over and still runs it. Setting up here as
    # well would give duplicate entities and two clients on one unit.
    if SUCCESSOR_MIGRATION_KEY in entry.options and hass.data[DOMAIN].get(DATA_SUCCESSOR_INSTALLED):
        raise ConfigEntryError(
            f"Version 5 ({SUCCESSOR_DOMAIN}) is still installed and owns this device. "
            f"To go back to this version, delete custom_components/{SUCCESSOR_DOMAIN} and restart Home Assistant"
        )

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
