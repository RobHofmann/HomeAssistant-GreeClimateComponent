DOMAIN = "gree"
PLATFORMS = ["climate"]

CONF_HVAC_MODES = "hvac_modes"
CONF_TARGET_TEMP_STEP = 'target_temp_step'
CONF_TEMP_SENSOR = 'temp_sensor'
CONF_LIGHTS = 'lights'
CONF_XFAN = 'xfan'
CONF_HEALTH = 'health'
CONF_POWERSAVE = 'powersave'
CONF_SLEEP = 'sleep'
CONF_EIGHTDEGHEAT = 'eightdegheat'
CONF_AIR = 'air'
CONF_ENCRYPTION_KEY = 'encryption_key'
CONF_UID = 'uid'
CONF_AUTO_XFAN = 'auto_xfan'
CONF_AUTO_LIGHT = 'auto_light'
CONF_TARGET_TEMP = 'target_temp'
CONF_FAN_MODES = 'fan_modes'
CONF_SWING_MODES = 'swing_modes'
CONF_SWING_HORIZONTAL_MODES = 'swing_horizontal_modes'
CONF_ANTI_DIRECT_BLOW = 'anti_direct_blow'
CONF_ENCRYPTION_VERSION = 'encryption_version'
CONF_DISABLE_AVAILABLE_CHECK  = 'disable_available_check'
CONF_MAX_ONLINE_ATTEMPTS = 'max_online_attempts'
CONF_LIGHT_SENSOR = 'light_sensor'
CONF_BEEPER = 'beeper'
CONF_TEMP_SENSOR_OFFSET = 'temp_sensor_offset'

DEFAULT_PORT = 7000
DEFAULT_TIMEOUT = 10
DEFAULT_TARGET_TEMP_STEP = 1

MIN_TEMP_C = 16
MAX_TEMP_C = 30

MIN_TEMP_F = 61
MAX_TEMP_F = 86

TEMSEN_OFFSET = 40

# HVAC modes - these come from Home Assistant and are standard
DEFAULT_HVAC_MODES = ["auto", "cool", "dry", "fan_only", "heat", "off"] 

DEFAULT_FAN_MODES = ["auto", "low", "medium_low", "medium", "medium_high", "high", "turbo", "quiet"]
DEFAULT_SWING_MODES = ["default", "swing_full", "fixed_upmost", "fixed_middle_up", "fixed_middle", "fixed_middle_low", "fixed_lowest", "swing_downmost", "swing_middle_low", "swing_middle", "swing_middle_up", "swing_upmost"]
DEFAULT_SWING_HORIZONTAL_MODES = ["default", "swing_full", "fixed_leftmost", "fixed_middle_left", "fixed_middle", "fixed_middle_right", "fixed_rightmost"]

# Keys that can be updated via the options flow
OPTION_KEYS = {
    CONF_HVAC_MODES,
    CONF_TARGET_TEMP_STEP,
    CONF_TEMP_SENSOR,
    CONF_LIGHTS,
    CONF_XFAN,
    CONF_HEALTH,
    CONF_POWERSAVE,
    CONF_SLEEP,
    CONF_EIGHTDEGHEAT,
    CONF_AIR,
    CONF_TARGET_TEMP,
    CONF_AUTO_XFAN,
    CONF_AUTO_LIGHT,
    CONF_FAN_MODES,
    CONF_SWING_MODES,
    CONF_SWING_HORIZONTAL_MODES,
    CONF_ANTI_DIRECT_BLOW,
    CONF_DISABLE_AVAILABLE_CHECK,
    CONF_MAX_ONLINE_ATTEMPTS,
    CONF_LIGHT_SENSOR,
    CONF_BEEPER,
    CONF_TEMP_SENSOR_OFFSET,
}

MODES_MAPPING = {
  "Mod" : {
    "auto" : 0,
    "cool" : 1,
    "dry" : 2,
    "fan_only" : 3,
    "heat" : 4
  },
  "WdSpd" : {
    "auto" : 0,
    "low" : 1,
    "medium_low" : 2,
    "medium" : 3,
    "medium_high" : 4,
    "high" : 5
  },
  "SwUpDn" : {
    "default" : 0,
    "swing_full" : 1,
    "fixed_upmost" : 2,
    "fixed_middle_up" : 3,
    "fixed_middle" : 4,
    "fixed_middle_low" : 5,
    "fixed_lowest" : 6,
    "swing_downmost" : 7,
    "swing_middle_low" : 8,
    "swing_middle" : 9,
    "swing_middle_up" : 10,
    "swing_upmost" : 11
  },
  "SwingLfRig" : {
    "default" : 0,
    "swing_full" : 1,
    "fixed_leftmost" : 2,
    "fixed_middle_left" : 3,
    "fixed_middle" : 4,
    "fixed_middle_right" : 5,
    "fixed_rightmost" : 6
  }
}