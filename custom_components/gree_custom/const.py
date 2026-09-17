"""Constants for the Gree integration."""

from homeassistant.components.climate import (
    HVACMode,  # pyright: ignore[reportPrivateImportUsage]
)
from homeassistant.const import UnitOfTemperature

from .aiogree.api import (
    FanSpeed,
    GreeProp,
    HorizontalSwingMode,
    OperationMode,
    TemperatureUnits,
    VerticalSwingMode,
)

DOMAIN = "gree_custom"

CURRENT_CONF_VERSION = 3

CONFENTRY_ID_LOCAL_ONLY = "local_only"
CONF_EXTRA_SCAN_NETWORKS = "extra_scan_networks"
CONF_EXTRA_SCAN_HOSTS = "extra_scan_hosts"
CONF_DISCOVERY_PREFS_KEY = DOMAIN + "_discovery_prefs"
CONF_DISCOVERY_PREFS_VERSION = 1
CONF_CLOUD = "cloud"

CONF_MAC_CONTROLLER_LOCAL = "mac_controller_local"
CONF_MAC_CONTROLLER_CLOUD = "mac_controller_cloud"
CONF_ADVANCED = "advanced"
CONF_DEVICE_CONNECTION = "connection"
CONF_DEVICE_CONNECTION_LOCAL = "local"
CONF_DEVICE_CONNECTION_CLOUD = "cloud"
CONF_DEVICE_OPTIONS = "options"
CONF_ALL_DEVICE_CONNECTIONS = "device_connections"
CONF_ALL_DEVICE_OPTIONS = "device_options"
CONF_UID = "uid"
CONF_ENCRYPTION_KEY = "encryption_key"
CONF_ENCRYPTION_VERSION = "encryption_version"
CONF_DISABLE_AVAILABLE_CHECK = "disable_available_check"
CONF_MAX_ONLINE_ATTEMPTS = "max_online_attempts"
CONF_RESTORE_STATES = "restore_states"
CONF_DEVICES = "devices"
CONF_HVAC_MODES = "hvac_modes"
CONF_FAN_MODES = "fan_modes"
CONF_SWING_MODES = "swing_modes"
CONF_SWING_HORIZONTAL_MODES = "swing_horizontal_modes"
CONF_FEATURES = "features"
CONF_TEMPERATURE_STEP = "target_temp_step"
CONF_PREFER_CLOUD = "prefer_cloud"

DEFAULT_TARGET_TEMP_STEP = 1
ENCRYPTION_VERSION_AUTO = "0"
DEFAULT_ENCRYPTION_VERSION = ENCRYPTION_VERSION_AUTO
DEFAULT_ENCRYPTION_KEY = ""
DEFAULT_DISABLE_AVAILABLE_CHECK = False
DEFAULT_RESTORE_STATES = True
MIN_SCAN_INTERVAL = 5
DEFAULT_SCAN_INTERVAL = 60
DEFAULT_PREFER_CLOUD = False

DEFAULT_DEVICE_UID = 0
DEFAULT_DEVICE_PORT = 7000
DEFAULT_CONNECTION_MAX_ATTEMPTS = 3
DEFAULT_CONNECTION_TIMEOUT = 10
DEFAULT_DISCOVERY_TIMEOUT = 5

MAX_UNICAST_SCAN_HOSTS = 65536

# OPTIONAL FEATURES/MODES
# use the device beeper on commands
GATTR_BEEPER = "beeper"
# controls the state of the fresh air valve (not available on all units)
GATTR_FEAT_FRESH_AIR = "air"
# "Blow" or "X-Fan", this function keeps the fan running for a while after shutting down. Only usable in Dry and Cool mode
GATTR_FEAT_XFAN = "xfan"
# sleep mode, which gradually changes the temperature in Cool, Heat and Dry mode
GATTR_FEAT_SLEEP_MODE = "sleep"
# Anti Freeze maintain the room temperature steadily at 8°C and prevent the room from freezing by heating operation when nobody is at home for long in severe winter
GATTR_FEAT_SMART_HEAT_8C = "eightdegheat"
# turns all indicators and the display on the unit on or off
GATTR_FEAT_LIGHT = "lights"
# controls Health ("Cold plasma") mode
GATTR_FEAT_HEALTH = "health"
# prevents the wind from blowing directly on people
GATTR_ANTI_DIRECT_BLOW = "anti_direct_blow"
# energy saving mode
GATTR_FEAT_ENERGY_SAVING = "powersave"
# use light sensor for unit display
GATTR_FEAT_SENSOR_LIGHT = "light_sensor"
# Quiet mode which slows down the fan to its most quiet speed. Not available in Dry and Fan mode.
GATTR_FEAT_QUIET_MODE = "quiet"
# Turbo mode sets fan speed to the maximum. Fan speed cannot be changed while active and only available in Dry and Cool mode
GATTR_FEAT_TURBO = "turbo"
# Humidity Control. Allows dry mode under cooling operation
GATTR_FEAT_HUMIDITY = "humidity_control"
# Humidity Control Target. Sets humidity target for humidity control
GATTR_FEAT_HUMIDITY_TARGET = "humidity_control_target"

GATTR_TEMP_UNITS = "temperature_units"
GATTR_INDOOR_TEMPERATURE = "indoor_temperature"
GATTR_OUTDOOR_TEMPERATURE = "outdoor_temperature"
GATTR_HUMIDITY = "room_humidity"

GATTR_FAULTS = "faults"

ATTR_EXTERNAL_TEMPERATURE_SENSOR = "external_temperature_sensor"
ATTR_EXTERNAL_HUMIDITY_SENSOR = "external_humidity_sensor"
ATTR_AUTO_XFAN = "auto_xfan"
ATTR_AUTO_LIGHT = "auto_light"

ATTR_SVC_PROPS = "prop_list"

# Map each feature constant to its corresponding GreeProp
ATTR_FEATURES_TO_PROP_MAP: dict[str, list[GreeProp]] = {
    GATTR_BEEPER: [GreeProp.BEEPER, GreeProp.BEEPER_NEW],
    GATTR_FEAT_FRESH_AIR: [GreeProp.FEAT_FRESH_AIR],
    GATTR_FEAT_XFAN: [GreeProp.FEAT_XFAN],
    GATTR_FEAT_SLEEP_MODE: [
        GreeProp.FEAT_SLEEP_MODE,
        GreeProp.FEAT_SLEEP_MODE_TYPE,
    ],
    GATTR_FEAT_SMART_HEAT_8C: [GreeProp.FEAT_SMART_HEAT_8C],
    GATTR_FEAT_LIGHT: [GreeProp.FEAT_LIGHT],
    GATTR_FEAT_SENSOR_LIGHT: [GreeProp.FEAT_LIGHT, GreeProp.FEAT_SENSOR_LIGHT],
    GATTR_FEAT_HEALTH: [GreeProp.FEAT_HEALTH],
    GATTR_ANTI_DIRECT_BLOW: [GreeProp.FEAT_ANTI_DIRECT_BLOW],
    GATTR_FEAT_ENERGY_SAVING: [GreeProp.FEAT_ENERGY_SAVING],
    GATTR_FEAT_HUMIDITY: [GreeProp.FEATURE_HUMIDITY_CONTROL],
}

ATTR_SENSORS_TO_PROP_MAP: dict[str, list[GreeProp]] = {
    GATTR_INDOOR_TEMPERATURE: [
        GreeProp.SENSOR_INDOOR_TEMPERATURE_1,
        GreeProp.SENSOR_INDOOR_TEMPERATURE_2,
        GreeProp.SENSOR_INDOOR_TEMPERATURE_3,
    ],
    GATTR_OUTDOOR_TEMPERATURE: [
        GreeProp.SENSOR_OUTSIDE_TEMPERATURE_1,
        GreeProp.SENSOR_OUTSIDE_TEMPERATURE_2,
    ],
    GATTR_HUMIDITY: [GreeProp.SENSOR_HUMIDITY_1, GreeProp.SENSOR_HUMIDITY_2],
    GATTR_FAULTS: [GreeProp.SENSOR_FAULT],
}

CONF_TO_PROP_FEATURE_MAP: dict[str, list[GreeProp]] = {
    GATTR_TEMP_UNITS: [GreeProp.TARGET_TEMPERATURE_UNIT],
    # SENSORS
    **ATTR_SENSORS_TO_PROP_MAP,
    # FEATURES
    **ATTR_FEATURES_TO_PROP_MAP,
}


# HVAC modes - these come from Home Assistant and are standard
DEFAULT_HVAC_MODES = [
    HVACMode.AUTO,
    HVACMode.COOL,
    HVACMode.DRY,
    HVACMode.FAN_ONLY,
    HVACMode.HEAT,
    HVACMode.OFF,
]

HVAC_MODES_HA_TO_GREE = {
    HVACMode.AUTO: OperationMode.auto,
    HVACMode.COOL: OperationMode.cool,
    HVACMode.DRY: OperationMode.dry,
    HVACMode.FAN_ONLY: OperationMode.fan,
    HVACMode.HEAT: OperationMode.heat,
}
HVAC_MODES_GREE_TO_HA = {
    OperationMode.auto: HVACMode.AUTO,
    OperationMode.cool: HVACMode.COOL,
    OperationMode.dry: HVACMode.DRY,
    OperationMode.fan: HVACMode.FAN_ONLY,
    OperationMode.heat: HVACMode.HEAT,
}

DEFAULT_FAN_MODES = [
    FanSpeed.auto.name,
    FanSpeed.low.name,
    FanSpeed.medium_low.name,
    FanSpeed.medium.name,
    FanSpeed.medium_high.name,
    FanSpeed.high.name,
    # GATTR_FEAT_TURBO,  # Special mode on Gree device
    # GATTR_FEAT_QUIET_MODE,  # Special mode on Gree device
]

DEFAULT_SWING_MODES = [
    VerticalSwingMode.default.name,
    VerticalSwingMode.full_swing.name,
    VerticalSwingMode.fixed_upper.name,
    VerticalSwingMode.fixed_upper_middle.name,
    VerticalSwingMode.fixed_middle.name,
    VerticalSwingMode.fixed_lower_middle.name,
    VerticalSwingMode.fixed_lower.name,
    VerticalSwingMode.swing_lower.name,
    VerticalSwingMode.swing_lower_middle.name,
    VerticalSwingMode.swing_middle.name,
    VerticalSwingMode.swing_upper_middle.name,
    VerticalSwingMode.swing_upper.name,
]

DEFAULT_SWING_HORIZONTAL_MODES = [
    HorizontalSwingMode.default.name,
    HorizontalSwingMode.full_swing.name,
    HorizontalSwingMode.left.name,
    HorizontalSwingMode.left_center.name,
    HorizontalSwingMode.center.name,
    HorizontalSwingMode.right_center.name,
    HorizontalSwingMode.right.name,
]

DEFAULT_SUPPORTED_FEATURES = [
    GATTR_BEEPER,
    GATTR_FEAT_FRESH_AIR,
    GATTR_FEAT_XFAN,
    GATTR_FEAT_SLEEP_MODE,
    GATTR_FEAT_SMART_HEAT_8C,
    GATTR_FEAT_LIGHT,
    GATTR_FEAT_HEALTH,
    GATTR_ANTI_DIRECT_BLOW,
    GATTR_FEAT_ENERGY_SAVING,
    GATTR_FEAT_SENSOR_LIGHT,
    GATTR_FAULTS,
]

UNITS_GREE_TO_HA = {
    TemperatureUnits.C: UnitOfTemperature.CELSIUS,
    TemperatureUnits.F: UnitOfTemperature.FAHRENHEIT,
}
