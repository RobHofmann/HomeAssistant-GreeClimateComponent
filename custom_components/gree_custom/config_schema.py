"""Schemas for the Gree integration.

`CONFIG_SCHEMA` validates the `gree_custom:` block in `configuration.yaml`,
fills the defaults and hands one item per config entry to the import flow.
The rest of the module holds the form schemas that the config flow shows.
"""

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import probatio
else:
    try:
        import probatio
    except ImportError:
        import voluptuous as probatio

from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN, SensorDeviceClass
from homeassistant.const import (
    CONF_DISCOVERY,
    CONF_EMAIL,
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_REGION,
    CONF_SCAN_INTERVAL,
    CONF_TIMEOUT,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import section
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .aiogree.api import GreeDiscoveredDevice, GreeProp
from .aiogree.cipher import EncryptionVersion
from .aiogree.cloud_api import GreeRegion
from .aiogree.device import GreeDevice
from .aiogree.helpers import gree_extract_macs
from .const import (
    ATTR_EXTERNAL_HUMIDITY_SENSOR,
    ATTR_EXTERNAL_TEMPERATURE_SENSOR,
    ATTR_FEATURES_TO_PROP_MAP,
    CONF_CLOUD,
    CONF_DEVICE_CONNECTION,
    CONF_DEVICE_CONNECTION_CLOUD,
    CONF_DEVICE_CONNECTION_LOCAL,
    CONF_DEVICE_OPTIONS,
    CONF_DEVICES,
    CONF_DISABLE_AVAILABLE_CHECK,
    CONF_ENCRYPTION_KEY,
    CONF_ENCRYPTION_VERSION,
    CONF_EXTRA_SCAN_HOSTS,
    CONF_EXTRA_SCAN_NETWORKS,
    CONF_FAN_MODES,
    CONF_FEATURES,
    CONF_HVAC_MODES,
    CONF_MAC_CONTROLLER_CLOUD,
    CONF_MAC_CONTROLLER_LOCAL,
    CONF_MAX_ONLINE_ATTEMPTS,
    CONF_PREFER_CLOUD,
    CONF_RESTORE_STATES,
    CONF_SWING_HORIZONTAL_MODES,
    CONF_SWING_MODES,
    CONF_TEMPERATURE_STEP,
    CONF_UID,
    DEFAULT_CONNECTION_MAX_ATTEMPTS,
    DEFAULT_CONNECTION_TIMEOUT,
    DEFAULT_DEVICE_PORT,
    DEFAULT_DEVICE_UID,
    DEFAULT_DISABLE_AVAILABLE_CHECK,
    DEFAULT_ENCRYPTION_KEY,
    DEFAULT_ENCRYPTION_VERSION,
    DEFAULT_FAN_MODES,
    DEFAULT_HVAC_MODES,
    DEFAULT_PREFER_CLOUD,
    DEFAULT_RESTORE_STATES,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SWING_HORIZONTAL_MODES,
    DEFAULT_SWING_MODES,
    DEFAULT_TARGET_TEMP_STEP,
    DOMAIN,
    ENCRYPTION_VERSION_AUTO,
    GATTR_FEAT_QUIET_MODE,
    GATTR_FEAT_TURBO,
    MIN_SCAN_INTERVAL,
)
from .helpers import get_entity_ids_from_unique_ids

HEX_CHARACTERS = "0123456789abcdef"
VALID_MAC_LENGTHS = (12, 14)

VALID_ENCRYPTION_VERSIONS = [
    ENCRYPTION_VERSION_AUTO,
    *(str(version.value) for version in EncryptionVersion),
]
VALID_HVAC_MODES = [str(mode) for mode in DEFAULT_HVAC_MODES]
VALID_FAN_MODES = [*DEFAULT_FAN_MODES, GATTR_FEAT_TURBO, GATTR_FEAT_QUIET_MODE]
VALID_FEATURES = list(ATTR_FEATURES_TO_PROP_MAP)

MIN_TARGET_TEMP_STEP = 0.5
MAX_TARGET_TEMP_STEP = 5


def _clean_mac(value: Any, field: str) -> str:
    """Strip the separators from a MAC address and check that it is valid."""
    mac = str(value).replace(":", "").replace("-", "").strip().lower()

    if len(mac) not in VALID_MAC_LENGTHS or any(c not in HEX_CHARACTERS for c in mac):
        raise probatio.Invalid(
            f"{field} must be a MAC address of 12 or 14 hex characters "
            f"without separators, got '{value}'"
        )

    return mac


def _mac_controller_local(value: Any) -> str:
    """Validate the MAC address of the local controller."""
    return _clean_mac(value, CONF_MAC_CONTROLLER_LOCAL)


def _mac_controller_cloud(value: Any) -> str:
    """Validate the MAC address of the cloud controller."""
    return _clean_mac(value, CONF_MAC_CONTROLLER_CLOUD)


def _encryption_version(value: Any) -> str:
    """Validate the encryption version and return it as a string."""
    version = str(value)

    if version not in VALID_ENCRYPTION_VERSIONS:
        raise probatio.Invalid(
            f"{CONF_ENCRYPTION_VERSION} must be one of "
            f"{VALID_ENCRYPTION_VERSIONS}, got '{value}'"
        )

    return version


def _target_temp_step(value: Any) -> float:
    """Validate the target temperature step and return it as a float."""
    step = probatio.Coerce(float)(value)

    if step < MIN_TARGET_TEMP_STEP or step > MAX_TARGET_TEMP_STEP:
        raise probatio.Invalid(
            f"{CONF_TEMPERATURE_STEP} must be between "
            f"{MIN_TARGET_TEMP_STEP} and {MAX_TARGET_TEMP_STEP}, got {step}"
        )

    if step * 2 != int(step * 2):
        raise probatio.Invalid(
            f"{CONF_TEMPERATURE_STEP} must be a multiple of 0.5, got {step}"
        )

    return step


CLOUD_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_EMAIL): cv.string,
        probatio.Required(CONF_PASSWORD): cv.string,
        probatio.Required(CONF_REGION): probatio.In(
            [region.value for region in GreeRegion]
        ),
    }
)

CONNECTION_LOCAL_SCHEMA = probatio.Schema(
    {
        probatio.Optional(CONF_MAC_CONTROLLER_LOCAL): _mac_controller_local,
        probatio.Required(CONF_HOST): cv.string,
        probatio.Optional(CONF_PORT, default=DEFAULT_DEVICE_PORT): cv.port,
        probatio.Optional(
            CONF_TIMEOUT, default=DEFAULT_CONNECTION_TIMEOUT
        ): cv.positive_int,
        probatio.Optional(
            CONF_ENCRYPTION_VERSION, default=DEFAULT_ENCRYPTION_VERSION
        ): _encryption_version,
        probatio.Optional(
            CONF_MAX_ONLINE_ATTEMPTS, default=DEFAULT_CONNECTION_MAX_ATTEMPTS
        ): cv.positive_int,
    }
)

CONNECTION_CLOUD_SCHEMA = probatio.Schema(
    {
        probatio.Optional(CONF_PREFER_CLOUD, default=DEFAULT_PREFER_CLOUD): cv.boolean,
        probatio.Optional(CONF_MAC_CONTROLLER_CLOUD): _mac_controller_cloud,
    }
)

CONNECTION_SCHEMA = probatio.Schema(
    {
        probatio.Optional(
            CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
        ): probatio.All(probatio.Coerce(int), probatio.Range(min=MIN_SCAN_INTERVAL)),
        probatio.Optional(
            CONF_DISABLE_AVAILABLE_CHECK, default=DEFAULT_DISABLE_AVAILABLE_CHECK
        ): cv.boolean,
        probatio.Optional(
            CONF_ENCRYPTION_KEY, default=DEFAULT_ENCRYPTION_KEY
        ): cv.string,
        probatio.Optional(CONF_UID, default=DEFAULT_DEVICE_UID): cv.positive_int,
        probatio.Optional(CONF_DEVICE_CONNECTION_LOCAL): CONNECTION_LOCAL_SCHEMA,
        probatio.Optional(CONF_DEVICE_CONNECTION_CLOUD): CONNECTION_CLOUD_SCHEMA,
    }
)

OPTIONS_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_NAME): cv.string,
        probatio.Optional(CONF_HVAC_MODES): probatio.All(
            cv.ensure_list, [probatio.In(VALID_HVAC_MODES)]
        ),
        probatio.Optional(CONF_FAN_MODES): probatio.All(
            cv.ensure_list, [probatio.In(VALID_FAN_MODES)]
        ),
        probatio.Optional(CONF_SWING_MODES): probatio.All(
            cv.ensure_list, [probatio.In(DEFAULT_SWING_MODES)]
        ),
        probatio.Optional(CONF_SWING_HORIZONTAL_MODES): probatio.All(
            cv.ensure_list, [probatio.In(DEFAULT_SWING_HORIZONTAL_MODES)]
        ),
        probatio.Optional(CONF_FEATURES): probatio.All(
            cv.ensure_list, [probatio.In(VALID_FEATURES)]
        ),
        probatio.Optional(CONF_TEMPERATURE_STEP): _target_temp_step,
        probatio.Optional(ATTR_EXTERNAL_TEMPERATURE_SENSOR): cv.entity_id,
        probatio.Optional(ATTR_EXTERNAL_HUMIDITY_SENSOR): cv.entity_id,
        probatio.Optional(
            CONF_RESTORE_STATES, default=DEFAULT_RESTORE_STATES
        ): cv.boolean,
    }
)


def _add_connection_block(value: Any) -> dict[str, Any]:
    """Give a device an empty connection block when it has none."""
    if not isinstance(value, dict):
        raise probatio.Invalid("a device must be a mapping")

    if value.get(CONF_DEVICE_CONNECTION) is None:
        return {**value, CONF_DEVICE_CONNECTION: {}}

    return value


DEVICE_SCHEMA = probatio.All(
    _add_connection_block,
    probatio.Schema(
        {
            probatio.Required(CONF_DEVICE_CONNECTION): CONNECTION_SCHEMA,
            probatio.Required(CONF_DEVICE_OPTIONS): OPTIONS_SCHEMA,
        }
    ),
)


def _finish_devices(value: dict[str, Any]) -> dict[str, Any]:
    """Re-key the devices on the normalized MAC and fill the controller MACs.

    The key goes through `gree_extract_macs()`, the same function discovery
    uses, so it accepts separators, upper case, a VRF main device MAC that
    ends in `00`, and the `<mac>@<controller mac>` form for a VRF sub-device.
    A given `mac_controller_local` or `mac_controller_cloud` wins over the
    derived value.
    """
    devices: dict[str, Any] = {}

    for raw_key, device in value.items():
        mac, mac_controller = gree_extract_macs(str(raw_key))
        _clean_mac(mac, "device MAC address")

        if mac in devices:
            raise probatio.Invalid(f"device {mac} is listed more than once")

        connection = dict(device[CONF_DEVICE_CONNECTION])

        local = connection.get(CONF_DEVICE_CONNECTION_LOCAL)
        if local is None:
            connection[CONF_DEVICE_CONNECTION_LOCAL] = {}
        else:
            local = {CONF_MAC_CONTROLLER_LOCAL: mac_controller, **local}
            if len(local[CONF_MAC_CONTROLLER_LOCAL]) != 12:
                raise probatio.Invalid(
                    f"device {mac} is a VRF sub-device and its local controller "
                    "is another unit. Write the key as '<mac>@<controller mac>' "
                    f"or set {CONF_DEVICE_CONNECTION}.{CONF_DEVICE_CONNECTION_LOCAL}."
                    f"{CONF_MAC_CONTROLLER_LOCAL} to the 12 character MAC of the "
                    "unit that holds the network connection"
                )
            connection[CONF_DEVICE_CONNECTION_LOCAL] = local

        cloud = connection.get(CONF_DEVICE_CONNECTION_CLOUD)
        if cloud is None:
            connection[CONF_DEVICE_CONNECTION_CLOUD] = {
                CONF_PREFER_CLOUD: DEFAULT_PREFER_CLOUD,
                CONF_MAC_CONTROLLER_CLOUD: "",
            }
        else:
            connection[CONF_DEVICE_CONNECTION_CLOUD] = {
                CONF_MAC_CONTROLLER_CLOUD: mac_controller,
                **cloud,
            }

        devices[mac] = {**device, CONF_DEVICE_CONNECTION: connection}

    return devices


def _validate_item(value: dict[str, Any]) -> dict[str, Any]:
    """Check that every device of one item can be reached."""
    devices: dict[str, Any] = value[CONF_DEVICES]

    if not devices:
        raise probatio.Invalid(f"{CONF_DEVICES} must hold at least one device")

    has_account = value.get(CONF_CLOUD) is not None

    for mac, device in devices.items():
        connection = device[CONF_DEVICE_CONNECTION]
        has_local = bool(connection[CONF_DEVICE_CONNECTION_LOCAL].get(CONF_HOST))
        has_cloud = bool(
            connection[CONF_DEVICE_CONNECTION_CLOUD].get(CONF_MAC_CONTROLLER_CLOUD)
        )

        if not has_local and not (has_account and has_cloud):
            raise probatio.Invalid(
                f"device {mac} cannot be reached: it needs a "
                f"{CONF_DEVICE_CONNECTION}.{CONF_DEVICE_CONNECTION_LOCAL} block, "
                f"or a top level {CONF_CLOUD} account plus a "
                f"{CONF_DEVICE_CONNECTION}.{CONF_DEVICE_CONNECTION_CLOUD} block"
            )

    return value


def _validate_items(value: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Check that the items do not share an entry."""
    local_only_items = 0
    emails: set[str] = set()

    for item in value:
        cloud = item.get(CONF_CLOUD)

        if cloud is None:
            local_only_items += 1
            if local_only_items > 1:
                raise probatio.Invalid(
                    f"only one item may leave out the {CONF_CLOUD} block, "
                    "because all local-only devices share one config entry"
                )
            continue

        email = cloud[CONF_EMAIL]
        if email in emails:
            raise probatio.Invalid(
                f"the {CONF_CLOUD} account {email} is used by more than one item"
            )
        emails.add(email)

    return value


ITEM_SCHEMA = probatio.All(
    probatio.Schema(
        {
            probatio.Optional(CONF_CLOUD): CLOUD_SCHEMA,
            probatio.Required(CONF_DEVICES): probatio.All(
                {str: DEVICE_SCHEMA},
                _finish_devices,
            ),
        }
    ),
    _validate_item,
)

CONFIG_SCHEMA = probatio.Schema(
    {DOMAIN: probatio.All(cv.ensure_list, [ITEM_SCHEMA], _validate_items)},
    extra=probatio.ALLOW_EXTRA,
)


# Forms for the config flow

SETUP_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_DISCOVERY, default=["cloud", "local"]): SelectSelector(
            SelectSelectorConfig(
                options=["cloud", "local"],
                multiple=True,
                translation_key=CONF_DISCOVERY,
            )
        )
    }
)


def setup_cloud_schema(defaults_values: dict | None = None) -> probatio.Schema:
    """Build the form that asks for the Gree cloud account."""
    defaults = defaults_values or {}

    return probatio.Schema(
        {
            probatio.Required(
                CONF_EMAIL,
                default=defaults.get(CONF_EMAIL, ""),
            ): str,
            probatio.Required(
                CONF_PASSWORD,
                default=defaults.get(CONF_PASSWORD, ""),
            ): str,
            probatio.Required(
                CONF_REGION,
                default=defaults.get(CONF_REGION),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=[region.value for region in GreeRegion],
                    multiple=False,
                )
            ),
        }
    )


def setup_local_schema(default_values: dict | None = None) -> probatio.Schema:
    """Build the form that asks for extra networks and hosts to scan."""
    defaults = default_values or {}

    return probatio.Schema(
        {
            probatio.Optional(
                CONF_EXTRA_SCAN_NETWORKS,
                description={
                    "suggested_value": defaults.get(CONF_EXTRA_SCAN_NETWORKS, [])
                },
            ): TextSelector(TextSelectorConfig(multiple=True, multiline=False)),
            probatio.Optional(
                CONF_EXTRA_SCAN_HOSTS,
                description={
                    "suggested_value": defaults.get(CONF_EXTRA_SCAN_HOSTS, [])
                },
            ): TextSelector(TextSelectorConfig(multiple=True, multiline=False)),
        }
    )


def setup_picker_schema(
    default: list[str], options: dict[str, GreeDiscoveredDevice]
) -> probatio.Schema:
    """Build the form that lets the user pick which devices to set up."""
    return probatio.Schema(
        {
            probatio.Required(CONF_DEVICES, default=default): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value=m, label=d.friendly_name)
                        for m, d in options.items()
                    ],
                    multiple=True,
                )
            )
        }
    )


def setup_device_connection_options_schema(
    device_info: GreeDiscoveredDevice, default_values: dict | None = None
) -> probatio.Schema:
    """Build the form that asks how to connect to one device."""
    defaults: dict = default_values or {}
    defaults_local = defaults.get(CONF_DEVICE_CONNECTION_LOCAL, {})
    defaults_cloud = defaults.get(CONF_DEVICE_CONNECTION_CLOUD, {})

    return probatio.Schema(
        {
            probatio.Required(
                CONF_SCAN_INTERVAL,
                default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): probatio.All(
                probatio.Coerce(int), probatio.Range(min=MIN_SCAN_INTERVAL)
            ),
            probatio.Required(
                CONF_DISABLE_AVAILABLE_CHECK,
                default=defaults.get(
                    CONF_DISABLE_AVAILABLE_CHECK,
                    DEFAULT_DISABLE_AVAILABLE_CHECK,
                ),
            ): cv.boolean,
            probatio.Optional(
                CONF_ENCRYPTION_KEY,
                default=(
                    defaults.get(CONF_ENCRYPTION_KEY)
                    or device_info.key
                    or DEFAULT_ENCRYPTION_KEY
                ),
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
            probatio.Required(
                CONF_UID,
                default=defaults.get(CONF_UID, device_info.user_id),
            ): cv.positive_int,
            probatio.Required(CONF_DEVICE_CONNECTION_LOCAL): section(
                probatio.Schema(
                    {
                        probatio.Optional(
                            CONF_MAC_CONTROLLER_LOCAL,
                            default=(
                                defaults_local.get(CONF_MAC_CONTROLLER_LOCAL)
                                or device_info.mac_controller_local
                            ),
                        ): str,
                        probatio.Optional(
                            CONF_HOST,
                            default=(
                                defaults_local.get(CONF_HOST) or device_info.host or ""
                            ),
                        ): str,
                        probatio.Optional(
                            CONF_PORT,
                            default=(
                                defaults_local.get(CONF_PORT)
                                or device_info.port
                                or DEFAULT_DEVICE_PORT
                            ),
                        ): cv.port,
                        probatio.Required(
                            CONF_TIMEOUT,
                            default=defaults_local.get(
                                CONF_TIMEOUT, DEFAULT_CONNECTION_TIMEOUT
                            ),
                        ): cv.positive_int,
                        probatio.Required(
                            CONF_ENCRYPTION_VERSION,
                            default=defaults_local.get(
                                CONF_ENCRYPTION_VERSION, DEFAULT_ENCRYPTION_VERSION
                            ),
                        ): SelectSelector(
                            SelectSelectorConfig(
                                translation_key=CONF_ENCRYPTION_VERSION,
                                options=[
                                    ENCRYPTION_VERSION_AUTO,
                                    *(
                                        str(version.value)
                                        for version in EncryptionVersion
                                    ),
                                ],
                                mode=SelectSelectorMode.DROPDOWN,
                            )
                        ),
                        probatio.Required(
                            CONF_MAX_ONLINE_ATTEMPTS,
                            default=defaults_local.get(
                                CONF_MAX_ONLINE_ATTEMPTS,
                                DEFAULT_CONNECTION_MAX_ATTEMPTS,
                            ),
                        ): cv.positive_int,
                    }
                )
            ),
            probatio.Required(CONF_DEVICE_CONNECTION_CLOUD): section(
                probatio.Schema(
                    {
                        probatio.Required(
                            CONF_PREFER_CLOUD,
                            default=defaults_cloud.get(
                                CONF_PREFER_CLOUD,
                                DEFAULT_PREFER_CLOUD,
                            ),
                        ): cv.boolean,
                        probatio.Optional(
                            CONF_MAC_CONTROLLER_CLOUD,
                            default=defaults_cloud.get(CONF_MAC_CONTROLLER_CLOUD)
                            or device_info.mac_controller_mqtt,
                        ): str,
                    }
                )
            ),
        }
    )


def setup_device_options_schema(  # noqa: C901
    hass: HomeAssistant, device: GreeDevice, default_values: Mapping | None
) -> probatio.Schema:
    """Build the form that asks for the options of one device."""
    defaults = default_values or {}

    schema: dict = {}
    schema.update(
        {
            probatio.Required(
                CONF_NAME,
                default=defaults.get(CONF_NAME, device.name),
            ): str
        }
    )

    if device.supports_property(GreeProp.OP_MODE):
        schema.update(
            {
                probatio.Optional(
                    CONF_HVAC_MODES,
                    default=defaults.get(CONF_HVAC_MODES, DEFAULT_HVAC_MODES),
                ): SelectSelector(
                    config=SelectSelectorConfig(
                        options=DEFAULT_HVAC_MODES,
                        multiple=True,
                        translation_key=CONF_HVAC_MODES,
                    )
                ),
            }
        )

    fan_mapping = {
        GreeProp.FAN_SPEED: DEFAULT_FAN_MODES,
        GreeProp.FEAT_TURBO_MODE: [GATTR_FEAT_TURBO],
        GreeProp.FEAT_QUIET_MODE: [GATTR_FEAT_QUIET_MODE],
    }
    valid_fan_modes: list[str] = []
    for prop, modes in fan_mapping.items():
        if device.supports_property(prop):
            valid_fan_modes.extend(modes)

    if valid_fan_modes:
        schema.update(
            {
                probatio.Optional(
                    CONF_FAN_MODES,
                    default=defaults.get(CONF_FAN_MODES, valid_fan_modes),
                ): SelectSelector(
                    config=SelectSelectorConfig(
                        options=valid_fan_modes,
                        multiple=True,
                        translation_key=CONF_FAN_MODES,
                    )
                ),
            }
        )

    if device.supports_property(GreeProp.SWING_VERTICAL):
        schema.update(
            {
                probatio.Optional(
                    CONF_SWING_MODES,
                    default=defaults.get(CONF_SWING_MODES, DEFAULT_SWING_MODES),
                ): SelectSelector(
                    config=SelectSelectorConfig(
                        options=DEFAULT_SWING_MODES,
                        multiple=True,
                        translation_key=CONF_SWING_MODES,
                    )
                ),
            }
        )

    if device.supports_property(GreeProp.SWING_HORIZONTAL):
        schema.update(
            {
                probatio.Optional(
                    CONF_SWING_HORIZONTAL_MODES,
                    default=defaults.get(
                        CONF_SWING_HORIZONTAL_MODES, DEFAULT_SWING_HORIZONTAL_MODES
                    ),
                ): SelectSelector(
                    config=SelectSelectorConfig(
                        options=DEFAULT_SWING_HORIZONTAL_MODES,
                        multiple=True,
                        translation_key=CONF_SWING_HORIZONTAL_MODES,
                    )
                ),
            }
        )

    valid_features = []
    for feat, props in ATTR_FEATURES_TO_PROP_MAP.items():
        if all(device.supports_property(p) for p in props):
            valid_features.append(feat)

    if valid_features:
        schema.update(
            {
                probatio.Optional(
                    CONF_FEATURES,
                    default=defaults.get(CONF_FEATURES, valid_features),
                ): SelectSelector(
                    config=SelectSelectorConfig(
                        options=valid_features,
                        multiple=True,
                        translation_key=CONF_FEATURES,
                    )
                )
            }
        )

    if device.supports_property(GreeProp.TARGET_TEMPERATURE):
        schema.update(
            {
                probatio.Required(
                    CONF_TEMPERATURE_STEP,
                    default=defaults.get(
                        CONF_TEMPERATURE_STEP, DEFAULT_TARGET_TEMP_STEP
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_TARGET_TEMP_STEP,
                        max=MAX_TARGET_TEMP_STEP,
                        step=0.5,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="ºC",
                    )
                )
            }
        )

    schema.update(
        {
            probatio.Optional(
                ATTR_EXTERNAL_TEMPERATURE_SENSOR,
                description={
                    "suggested_value": defaults.get(
                        ATTR_EXTERNAL_TEMPERATURE_SENSOR, ""
                    )
                },
            ): EntitySelector(
                config=EntitySelectorConfig(
                    domain=SENSOR_DOMAIN,
                    device_class=SensorDeviceClass.TEMPERATURE,
                    multiple=False,
                    exclude_entities=get_entity_ids_from_unique_ids(
                        hass,
                        SENSOR_DOMAIN,
                        [
                            f"{device.mac_address}_indoor_temperature",
                            f"{device.mac_address}_outdoor_temperature",
                        ],
                    ),
                )
            ),
            probatio.Optional(
                ATTR_EXTERNAL_HUMIDITY_SENSOR,
                description={
                    "suggested_value": defaults.get(ATTR_EXTERNAL_HUMIDITY_SENSOR, "")
                },
            ): EntitySelector(
                config=EntitySelectorConfig(
                    domain=SENSOR_DOMAIN,
                    device_class=SensorDeviceClass.HUMIDITY,
                    multiple=False,
                    exclude_entities=get_entity_ids_from_unique_ids(
                        hass,
                        SENSOR_DOMAIN,
                        [
                            f"{device.mac_address}_room_humidity",
                        ],
                    ),
                )
            ),
            probatio.Required(
                CONF_RESTORE_STATES,
                default=defaults.get(CONF_RESTORE_STATES, DEFAULT_RESTORE_STATES),
            ): cv.boolean,
        }
    )

    return probatio.Schema(schema)
