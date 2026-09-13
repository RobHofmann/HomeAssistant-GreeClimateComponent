DOMAIN = "gree"

CONF_HVAC_MODES = "hvac_modes"
CONF_ENCRYPTION_KEY = 'encryption_key'
CONF_UID = 'uid'
CONF_FAN_MODES = 'fan_modes'
CONF_SWING_MODES = 'swing_modes'
CONF_SWING_HORIZONTAL_MODES = 'swing_horizontal_modes'
CONF_ENCRYPTION_VERSION = 'encryption_version'
CONF_DISABLE_AVAILABLE_CHECK  = 'disable_available_check'
CONF_TEMP_SENSOR_OFFSET = 'temp_sensor_offset'
CONF_EXTRA_SCAN_NETWORKS = 'extra_scan_networks'
CONF_EXTRA_SCAN_HOSTS = 'extra_scan_hosts'

MAX_UNICAST_SCAN_HOSTS = 65536

DEFAULT_PORT = 7000
DEFAULT_TARGET_TEMP_STEP = 1

MIN_TEMP_C = 16
MAX_TEMP_C = 30

MIN_TEMP_F = 61
MAX_TEMP_F = 86

TEMSEN_OFFSET = 40

# Sensor readings that arrive with a +40 °C encoding offset (actual = raw - 40).
DIAGNOSTIC_TEMP_OFFSET = 40

# Optional device properties, probed once before they join the polling list.
#
# Probing is mandatory rather than defensive. The firmware silently omits unknown columns
# from a status response, while SetAcOptions() maps dat[i] positionally onto the list of
# columns that was requested. Polling a key the device does not implement therefore shifts
# every following value by one position, and the next SendStateToAc() would push a wrong
# mode or temperature to the unit.
#
# Each entry is (property key, attribute name used as the "device has this" flag).
PROBED_PROPS = (
    ("TemSen", "_has_temp_sensor"),
    ("AntiDirectBlow", "_has_anti_direct_blow"),
    ("LigSen", "_has_light_sensor"),
    ("OutEnvTem", "_has_outside_temp_sensor"),
    ("DwatSen", "_has_room_humidity_sensor"),
    # Inverter and air-quality diagnostics
    ("CompressorFqy", "_has_compressor_freq"),
    ("CompressorTem", "_has_compressor_temp"),
    ("InEvaTem", "_has_evaporator_temp"),
    ("EnvTem", "_has_env_temp"),
    ("TemsSenOut", "_has_outside_temp_alt"),
    ("PM2P5", "_has_pm25"),
    # Fault and maintenance reporting
    ("AllErr", "_has_all_err"),
    ("JFErrorCode", "_has_jf_error"),
    ("Dfltr", "_has_filter_alarm"),
    ("ReplaceHEPA", "_has_hepa_alarm"),
    # Comfort and cleaning toggles
    ("ChildLock", "_has_child_lock"),
    ("Dazzling", "_has_dazzling"),
    ("UvcControl", "_has_uvc"),
    ("AutoClean", "_has_auto_clean"),
    ("NobodySave", "_has_nobody_save"),
)

# Optional properties that are writable, not just readable. They are appended to the
# command sent by SendStateToAc(); values still unset (device lacks the feature) are
# filtered out there, so listing one a device does not implement is harmless.
CONTROLLABLE_OPTIONAL_PROPS = ("ChildLock", "Dazzling", "UvcControl", "AutoClean", "NobodySave")

# HVAC modes - these come from Home Assistant and are standard
DEFAULT_HVAC_MODES = ["auto", "cool", "dry", "fan_only", "heat", "off"] 

DEFAULT_FAN_MODES = ["auto", "low", "medium_low", "medium", "medium_high", "high", "turbo", "quiet"]
DEFAULT_SWING_MODES = ["default", "swing_full", "fixed_upmost", "fixed_middle_up", "fixed_middle", "fixed_middle_low", "fixed_lowest", "swing_downmost", "swing_middle_low", "swing_middle", "swing_middle_up", "swing_upmost"]
DEFAULT_SWING_HORIZONTAL_MODES = ["default", "swing_full", "fixed_leftmost", "fixed_middle_left", "fixed_middle", "fixed_middle_right", "fixed_rightmost"]

# Keys that can be updated via the options flow
OPTION_KEYS = {
    CONF_HVAC_MODES,
    CONF_FAN_MODES,
    CONF_SWING_MODES,
    CONF_SWING_HORIZONTAL_MODES,
    CONF_DISABLE_AVAILABLE_CHECK,
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