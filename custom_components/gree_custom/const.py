"""Constants for the Gree integration."""

from homeassistant.components.climate import HVACMode
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

CONF_ADVANCED = "advanced"
CONF_UID = "uid"
CONF_ENCRYPTION_KEY = "encryption_key"
CONF_ENCRYPTION_VERSION = "encryption_version"
CONF_DISABLE_AVAILABLE_CHECK = "disable_available_check"
CONF_MAX_ONLINE_ATTEMPTS = "max_online_attempts"
CONF_RESTORE_STATES = "restore_states"
CONF_DEVICES = "devices"
CONF_DEV_NAME = "device_name"
CONF_HVAC_MODES = "hvac_modes"
CONF_FAN_MODES = "fan_modes"
CONF_SWING_MODES = "swing_modes"
CONF_SWING_HORIZONTAL_MODES = "swing_horizontal_modes"
CONF_FEATURES = "features"
CONF_TEMPERATURE_STEP = "target_temp_step"

DEFAULT_TARGET_TEMP_STEP = 1
DEFAULT_ENCRYPTION_VERSION = None


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

GATTR_TEMP_UNITS = "temperature_units"
GATTR_INDOOR_TEMPERATURE = "indoor_temperature"
GATTR_OUTDOOR_TEMPERATURE = "outdoor_temperature"
GATTR_HUMIDITY = "rooom_humidity"

ATTR_EXTERNAL_TEMPERATURE_SENSOR = "external_temperature_sensor"
ATTR_EXTERNAL_HUMIDITY_SENSOR = "external_humidity_sensor"
ATTR_AUTO_XFAN = "auto_xfan"
ATTR_AUTO_LIGHT = "auto_light"

# Map each feature constant to its corresponding GreeProp
CONF_TO_PROP_FEATURE_MAP = {
    GATTR_BEEPER: GreeProp.BEEPER,
    GATTR_FEAT_FRESH_AIR: GreeProp.FEAT_FRESH_AIR,
    GATTR_FEAT_XFAN: GreeProp.FEAT_XFAN,
    GATTR_FEAT_SLEEP_MODE: GreeProp.FEAT_SLEEP_MODE,
    GATTR_FEAT_SMART_HEAT_8C: GreeProp.FEAT_SMART_HEAT_8C,
    GATTR_FEAT_HEALTH: GreeProp.FEAT_HEALTH,
    GATTR_ANTI_DIRECT_BLOW: GreeProp.FEAT_ANTI_DIRECT_BLOW,
    GATTR_FEAT_ENERGY_SAVING: GreeProp.FEAT_ENERGY_SAVING,
    GATTR_FEAT_LIGHT: GreeProp.FEAT_LIGHT,
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
]

UNITS_GREE_TO_HA = {
    TemperatureUnits.C: UnitOfTemperature.CELSIUS,
    TemperatureUnits.F: UnitOfTemperature.FAHRENHEIT,
}
