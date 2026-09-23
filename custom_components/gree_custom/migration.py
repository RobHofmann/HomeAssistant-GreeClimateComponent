"""Move a Gree 4.x setup to this integration without user action.

Releases 4.x used the domain `gree`, a flat config entry per device and a flat
`gree:` YAML block. This module moves such a setup over in two phases:

1. `async_prepare_legacy_migration()` runs in `async_setup`. It reads the old
   config entries and the old `gree:` block, converts every device to the
   shape of this integration, and decides how the devices come in: through
   the YAML import when a YAML block manages the local devices, or through
   the `migrate` config flow step otherwise. It also raises the repair issues.
2. `async_migrate_legacy_registry()` runs in `async_setup_entry`, when the
   new entry exists. It moves the device and entity registry rows of the old
   entries to the new entry, so entity IDs, areas and history stay, and then
   disables or removes the old entries.

The details are in `docs/config-entry.md`.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import probatio
else:
    try:
        import probatio
    except ImportError:
        import voluptuous as probatio

from homeassistant import config as conf_util
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryDisabler,
    ConfigEntryState,
    OperationNotAllowed,
)
from homeassistant.const import (
    CONF_HOST,
    CONF_MAC,
    CONF_NAME,
    CONF_PORT,
    EVENT_HOMEASSISTANT_STARTED,
)
from homeassistant.core import CoreState, Event, HomeAssistant, callback
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.helpers.entity import entity_sources
from homeassistant.helpers.restore_state import async_get as async_get_restore_data
from homeassistant.helpers.typing import UNDEFINED, ConfigType
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml import dump as yaml_dump

from .aiogree.api import HorizontalSwingMode, VerticalSwingMode
from .aiogree.helpers import gree_extract_macs
from .config_schema import (
    ITEM_SCHEMA,
    VALID_FAN_MODES,
    VALID_HVAC_MODES,
    _target_temp_step,
)
from .const import (
    ATTR_EXTERNAL_HUMIDITY_SENSOR,
    ATTR_EXTERNAL_TEMPERATURE_SENSOR,
    CONF_CLOUD,
    CONF_DEVICE_CONNECTION,
    CONF_DEVICE_CONNECTION_LOCAL,
    CONF_DEVICE_OPTIONS,
    CONF_DEVICES,
    CONF_DISABLE_AVAILABLE_CHECK,
    CONF_ENCRYPTION_KEY,
    CONF_ENCRYPTION_VERSION,
    CONF_FAN_MODES,
    CONF_HVAC_MODES,
    CONF_SWING_HORIZONTAL_MODES,
    CONF_SWING_MODES,
    CONF_TEMPERATURE_STEP,
    CONF_UID,
    DEFAULT_DEVICE_PORT,
    DEFAULT_FAN_MODES,
    DEFAULT_SWING_HORIZONTAL_MODES,
    DEFAULT_SWING_MODES,
    DEFAULT_TARGET_TEMP_STEP,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

LEGACY_DOMAIN = "gree"
LEGACY_CONF_TEMP_SENSOR_OFFSET = "temp_sensor_offset"
SOURCE_MIGRATE = "migrate"

ISSUE_LEGACY_YAML = "legacy_yaml"
ISSUE_LEGACY_FOLDER = "legacy_folder"

DATA_LEGACY_MIGRATION = f"{DOMAIN}_legacy_migration"

# The 4.x repo, to tell our old component from any other `gree` folder
LEGACY_DOCUMENTATION_MARKER = "HomeAssistant-GreeClimateComponent"

# Swing modes had other names in 4.x. They are matched on the value that goes
# on the wire, so a migrated unit moves its louvers the same way as before.
# The values come from `MODES_MAPPING` in 4.x `const.py`.
LEGACY_SWING_MODE_VALUES = {
    "default": 0,
    "swing_full": 1,
    "fixed_upmost": 2,
    "fixed_middle_up": 3,
    "fixed_middle": 4,
    "fixed_middle_low": 5,
    "fixed_lowest": 6,
    "swing_downmost": 7,
    "swing_middle_low": 8,
    "swing_middle": 9,
    "swing_middle_up": 10,
    "swing_upmost": 11,
}
LEGACY_SWING_HORIZONTAL_MODE_VALUES = {
    "default": 0,
    "swing_full": 1,
    "fixed_leftmost": 2,
    "fixed_middle_left": 3,
    "fixed_middle": 4,
    "fixed_middle_right": 5,
    "fixed_rightmost": 6,
}

# 4.x used these lists when a device had none, in YAML and in the UI alike.
# The values come from 4.x `const.py`.
LEGACY_DEFAULT_MODES = {
    CONF_HVAC_MODES: ["auto", "cool", "dry", "fan_only", "heat", "off"],
    CONF_FAN_MODES: [
        "auto",
        "low",
        "medium_low",
        "medium",
        "medium_high",
        "high",
        "turbo",
        "quiet",
    ],
    CONF_SWING_MODES: list(LEGACY_SWING_MODE_VALUES),
    CONF_SWING_HORIZONTAL_MODES: list(LEGACY_SWING_HORIZONTAL_MODE_VALUES),
}

# 4.x entity keys that map to another key here. Keys that are not listed and
# not in LEGACY_SAME_KEYS have no entity in this version.
LEGACY_RENAMED_KEYS = {
    "outside_temperature": "outdoor_temperature",
}
LEGACY_SAME_KEYS = {
    "xfan",
    "lights",
    "health",
    "powersave",
    "eightdegheat",
    "sleep",
    "air",
    "anti_direct_blow",
    "light_sensor",
    "auto_xfan",
    "auto_light",
    "beeper",
    "room_humidity",
}
LEGACY_CLIMATE_PREFIX = f"{LEGACY_DOMAIN}_"
CLIMATE_KEY = "hvac"

# 4.x entities whose last state becomes an option here
LEGACY_STATE_OPTIONS = {
    "target_temp_step": CONF_TEMPERATURE_STEP,
    "external_temperature_sensor": ATTR_EXTERNAL_TEMPERATURE_SENSOR,
    "external_humidity_sensor": ATTR_EXTERNAL_HUMIDITY_SENSOR,
}

# The 4.x YAML schema, without its defaults. Unknown keys are allowed, so a
# typo in an old block does not stop the whole migration.
LEGACY_DEVICE_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_NAME): cv.string,
        probatio.Required(CONF_HOST): cv.string,
        probatio.Required(CONF_MAC): cv.string,
        probatio.Optional(CONF_PORT): cv.port,
        probatio.Optional(CONF_ENCRYPTION_KEY): probatio.Any(None, cv.string),
        probatio.Optional(CONF_UID): probatio.Any(None, cv.positive_int),
        probatio.Optional(CONF_ENCRYPTION_VERSION): probatio.All(
            probatio.Coerce(int), probatio.In([1, 2])
        ),
        probatio.Optional(CONF_HVAC_MODES): probatio.All(cv.ensure_list, [cv.string]),
        probatio.Optional(CONF_FAN_MODES): probatio.All(cv.ensure_list, [cv.string]),
        probatio.Optional(CONF_SWING_MODES): probatio.All(cv.ensure_list, [cv.string]),
        probatio.Optional(CONF_SWING_HORIZONTAL_MODES): probatio.All(
            cv.ensure_list, [cv.string]
        ),
        probatio.Optional(CONF_DISABLE_AVAILABLE_CHECK): cv.boolean,
        probatio.Optional(LEGACY_CONF_TEMP_SENSOR_OFFSET): probatio.Any(
            None, cv.boolean
        ),
    },
    extra=probatio.ALLOW_EXTRA,
)


@dataclass
class LegacyDevice:
    """One 4.x device, converted to the YAML shape of this integration."""

    key: str
    """Device key as it goes in YAML: the MAC, or `<mac>@<controller mac>`."""
    mac: str
    """Normalized device MAC, the key in the config entry."""
    mac_controller: str
    """MAC that 4.x used in its unique IDs and device identifiers."""
    config: dict[str, Any]
    """Device block in the YAML shape, with only the values that differ from the defaults."""
    entry_id: str | None = None
    """The 4.x config entry, when the device came from one."""


@dataclass
class LegacyMigration:
    """What phase 1 learned, for phase 2 in `async_setup_entry`."""

    folder_present: bool = True
    """The 4.x folder is still installed, so its entries must stay (disabled)."""
    macs_needing_old_entry: set[str] = field(default_factory=set)
    """UI devices that are only kept because the old entry still exists."""


def legacy_device_key(raw_mac: str) -> str:
    """Clean a 4.x MAC the way the YAML schema of this integration expects it."""
    return str(raw_mac).replace(":", "").replace("-", "").strip().lower()


def _convert_modes(
    name: str,
    field_name: str,
    values: list[str],
    to_new: Mapping[str, str],
    all_modes: list[str],
) -> list[str] | None:
    """Convert a 4.x mode list. Returns None when the default covers it."""
    converted: list[str] = []

    for value in values:
        new_value = to_new.get(value)
        if new_value is None:
            _LOGGER.warning(
                "Migration from 4.x: %s: %s value '%s' is not known and is dropped",
                name,
                field_name,
                value,
            )
            continue
        if new_value not in converted:
            converted.append(new_value)

    if values and set(converted) == set(all_modes):
        return None

    return converted


def _swing_map(legacy_values: Mapping[str, int], new_enum: Any) -> dict[str, str]:
    """Map a 4.x swing name to the name here that sends the same value."""
    return {name: new_enum(value).name for name, value in legacy_values.items()}


SWING_MODE_MAP = _swing_map(LEGACY_SWING_MODE_VALUES, VerticalSwingMode)
SWING_HORIZONTAL_MODE_MAP = _swing_map(
    LEGACY_SWING_HORIZONTAL_MODE_VALUES, HorizontalSwingMode
)


def convert_legacy_device(
    conf: Mapping[str, Any], extra_options: Mapping[str, Any] | None = None
) -> tuple[str, dict[str, Any]]:
    """Convert one 4.x device config to a device block of this integration.

    `conf` is a 4.x YAML item or the data of a 4.x config entry with its
    options merged in. `extra_options` are options that 4.x kept as entity
    state, such as the temperature step.

    Returns the device key and the device block, in the YAML shape. Values
    that equal the defaults of this integration are left out, so the block
    stays short and a user can paste it as is.
    """
    name = str(conf[CONF_NAME])
    key = legacy_device_key(conf[CONF_MAC])

    local: dict[str, Any] = {CONF_HOST: conf[CONF_HOST]}
    port = conf.get(CONF_PORT) or DEFAULT_DEVICE_PORT
    if int(port) != DEFAULT_DEVICE_PORT:
        local[CONF_PORT] = int(port)
    # 4.x always had a version and defaulted to 1. Keep it, so the unit gets
    # the same cipher as before without a detection round.
    local[CONF_ENCRYPTION_VERSION] = str(conf.get(CONF_ENCRYPTION_VERSION) or 1)

    connection: dict[str, Any] = {}
    if conf.get(CONF_ENCRYPTION_KEY):
        connection[CONF_ENCRYPTION_KEY] = str(conf[CONF_ENCRYPTION_KEY])
    if conf.get(CONF_UID):
        connection[CONF_UID] = int(conf[CONF_UID])
    if conf.get(CONF_DISABLE_AVAILABLE_CHECK):
        connection[CONF_DISABLE_AVAILABLE_CHECK] = True
    connection[CONF_DEVICE_CONNECTION_LOCAL] = local

    options: dict[str, Any] = {CONF_NAME: name}

    mode_fields: list[tuple[str, Mapping[str, str], list[str]]] = [
        (
            CONF_HVAC_MODES,
            {m: m for m in VALID_HVAC_MODES},
            VALID_HVAC_MODES,
        ),
        (CONF_FAN_MODES, {m: m for m in VALID_FAN_MODES}, DEFAULT_FAN_MODES),
        (CONF_SWING_MODES, SWING_MODE_MAP, DEFAULT_SWING_MODES),
        (
            CONF_SWING_HORIZONTAL_MODES,
            SWING_HORIZONTAL_MODE_MAP,
            DEFAULT_SWING_HORIZONTAL_MODES,
        ),
    ]
    for field_name, to_new, all_modes in mode_fields:
        values = conf.get(field_name)
        if values is None:
            values = LEGACY_DEFAULT_MODES[field_name]
        converted = _convert_modes(name, field_name, list(values), to_new, all_modes)
        if converted is not None:
            options[field_name] = converted

    if conf.get(LEGACY_CONF_TEMP_SENSOR_OFFSET) is not None:
        _LOGGER.info(
            "Migration from 4.x: %s: temp_sensor_offset is not needed any more"
            " and is dropped",
            name,
        )

    options.update(extra_options or {})

    return key, {CONF_DEVICE_CONNECTION: connection, CONF_DEVICE_OPTIONS: options}


def _normalize_device(
    key: str, device_config: dict[str, Any]
) -> tuple[str, dict[str, Any]] | None:
    """Run one converted device through the YAML schema of this integration.

    Returns the normalized MAC and the full device config, or None when the
    device is not valid.
    """
    try:
        item = ITEM_SCHEMA({CONF_DEVICES: {key: device_config}})
    except probatio.Invalid as err:
        _LOGGER.error(
            "Migration from 4.x: device %s cannot be converted and is skipped: %s",
            key,
            err,
        )
        return None

    ((mac, normalized),) = item[CONF_DEVICES].items()
    return mac, normalized


def _restored_options(
    hass: HomeAssistant, entry_id: str | None, mac_controller: str
) -> dict[str, Any]:
    """Read the options that 4.x kept as the state of an entity."""
    if entry_id is None:
        return {}

    ent_reg = er.async_get(hass)
    try:
        last_states = async_get_restore_data(hass).last_states
    except KeyError:
        return {}

    options: dict[str, Any] = {}

    for row in er.async_entries_for_config_entry(ent_reg, entry_id):
        legacy_key = row.unique_id.removeprefix(f"{mac_controller}_")
        option = LEGACY_STATE_OPTIONS.get(legacy_key)
        stored = last_states.get(row.entity_id)
        if option is None or stored is None:
            continue

        value = stored.state.state
        try:
            if option == CONF_TEMPERATURE_STEP:
                step = _target_temp_step(value)
                if step != DEFAULT_TARGET_TEMP_STEP:
                    options[option] = step
            elif value not in ("None", "unknown", "unavailable", ""):
                options[option] = cv.entity_id(value)
        except probatio.Invalid:
            _LOGGER.info(
                "Migration from 4.x: %s value '%s' of %s is not valid here and is"
                " dropped",
                legacy_key,
                value,
                row.entity_id,
            )

    return options


def get_legacy_entries(hass: HomeAssistant) -> list[ConfigEntry]:
    """Return the 4.x config entries.

    The built-in `gree` integration of Home Assistant shares the domain, but
    its entries hold no device data, so the MAC and host tell them apart.
    """
    return [
        entry
        for entry in hass.config_entries.async_entries(LEGACY_DOMAIN)
        if CONF_MAC in entry.data and CONF_HOST in entry.data
    ]


def _entry_conf(entry: ConfigEntry) -> dict[str, Any]:
    """Merge the options of a 4.x entry over its data, like 4.x did."""
    conf = dict(entry.data)
    for key, value in entry.options.items():
        if value is None:
            conf.pop(key, None)
        else:
            conf[key] = value
    return conf


def _legacy_device(
    hass: HomeAssistant,
    conf: Mapping[str, Any],
    entry_id: str | None,
    state_entry_id: str | None = None,
) -> LegacyDevice | None:
    """Convert and check one 4.x device.

    `entry_id` is the 4.x entry the device came from. `state_entry_id` is the
    4.x entry whose entity states hold the extra options. 4.x also made an
    entry for a YAML device, so for those the two differ.
    """
    try:
        conf = LEGACY_DEVICE_SCHEMA(dict(conf))
    except probatio.Invalid as err:
        _LOGGER.error(
            "Migration from 4.x: item %s is not valid and is skipped: %s",
            conf.get(CONF_NAME, conf.get(CONF_MAC, "?")),
            err,
        )
        return None

    _, mac_controller = gree_extract_macs(legacy_device_key(conf[CONF_MAC]))
    key, device_config = convert_legacy_device(
        conf, _restored_options(hass, state_entry_id or entry_id, mac_controller)
    )

    normalized = _normalize_device(key, device_config)
    if normalized is None:
        return None

    mac, _ = normalized
    return LegacyDevice(
        key=key,
        mac=mac,
        mac_controller=mac_controller,
        config=device_config,
        entry_id=entry_id,
    )


def _legacy_yaml_block(devices: list[LegacyDevice]) -> str:
    """Build the `gree_custom:` block that replaces the 4.x configuration."""
    block = {DOMAIN: [{CONF_DEVICES: {d.key: d.config for d in devices}}]}
    return yaml_dump(block).strip()


def _read_legacy_manifest(path: str) -> dict[str, Any] | None:
    """Read the manifest of the 4.x folder, if it is there."""
    try:
        with Path(path).open(encoding="utf-8") as file:
            manifest: dict[str, Any] = json.load(file)
    except OSError, ValueError:
        return None
    return manifest


async def async_legacy_folder_present(hass: HomeAssistant) -> bool:
    """Tell if the 4.x component is still in `custom_components/gree`."""
    manifest = await hass.async_add_executor_job(
        _read_legacy_manifest,
        hass.config.path("custom_components", LEGACY_DOMAIN, "manifest.json"),
    )
    return bool(
        manifest
        and manifest.get("domain") == LEGACY_DOMAIN
        and LEGACY_DOCUMENTATION_MARKER in str(manifest.get("documentation", ""))
    )


def _local_item(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the YAML item for the local-only entry, if there is one."""
    return next((item for item in items if item.get(CONF_CLOUD) is None), None)


def _collect_legacy_devices(
    hass: HomeAssistant, config: ConfigType
) -> tuple[bool, list[LegacyDevice]]:
    """Read and convert the 4.x YAML block and the 4.x config entries.

    Returns whether a `gree:` block exists, and the devices: the YAML ones
    first, so a device that is in both keeps its YAML values.
    """
    raw_yaml = config.get(LEGACY_DOMAIN)
    devices: list[LegacyDevice] = []
    legacy_entries = get_legacy_entries(hass)
    entry_by_mac = {
        legacy_device_key(entry.data[CONF_MAC]): entry.entry_id
        for entry in legacy_entries
    }

    if raw_yaml is not None:
        for conf in cv.ensure_list(raw_yaml):
            if not isinstance(conf, Mapping):
                _LOGGER.error("Migration from 4.x: an item of gree: is not a mapping")
                continue
            state_entry_id = entry_by_mac.get(legacy_device_key(conf.get(CONF_MAC, "")))
            if device := _legacy_device(hass, conf, None, state_entry_id):
                devices.append(device)

    devices.extend(
        device
        for entry in legacy_entries
        if (device := _legacy_device(hass, _entry_conf(entry), entry.entry_id))
    )

    return raw_yaml is not None, devices


def _normalized_devices(devices: list[LegacyDevice]) -> dict[str, Any]:
    """Return the full device configs, keyed on the normalized MAC."""
    return {
        normalized[0]: normalized[1]
        for device in devices
        if (normalized := _normalize_device(device.key, device.config))
    }


def _merge_into_yaml(
    items: list[dict[str, Any]], devices: list[LegacyDevice]
) -> list[dict[str, Any]]:
    """Add the 4.x devices to the YAML item of the local-only entry."""
    items = list(items)
    added = _normalized_devices(devices)
    local_item = _local_item(items)

    if local_item is None:
        items.append({CONF_CLOUD: None, CONF_DEVICES: added})
    else:
        items[items.index(local_item)] = {
            **local_item,
            CONF_DEVICES: {**added, **local_item[CONF_DEVICES]},
        }

    return items


def _async_update_yaml_issue(hass: HomeAssistant, devices: list[LegacyDevice]) -> None:
    """Show the block to paste while devices depend on the 4.x configuration."""
    if not devices:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_LEGACY_YAML)
        return

    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_LEGACY_YAML,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_LEGACY_YAML,
        translation_placeholders={"yaml": _legacy_yaml_block(devices)},
    )
    _LOGGER.warning(
        "Migration from 4.x: devices %s still come from the 4.x configuration."
        " They work, but this legacy import will be removed in a later version."
        " See the repair issue for the block to paste in configuration.yaml",
        ", ".join(d.key for d in devices),
    )


def _async_update_folder_issue(hass: HomeAssistant, folder_present: bool) -> None:
    """Ask for the 4.x folder to be deleted while it is there."""
    if not folder_present:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_LEGACY_FOLDER)
        return

    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_LEGACY_FOLDER,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_LEGACY_FOLDER,
    )
    _LOGGER.warning(
        "Migration from 4.x: the old component is still installed in"
        " custom_components/%s. Delete that folder and restart Home Assistant",
        LEGACY_DOMAIN,
    )


def _keep_migrated_options(hass: HomeAssistant, devices: list[LegacyDevice]) -> None:
    """Keep the options that came from 4.x entity states once they are migrated.

    Home Assistant drops the stored state of an entity that is gone for a
    while. A device that is converted again at every start, from a `gree:`
    block, would then lose its temperature step. The entry already holds the
    value from the first run, so take it from there.
    """
    known: dict[str, Mapping[str, Any]] = {
        mac: device.get(CONF_DEVICE_OPTIONS) or {}
        for entry in hass.config_entries.async_entries(DOMAIN)
        for mac, device in (entry.data.get(CONF_DEVICES) or {}).items()
    }

    for device in devices:
        stored = known.get(device.mac)
        if not stored:
            continue
        options = device.config[CONF_DEVICE_OPTIONS]
        for option in LEGACY_STATE_OPTIONS.values():
            if option not in options and option in stored:
                options[option] = stored[option]


async def async_prepare_legacy_migration(
    hass: HomeAssistant, config: ConfigType, items: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Phase 1: convert a 4.x setup and decide how it comes in.

    `items` are the validated `gree_custom:` items. The return value is the
    list of items to import, with the 4.x devices merged in when a YAML block
    manages the local devices. Otherwise the 4.x UI devices go through the
    `migrate` config flow step.
    """
    state = LegacyMigration(folder_present=await async_legacy_folder_present(hass))
    hass.data[DATA_LEGACY_MIGRATION] = state

    has_legacy_yaml, devices = _collect_legacy_devices(hass, config)
    _keep_migrated_options(hass, devices)

    # A device the user already wrote in a gree_custom: block stays as written
    seen: set[str] = {mac for item in items for mac in item[CONF_DEVICES]}
    to_add: list[LegacyDevice] = []
    for device in devices:
        if device.mac not in seen:
            seen.add(device.mac)
            to_add.append(device)

    yaml_managed = has_legacy_yaml or _local_item(items) is not None

    if to_add and yaml_managed:
        items = _merge_into_yaml(items, to_add)
        state.macs_needing_old_entry = {d.mac for d in to_add if d.entry_id is not None}
        _async_update_yaml_issue(hass, to_add)
    else:
        _async_update_yaml_issue(hass, [])
        if to_add:
            _async_start_migrate_flow(hass, to_add)

    _async_update_folder_issue(hass, state.folder_present)

    return items


async def async_setup_from_flow(hass: HomeAssistant) -> bool:
    """Set up this integration when a flow starts and only 4.x is set up.

    Home Assistant only sets up an integration that has a config entry or a
    YAML key. A 4.x user has neither for this domain yet. The start hook in
    the last 4.x release sets this integration up. Without that hook,
    opening the setup flow is the one action that starts the migration.

    Returns True when it started the migration, so the flow can stop.
    """
    if DOMAIN in hass.config.components or not get_legacy_entries(hass):
        return False

    _LOGGER.info("Migration from 4.x: started from a config flow")
    config = await conf_util.async_hass_config_yaml(hass)
    return await async_setup_component(hass, DOMAIN, config)


def _async_start_migrate_flow(hass: HomeAssistant, devices: list[LegacyDevice]) -> None:
    """Start the flow that adds the 4.x UI devices to the local-only entry."""
    configured: set[str] = {
        mac
        for entry in hass.config_entries.async_entries(DOMAIN)
        for mac in entry.data.get(CONF_DEVICES, {})
    }

    new_devices = _normalized_devices(
        [device for device in devices if device.mac not in configured]
    )

    if not new_devices:
        return

    _LOGGER.info(
        "Migration from 4.x: adding devices %s to the local-only entry",
        ", ".join(new_devices),
    )
    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_MIGRATE},
            data={CONF_DEVICES: new_devices},
        )
    )


def _new_unique_id(old_unique_id: str, mac: str, mac_controller: str) -> str | None:
    """Return the unique ID here for a 4.x unique ID, or None if there is none."""
    if old_unique_id.startswith(LEGACY_CLIMATE_PREFIX):
        return f"{mac}_{CLIMATE_KEY}"

    # 4.x used the controller MAC for every other entity, so the entities of
    # the sub-devices of one VRF controller share their unique IDs. Only the
    # climate entity can be told apart there.
    if mac != mac_controller:
        return None

    legacy_key = old_unique_id.removeprefix(f"{mac_controller}_")
    if legacy_key == old_unique_id:
        return None
    if legacy_key in LEGACY_SAME_KEYS:
        return f"{mac}_{legacy_key}"
    if legacy_key in LEGACY_RENAMED_KEYS:
        return f"{mac}_{LEGACY_RENAMED_KEYS[legacy_key]}"
    return None


async def _async_unload_legacy_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a 4.x entry, so its entities can move. Returns False on failure."""
    if entry.state is ConfigEntryState.SETUP_IN_PROGRESS:
        # A setup cannot be unloaded. Wait until it is done.
        async with entry.setup_lock:
            pass

    if entry.state is ConfigEntryState.NOT_LOADED:
        return True

    try:
        return await hass.config_entries.async_unload(entry.entry_id)
    except OperationNotAllowed as err:
        _LOGGER.warning(
            "Migration from 4.x: cannot unload entry '%s' yet: %s", entry.title, err
        )
        return False


def _legacy_entries_for(
    hass: HomeAssistant, entry: ConfigEntry
) -> list[tuple[ConfigEntry, str, str]]:
    """Return the 4.x entries of the devices in `entry`, with MAC and controller MAC."""
    devices: Mapping[str, Any] = entry.data.get(CONF_DEVICES) or {}
    found: list[tuple[ConfigEntry, str, str]] = []

    for legacy_entry in get_legacy_entries(hass):
        mac, mac_controller = gree_extract_macs(
            legacy_device_key(legacy_entry.data[CONF_MAC])
        )
        if mac in devices:
            found.append((legacy_entry, mac, mac_controller))

    return found


async def async_unload_legacy_entries(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Stop the 4.x entries of the devices in `entry`, so only one client polls."""
    for legacy_entry, _, _ in _legacy_entries_for(hass, entry):
        await _async_unload_legacy_entry(hass, legacy_entry)


async def async_migrate_legacy_registry(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, list[str]]:
    """Phase 2: move the registry rows of the 4.x entries to `entry`.

    Runs in `async_setup_entry` before the platforms are set up, so the
    entities of this integration find their moved rows and keep their entity
    IDs. Returns the moved entity IDs per device MAC.
    """
    state: LegacyMigration = hass.data.get(DATA_LEGACY_MIGRATION) or LegacyMigration()
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    moved: dict[str, list[str]] = {}

    for legacy_entry, mac, mac_controller in _legacy_entries_for(hass, entry):
        if not await _async_unload_legacy_entry(hass, legacy_entry):
            continue

        # From here to the disable call nothing awaits, so the old entry
        # cannot load again while its rows move. The entities move first:
        # moving a device removes the entities that still belong to the old
        # entry.
        legacy_device, target_device_id = _find_devices(
            dev_reg, legacy_entry, mac, mac_controller
        )
        moved[mac] = _async_move_entities(
            hass, ent_reg, entry, legacy_entry, mac, mac_controller, target_device_id
        )
        if legacy_device is not None:
            _async_move_device(dev_reg, entry, legacy_entry, legacy_device, mac)

        if state.folder_present or mac in state.macs_needing_old_entry:
            if legacy_entry.disabled_by is None:
                _LOGGER.info(
                    "Migration from 4.x: disabling entry '%s'", legacy_entry.title
                )
                await hass.config_entries.async_set_disabled_by(
                    legacy_entry.entry_id, ConfigEntryDisabler.USER
                )
        else:
            _LOGGER.info("Migration from 4.x: removing entry '%s'", legacy_entry.title)
            await hass.config_entries.async_remove(legacy_entry.entry_id)

    return moved


def _find_devices(
    dev_reg: dr.DeviceRegistry,
    legacy_entry: ConfigEntry,
    mac: str,
    mac_controller: str,
) -> tuple[dr.DeviceEntry | None, str | None]:
    """Find the 4.x device row to move, and the device ID the entities link to."""
    if target := dev_reg.async_get_device(identifiers={(DOMAIN, mac)}):
        return None, target.id

    # A VRF controller held the sub-devices under one row in 4.x. Leave it, and
    # let each sub-device get its own row here.
    if mac != mac_controller:
        return None, None

    legacy_device = dev_reg.async_get_device(identifiers={(LEGACY_DOMAIN, mac)})
    if (
        legacy_device is None
        or legacy_entry.entry_id not in legacy_device.config_entries
    ):
        return None, None

    return legacy_device, legacy_device.id


@callback
def _async_move_device(
    dev_reg: dr.DeviceRegistry,
    entry: ConfigEntry,
    legacy_entry: ConfigEntry,
    legacy_device: dr.DeviceEntry,
    mac: str,
) -> None:
    """Move the 4.x device row to `entry`, so its area and name stay."""
    _LOGGER.info(
        "Migration from 4.x: moving device '%s' to entry '%s'",
        legacy_device.name_by_user or legacy_device.name,
        entry.title,
    )
    try:
        dev_reg.async_update_device(
            legacy_device.id,
            new_identifiers={(DOMAIN, mac)},
            new_config_entry_id=entry.entry_id,
        )
    except TypeError:
        # Home Assistant before `new_config_entry_id` moved a device this way
        dev_reg.async_update_device(
            legacy_device.id,
            new_identifiers={(DOMAIN, mac)},
            add_config_entry_id=entry.entry_id,
            remove_config_entry_id=legacy_entry.entry_id,
        )


@callback
def _async_move_entities(
    hass: HomeAssistant,
    ent_reg: er.EntityRegistry,
    entry: ConfigEntry,
    legacy_entry: ConfigEntry,
    mac: str,
    mac_controller: str,
    target_device_id: str | None,
) -> list[str]:
    """Move the 4.x entity rows that have a counterpart here to `entry`."""
    moved: list[str] = []
    loaded = entity_sources(hass)

    for row in er.async_entries_for_config_entry(ent_reg, legacy_entry.entry_id):
        new_unique_id = _new_unique_id(row.unique_id, mac, mac_controller)
        if new_unique_id is None:
            continue

        if existing := ent_reg.async_get_entity_id(row.domain, DOMAIN, new_unique_id):
            _LOGGER.info(
                "Migration from 4.x: %s is not moved, because %s already exists",
                row.entity_id,
                existing,
            )
            continue

        if row.entity_id in loaded:
            _LOGGER.warning(
                "Migration from 4.x: %s is still loaded and is moved at the next start",
                row.entity_id,
            )
            continue

        if row.disabled_by is er.RegistryEntryDisabler.CONFIG_ENTRY:
            # Disabled only because the old entry was disabled
            ent_reg.async_update_entity(row.entity_id, disabled_by=None)

        # Home Assistant checks a new unique ID against the old platform, so an
        # unchanged one would clash with the row itself
        ent_reg.async_update_entity_platform(
            row.entity_id,
            DOMAIN,
            new_config_entry_id=entry.entry_id,
            new_unique_id=(
                new_unique_id if new_unique_id != row.unique_id else UNDEFINED
            ),
            new_device_id=target_device_id,
        )
        moved.append(row.entity_id)

    if moved:
        _LOGGER.info(
            "Migration from 4.x: moved %s to entry '%s'", ", ".join(moved), entry.title
        )

    return moved


@callback
def async_remove_unprovided_entities(
    hass: HomeAssistant, entry: ConfigEntry, moved: dict[str, list[str]]
) -> None:
    """Remove moved rows that this integration does not provide for a bound device.

    4.x created every switch, also for features the unit does not have. After
    the platforms are set up, a moved row without an entity is such a switch.
    Only bound devices are checked, because an unbound device has no entities
    at all yet.
    """
    if not moved:
        return

    ent_reg = er.async_get(hass)
    bound: Mapping[str, Any] = entry.runtime_data or {}

    def _cleanup() -> None:
        loaded = entity_sources(hass)
        for mac, entity_ids in moved.items():
            if mac not in bound:
                continue
            for entity_id in entity_ids:
                if entity_id not in loaded and ent_reg.async_get(entity_id):
                    _LOGGER.info(
                        "Migration from 4.x: removing %s, this device does not"
                        " provide it",
                        entity_id,
                    )
                    ent_reg.async_remove(entity_id)

    if hass.state is CoreState.running:
        _cleanup()
        return

    @callback
    def _on_started(_event: Event) -> None:
        _cleanup()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _on_started)
