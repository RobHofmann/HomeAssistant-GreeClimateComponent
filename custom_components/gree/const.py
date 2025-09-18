"""Constants for the Gree integration."""

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
CONF_FEATURES = "features"

DEFAULT_TARGET_TEMP_STEP = 1
DEFAULT_ENCRYPTION_VERSION = None


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

ATTR_EXTERNAL_TEMPERATURE_SENSOR = "external_temperature_sensor"
ATTR_EXTERNAL_HUMIDITY_SENSOR = "external_humidity_sensor"

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

DEFAULT_SWING_HORIZONTAL_MODES = [
    HorizontalSwingMode.Default.name,
    HorizontalSwingMode.FullSwing.name,
    HorizontalSwingMode.Left.name,
    HorizontalSwingMode.LeftCenter.name,
    HorizontalSwingMode.Center.name,
    HorizontalSwingMode.RightCenter.name,
    HorizontalSwingMode.Right.name,
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
