"""Constants."""

from homeassistant.components.climate import HVACMode
from homeassistant.const import UnitOfTemperature

from .gree_api import (
    FanSpeed,
    HorizontalSwingMode,
    OperationMode,
    TemperatureUnits,
    VerticalSwingMode,
)

DOMAIN = "gree"

CONF_ADVANCED = "advanced"
CONF_UID = "uid"
CONF_ENCRYPTION_KEY = "encryption_key"
CONF_ENCRYPTION_VERSION = "encryption_version"
CONF_DISABLE_AVAILABLE_CHECK = "disable_available_check"
CONF_MAX_ONLINE_ATTEMPTS = "max_online_attempts"

CONF_HVAC_MODES = "hvac_modes"
CONF_FAN_MODES = "fan_modes"
CONF_SWING_MODES = "swing_modes"
CONF_SWING_HORIZONTAL_MODES = "swing_horizontal_modes"
CONF_TEMP_SENSOR_OFFSET = "temp_sensor_offset"
CONF_FEATURES = "features"

DEFAULT_PORT = 7000
DEFAULT_TIMEOUT = 10
DEFAULT_TARGET_TEMP_STEP = 1
DEFAULT_MAX_ONLINE_ATTEMPTS = 8
DEFAULT_ENCRYPTION_VERSION = 0

MIN_TEMP_C = 16
MAX_TEMP_C = 30

MIN_TEMP_F = 61
MAX_TEMP_F = 86

TEMSEN_OFFSET = 40

# OPTIONAL FEATURES/MODES
# use the device beeper on commands
GATTR_BEEPER = "beeper"
# controls the state of the fresh air valve (not available on all units)
GATTR_FEAT_FRESH_AIR = "feat_fresh_air"
# "Blow" or "X-Fan", this function keeps the fan running for a while after shutting down. Only usable in Dry and Cool mode
GATTR_FEAT_XFAN = "feat_xfan"
# sleep mode, which gradually changes the temperature in Cool, Heat and Dry mode
GATTR_FEAT_SLEEP_MODE = "feat_sleep"
# Anti Freeze maintain the room temperature steadily at 8°C and prevent the room from freezing by heating operation when nobody is at home for long in severe winter
GATTR_FEAT_SMART_HEAT_8C = "feat_smart_heat"
# turns all indicators and the display on the unit on or off
GATTR_FEAT_LIGHT = "feat_lights"
# controls Health ("Cold plasma") mode
GATTR_FEAT_HEALTH = "feat_health"
# prevents the wind from blowing directly on people
GATTR_ANTI_DIRECT_BLOW = "feat_anti_direct_blow"
# energy saving mode
GATTR_FEAT_ENERGY_SAVING = "feat_energy_saving"
# use light sensor for unit display
GATTR_FEAT_SENSOR_LIGHT = "feat_light_sensor"
# Quiet mode which slows down the fan to its most quiet speed. Not available in Dry and Fan mode.
GATTR_FEAT_QUIET_MODE = "feat_quiet"
# Turbo mode sets fan speed to the maximum. Fan speed cannot be changed while active and only available in Dry and Cool mode
GATTR_FEAT_TURBO = "feat_turbo"

GATTR_TEMP_UNITS = "temperature_units"

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
    HVACMode.AUTO: OperationMode.Auto,
    HVACMode.COOL: OperationMode.Cool,
    HVACMode.DRY: OperationMode.Dry,
    HVACMode.FAN_ONLY: OperationMode.Fan,
    HVACMode.HEAT: OperationMode.Heat,
}
HVAC_MODES_GREE_TO_HA = {
    OperationMode.Auto: HVACMode.AUTO,
    OperationMode.Cool: HVACMode.COOL,
    OperationMode.Dry: HVACMode.DRY,
    OperationMode.Fan: HVACMode.FAN_ONLY,
    OperationMode.Heat: HVACMode.HEAT,
}

DEFAULT_FAN_MODES = [
    FanSpeed.Auto.name,
    FanSpeed.Low.name,
    FanSpeed.MediumLow.name,
    FanSpeed.Medium.name,
    FanSpeed.MediumHigh.name,
    FanSpeed.High.name,
    GATTR_FEAT_TURBO,  # Special mode on Gree device
    GATTR_FEAT_QUIET_MODE,  # Special mode on Gree device
]

# FAN_SPEED_HA_TO_GREE = {
#     FanSpeed.Auto.name: FanSpeed.Auto,
#     FanSpeed.Low.name: FanSpeed.Low,
#     FanSpeed.MediumLow.name: FanSpeed.MediumLow,
#     FanSpeed.Medium.name: FanSpeed.Medium,
#     FanSpeed.MediumHigh.name: FanSpeed.MediumHigh,
#     FanSpeed.High.name: FanSpeed.High,
# }

DEFAULT_SWING_MODES = [
    VerticalSwingMode.Default.name,
    VerticalSwingMode.FullSwing.name,
    VerticalSwingMode.FixedUpper.name,
    VerticalSwingMode.FixedUpperMiddle.name,
    VerticalSwingMode.FixedMiddle.name,
    VerticalSwingMode.FixedLowerMiddle.name,
    VerticalSwingMode.FixedLower.name,
    VerticalSwingMode.SwingLower.name,
    VerticalSwingMode.SwingLowerMiddle.name,
    VerticalSwingMode.SwingMiddle.name,
    VerticalSwingMode.SwingUpperMiddle.name,
    VerticalSwingMode.SwingUpper.name,
]

# SWING_VERTICAL_MODE_HA_TO_GREE = {
#     VerticalSwingMode.Default.name: VerticalSwingMode.Default,
#     VerticalSwingMode.FullSwing.name: VerticalSwingMode.FullSwing,
#     VerticalSwingMode.FixedUpper.name: VerticalSwingMode.FixedUpper,
#     VerticalSwingMode.FixedUpperMiddle.name: VerticalSwingMode.FixedUpperMiddle,
#     VerticalSwingMode.FixedMiddle.name: VerticalSwingMode.FixedMiddle,
#     VerticalSwingMode.FixedLowerMiddle.name: VerticalSwingMode.FixedLowerMiddle,
#     VerticalSwingMode.FixedLower.name: VerticalSwingMode.FixedLower,
#     VerticalSwingMode.SwingLower.name: VerticalSwingMode.SwingLower,
#     VerticalSwingMode.SwingLowerMiddle.name: VerticalSwingMode.SwingLowerMiddle,
#     VerticalSwingMode.SwingMiddle.name: VerticalSwingMode.SwingMiddle,
#     VerticalSwingMode.SwingUpperMiddle.name: VerticalSwingMode.SwingUpperMiddle,
#     VerticalSwingMode.SwingUpper.name: VerticalSwingMode.SwingUpper,
# }

DEFAULT_SWING_HORIZONTAL_MODES = [
    HorizontalSwingMode.Default.name,
    HorizontalSwingMode.FullSwing.name,
    HorizontalSwingMode.Left.name,
    HorizontalSwingMode.LeftCenter.name,
    HorizontalSwingMode.Center.name,
    HorizontalSwingMode.RightCenter.name,
    HorizontalSwingMode.Right.name,
]

# SWING_HORIZONTAL_MODE_HA_TO_GREE = {
#     HorizontalSwingMode.Default.name: HorizontalSwingMode.Default,
#     HorizontalSwingMode.FullSwing.name: HorizontalSwingMode.FullSwing,
#     HorizontalSwingMode.Left.name: HorizontalSwingMode.Left,
#     HorizontalSwingMode.LeftCenter.name: HorizontalSwingMode.LeftCenter,
#     HorizontalSwingMode.Center.name: HorizontalSwingMode.Center,
#     HorizontalSwingMode.RightCenter.name: HorizontalSwingMode.RightCenter,
#     HorizontalSwingMode.Right.name: HorizontalSwingMode.Right,
# }

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

# Keys that can be updated via the options flow
OPTION_KEYS = {
    CONF_HVAC_MODES,
    CONF_FAN_MODES,
    CONF_SWING_MODES,
    CONF_SWING_HORIZONTAL_MODES,
    CONF_DISABLE_AVAILABLE_CHECK,
    CONF_MAX_ONLINE_ATTEMPTS,
    CONF_TEMP_SENSOR_OFFSET,
}

MODES_MAPPING = {
    "Mod": {"auto": 0, "cool": 1, "dry": 2, "fan_only": 3, "heat": 4},
    "WdSpd": {
        "auto": 0,
        "low": 1,
        "medium_low": 2,
        "medium": 3,
        "medium_high": 4,
        "high": 5,
    },
    "SwUpDn": {
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
    },
    "SwingLfRig": {
        "default": 0,
        "swing_full": 1,
        "fixed_leftmost": 2,
        "fixed_middle_left": 3,
        "fixed_middle": 4,
        "fixed_middle_right": 5,
        "fixed_rightmost": 6,
    },
}
