"""
Gree Climate Entity for Home Assistant.

This module defines the climate (HVAC) unit for the Gree integration.
"""

# Standard library imports
import base64
import logging
from datetime import timedelta

# Third-party imports
try:
    import simplejson
except ImportError:
    import json as simplejson
from Crypto.Cipher import AES

# Home Assistant imports
from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature, HVACMode
from homeassistant.const import (
    ATTR_TEMPERATURE,
    ATTR_UNIT_OF_MEASUREMENT,
    CONF_HOST,
    CONF_MAC,
    CONF_NAME,
    CONF_PORT,
    CONF_TIMEOUT,
)

# Local imports
from .const import (
    DOMAIN,
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    DEFAULT_HVAC_MODES,
    DEFAULT_FAN_MODES,
    DEFAULT_SWING_MODES,
    DEFAULT_SWING_HORIZONTAL_MODES,
    DEFAULT_TARGET_TEMP_STEP,
    MIN_TEMP_C,
    MIN_TEMP_F,
    MAX_TEMP_C,
    MAX_TEMP_F,
    MODES_MAPPING,
    TEMSEN_OFFSET,
    CONF_HVAC_MODES,
    CONF_FAN_MODES,
    CONF_SWING_MODES,
    CONF_SWING_HORIZONTAL_MODES,
    CONF_ENCRYPTION_KEY,
    CONF_UID,
    CONF_ENCRYPTION_VERSION,
    CONF_DISABLE_AVAILABLE_CHECK,
    CONF_MAX_ONLINE_ATTEMPTS,
    CONF_TEMP_SENSOR_OFFSET,
)
from .gree_protocol import Pad, FetchResult, GetDeviceKey, GetGCMCipher, EncryptGCM, GetDeviceKeyGCM
from .helpers import TempOffsetResolver, gree_f_to_c, gree_c_to_f, encode_temp_c, decode_temp_c

REQUIREMENTS = ["pycryptodome"]

_LOGGER = logging.getLogger(__name__)

SUPPORT_FLAGS = ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE | ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF


async def create_gree_device(hass, config):
    """Create a Gree device instance from config."""
    name = config.get(CONF_NAME, "Gree Climate")
    ip_addr = config.get(CONF_HOST)
    port = config.get(CONF_PORT, DEFAULT_PORT)
    mac_addr = config.get(CONF_MAC).encode().replace(b":", b"")
    timeout = config.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)

    chm = config.get(CONF_HVAC_MODES)
    hvac_modes = [getattr(HVACMode, mode.upper()) for mode in (chm if chm is not None else DEFAULT_HVAC_MODES)]

    cfm = config.get(CONF_FAN_MODES)
    fan_modes = cfm if cfm is not None else DEFAULT_FAN_MODES
    csm = config.get(CONF_SWING_MODES)
    swing_modes = csm if csm is not None else DEFAULT_SWING_MODES
    cshm = config.get(CONF_SWING_HORIZONTAL_MODES)
    swing_horizontal_modes = cshm if cshm is not None else DEFAULT_SWING_HORIZONTAL_MODES
    encryption_key = config.get(CONF_ENCRYPTION_KEY)
    uid = config.get(CONF_UID)
    encryption_version = config.get(CONF_ENCRYPTION_VERSION, 1)
    disable_available_check = config.get(CONF_DISABLE_AVAILABLE_CHECK, False)
    max_online_attempts = config.get(CONF_MAX_ONLINE_ATTEMPTS, 3)
    temp_sensor_offset = config.get(CONF_TEMP_SENSOR_OFFSET)

    return GreeClimate(
        hass,
        name,
        ip_addr,
        port,
        mac_addr,
        timeout,
        hvac_modes,
        fan_modes,
        swing_modes,
        swing_horizontal_modes,
        encryption_version,
        disable_available_check,
        max_online_attempts,
        encryption_key,
        uid,
        temp_sensor_offset,
    )


# from the remote control and gree app

# update() interval
SCAN_INTERVAL = timedelta(seconds=60)


async def async_setup_entry(hass, entry, async_add_devices):
    """Set up Gree climate from a config entry."""
    # Get the device that was created in __init__.py
    entry_data = hass.data[DOMAIN][entry.entry_id]
    device = entry_data["device"]

    async_add_devices([device])


async def async_unload_entry(hass, entry):
    """Unload a config entry."""
    return True


class GreeClimate(ClimateEntity):
    # Language is retrieved from translation key
    _attr_translation_key = "gree"

    def __init__(
        self,
        hass,
        name,
        ip_addr,
        port,
        mac_addr,
        timeout,
        hvac_modes,
        fan_modes,
        swing_modes,
        swing_horizontal_modes,
        encryption_version,
        disable_available_check,
        max_online_attempts,
        encryption_key=None,
        uid=None,
        temp_sensor_offset=None,
    ):
        _LOGGER.info("Initialize the GREE climate device")
        self.hass = hass
        self._name = name
        self._ip_addr = ip_addr
        self._port = port
        mac_addr_str = mac_addr.decode("utf-8").lower()
        if "@" in mac_addr_str:
            self._sub_mac_addr, self._mac_addr = mac_addr_str.split("@", 1)
        else:
            self._sub_mac_addr = self._mac_addr = mac_addr_str
        self._timeout = timeout
        self._unique_id = f"{DOMAIN}_{self._mac_addr}"
        self._device_online = None
        self._online_attempts = 0
        self._max_online_attempts = max_online_attempts
        self._disable_available_check = disable_available_check

        self._target_temperature = None
        # Initialize target temperature step with default value (will be overridden by number entity when available)
        self._target_temperature_step = DEFAULT_TARGET_TEMP_STEP
        # Device uses a combination of Celsius + a set bit for Fahrenheit, so the integration needs to be aware of the units.
        self._unit_of_measurement = hass.config.units.temperature_unit
        _LOGGER.info("Unit of measurement: %s", self._unit_of_measurement)

        self._hvac_modes = hvac_modes
        self._hvac_mode = HVACMode.OFF
        self._fan_modes = fan_modes
        self._fan_mode = None
        self._swing_modes = swing_modes
        self._swing_mode = None
        self._swing_horizontal_modes = swing_horizontal_modes
        self._swing_horizontal_mode = None

        self._temp_sensor_offset = temp_sensor_offset

        # Store for external temp sensor entity (set by sensor entity)
        self._external_temperature_sensor = None

        # Keep unsub callbacks for deregistering listeners
        self._listeners: list = []

        self._has_temp_sensor = None
        self._has_anti_direct_blow = None
        self._has_light_sensor = None

        self._current_temperature = None
        self._current_anti_direct_blow = None
        self._current_light_sensor = None

        self._firstTimeRun = True

        self._enable_turn_on_off_backwards_compatibility = False

        self.encryption_version = encryption_version
        self.CIPHER = None

        if encryption_key:
            _LOGGER.info("Using configured encryption key: {}".format(encryption_key))
            self._encryption_key = encryption_key.encode("utf8")
            if encryption_version == 1:
                # Cipher to use to encrypt/decrypt
                self.CIPHER = AES.new(self._encryption_key, AES.MODE_ECB)
            elif self.encryption_version != 2:
                _LOGGER.error("Encryption version %s is not implemented." % self.encryption_version)
        else:
            self._encryption_key = None

        if uid:
            self._uid = uid
        else:
            self._uid = 0

        self._acOptions = {
            "Pow": None,
            "Mod": None,
            "SetTem": None,
            "WdSpd": None,
            "Air": None,
            "Blo": None,
            "Health": None,
            "SwhSlp": None,
            "Lig": None,
            "SwingLfRig": None,
            "SwUpDn": None,
            "Quiet": None,
            "Tur": None,
            "StHt": None,
            "TemUn": None,
            "HeatCoolType": None,
            "TemRec": None,
            "SvSt": None,
            "SlpMod": None,
        }
        self._optionsToFetch = ["Pow", "Mod", "SetTem", "WdSpd", "Air", "Blo", "Health", "SwhSlp", "Lig", "SwingLfRig", "SwUpDn", "Quiet", "Tur", "StHt", "TemUn", "HeatCoolType", "TemRec", "SvSt", "SlpMod"]

        # Initialize auto switches
        self._auto_light = False
        self._auto_xfan = False

        # Initialize beeper control
        self._beeper_enabled = True  # Default to beeper ON (silent mode OFF)

        # helper method to determine TemSen offset
        self._process_temp_sensor = TempOffsetResolver()

    def GreeGetValues(self, propertyNames):
        plaintext = '{"cols":' + simplejson.dumps(propertyNames) + ',"mac":"' + str(self._sub_mac_addr) + '","t":"status"}'
        if self.encryption_version == 1:
            cipher = self.CIPHER
            jsonPayloadToSend = '{"cid":"app","i":0,"pack":"' + base64.b64encode(cipher.encrypt(Pad(plaintext).encode("utf8"))).decode("utf-8") + '","t":"pack","tcid":"' + str(self._mac_addr) + '","uid":{}'.format(self._uid) + "}"
        elif self.encryption_version == 2:
            pack, tag = EncryptGCM(self._encryption_key, plaintext)
            jsonPayloadToSend = '{"cid":"app","i":0,"pack":"' + pack + '","t":"pack","tcid":"' + str(self._mac_addr) + '","uid":{}'.format(self._uid) + ',"tag" : "' + tag + '"}'
            cipher = GetGCMCipher(self._encryption_key)
        dat = FetchResult(cipher, self._ip_addr, self._port, self._timeout, jsonPayloadToSend, encryption_version=self.encryption_version)["dat"]
        return dat[0] if len(dat) == 1 else dat

    def SetAcOptions(self, acOptions, newOptionsToOverride, optionValuesToOverride=None):
        if optionValuesToOverride is not None:
            _LOGGER.debug("Setting acOptions with retrieved HVAC values")
            for key in newOptionsToOverride:
                _LOGGER.debug("Setting %s: %s" % (key, optionValuesToOverride[newOptionsToOverride.index(key)]))
                acOptions[key] = optionValuesToOverride[newOptionsToOverride.index(key)]
            _LOGGER.debug("Done setting acOptions")
        else:
            _LOGGER.debug("Overwriting acOptions with new settings")
            for key, value in newOptionsToOverride.items():
                _LOGGER.debug("Overwriting %s: %s" % (key, value))
                acOptions[key] = value
            _LOGGER.debug("Done overwriting acOptions")
        return acOptions

    def SendStateToAc(self, timeout):
        opt_list = ["Pow", "Mod", "SetTem", "WdSpd", "Air", "Blo", "Health", "SwhSlp", "Lig", "SwingLfRig", "SwUpDn", "Quiet", "Tur", "StHt", "TemUn", "HeatCoolType", "TemRec", "SvSt", "SlpMod", "AntiDirectBlow", "LigSen"]

        # Collect values from _acOptions
        p_values = [self._acOptions.get(k) for k in opt_list]

        # Filter out empty ones
        filtered_opt = []
        filtered_p = []
        for name, val in zip(opt_list, p_values):
            if val not in ("", None):
                filtered_opt.append(f'"{name}"')
                filtered_p.append(str(val))

        buzzer_command_value = 0 if self._beeper_enabled else 1
        filtered_opt.append('"Buzzer_ON_OFF"')
        filtered_p.append(str(buzzer_command_value))
        _LOGGER.debug(f"Sending with Buzzer_ON_OFF={buzzer_command_value} (Beeper is {'ENABLED' if self._beeper_enabled else 'DISABLED'})")

        statePackJson = '{"opt":[' + ",".join(filtered_opt) + '],"p":[' + ",".join(filtered_p) + '],"t":"cmd","mac":"' + self._sub_mac_addr + '"}'

        if self.encryption_version == 1:
            cipher = self.CIPHER
            sentJsonPayload = '{"cid":"app","i":0,"pack":"' + base64.b64encode(cipher.encrypt(Pad(statePackJson).encode("utf8"))).decode("utf-8") + '","t":"pack","tcid":"' + str(self._mac_addr) + '","uid":{}'.format(self._uid) + "}"
        elif self.encryption_version == 2:
            pack, tag = EncryptGCM(self._encryption_key, statePackJson)
            sentJsonPayload = '{"cid":"app","i":0,"pack":"' + pack + '","t":"pack","tcid":"' + str(self._mac_addr) + '","uid":{}'.format(self._uid) + ',"tag":"' + tag + '"}'
            cipher = GetGCMCipher(self._encryption_key)
        receivedJsonPayload = FetchResult(cipher, self._ip_addr, self._port, timeout, sentJsonPayload, encryption_version=self.encryption_version)
        _LOGGER.debug("Done sending state to HVAC: " + str(receivedJsonPayload))

    def UpdateHATargetTemperature(self):
        # Sync set temperature to HA. If 8℃ heating is active we set the temp in HA to 8℃ so that it shows the same as the AC display.
        if self._acOptions["StHt"] and (int(self._acOptions["StHt"]) == 1):
            self._target_temperature = 8
            _LOGGER.info("HA target temp set according to HVAC state to 8℃ since 8℃ heating mode is active")
        else:
            temp_c = decode_temp_c(SetTem=self._acOptions["SetTem"], TemRec=self._acOptions["TemRec"])  # takes care of 1/2 degrees
            temp_f = gree_c_to_f(SetTem=self._acOptions["SetTem"], TemRec=self._acOptions["TemRec"])

            if self._unit_of_measurement == "°C":
                display_temp = temp_c
            elif self._unit_of_measurement == "°F":
                display_temp = temp_f
            else:
                display_temp = temp_c  # default to deg c
                _LOGGER.error("Unknown unit of measurement: %s" % self._unit_of_measurement)

            self._target_temperature = display_temp

            _LOGGER.info(f"UpdateHATargetTemperature: HA target temp set to: {self._target_temperature} {self._unit_of_measurement}. Device commands: SetTem: {self._acOptions['SetTem']}, TemRec: {self._acOptions['TemRec']}")

    def UpdateHAHvacMode(self):
        # Sync current HVAC operation mode to HA
        if self._acOptions["Pow"] == 0:
            self._hvac_mode = HVACMode.OFF
        else:
            for key, value in MODES_MAPPING.get("Mod").items():
                if value == (self._acOptions["Mod"]):
                    self._hvac_mode = key
        _LOGGER.debug("HA operation mode set according to HVAC state to: " + str(self._hvac_mode))

    def UpdateHACurrentSwingMode(self):
        # Sync current HVAC Swing mode state to HA
        for key, value in MODES_MAPPING.get("SwUpDn").items():
            if value == (self._acOptions["SwUpDn"]):
                self._swing_mode = key
        _LOGGER.debug("HA swing mode set according to HVAC state to: " + str(self._swing_mode))

    def UpdateHACurrentSwingHorizontalMode(self):
        # Sync current HVAC Horizontal Swing mode state to HA
        for key, value in MODES_MAPPING.get("SwingLfRig").items():
            if value == (self._acOptions["SwingLfRig"]):
                self._swing_horizontal_mode = key
        _LOGGER.debug("HA horizontal swing mode set according to HVAC state to: " + str(self._swing_horizontal_mode))

    def UpdateHAFanMode(self):
        # Sync current HVAC Fan mode state to HA
        if int(self._acOptions["Tur"]) == 1:
            turbo_index = self._fan_modes.index("turbo")
            self._fan_mode = self._fan_modes[turbo_index]
        elif int(self._acOptions["Quiet"]) >= 1:
            quiet_index = self._fan_modes.index("quiet")
            self._fan_mode = self._fan_modes[quiet_index]
        else:
            for key, value in MODES_MAPPING.get("WdSpd").items():
                if value == (self._acOptions["WdSpd"]):
                    self._fan_mode = key
        _LOGGER.debug("HA fan mode set according to HVAC state to: " + str(self._fan_mode))

    def UpdateHACurrentTemperature(self):
        # Use external temperature sensor if available
        if self._external_temperature_sensor:
            # Use external temperature sensor
            external_sensor_state = self.hass.states.get(self._external_temperature_sensor)
            if external_sensor_state and external_sensor_state.state not in ("unknown", "unavailable"):
                try:
                    unit = external_sensor_state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
                    _LOGGER.debug(f"Using external temperature sensor: {self._external_temperature_sensor}, value: {external_sensor_state.state}, unit: {unit}")
                    self._current_temperature = self.hass.config.units.temperature(float(external_sensor_state.state), unit)
                    _LOGGER.debug(f"External temperature: {self._current_temperature} {self._unit_of_measurement}")
                    return
                except (ValueError, TypeError) as ex:
                    _LOGGER.error("Unable to update from external temp sensor %s: %s", self._external_temperature_sensor, ex)

        # Use built-in AC temperature sensor if available
        if self._has_temp_sensor:
            _LOGGER.debug("method UpdateHACurrentTemperature: TemSen: " + str(self._acOptions["TemSen"]))

            if self._temp_sensor_offset is None:  # user hasn't chosen an offset
                # User hasn't set automaticaly, so try to determine the offset
                temp_c = self._process_temp_sensor(self._acOptions["TemSen"])
                _LOGGER.debug("method UpdateHACurrentTemperature: User has not chosen an offset, using process_temp_sensor() to automatically determine offset.")
            else:
                # User set
                if self._temp_sensor_offset is True:
                    temp_c = self._acOptions["TemSen"] - TEMSEN_OFFSET

                elif self._temp_sensor_offset is False:
                    temp_c = self._acOptions["TemSen"]

                _LOGGER.debug(f"method UpdateHACurrentTemperature: User has chosen an offset ({self._temp_sensor_offset})")

            temp_f = gree_c_to_f(SetTem=temp_c, TemRec=0)  # Convert to Fahrenheit using TemRec bit

            if self._unit_of_measurement == "°C":
                self._current_temperature = temp_c
            elif self._unit_of_measurement == "°F":
                self._current_temperature = temp_f
            else:
                _LOGGER.error("Unknown unit of measurement: %s" % self._unit_of_measurement)

            _LOGGER.debug("method UpdateHACurrentTemperature: HA current temperature set with device built-in temperature sensor state : " + str(self._current_temperature) + str(self._unit_of_measurement))

    def UpdateHAStateToCurrentACState(self):
        self.UpdateHATargetTemperature()
        self.UpdateHAHvacMode()
        if self._swing_modes:
            self.UpdateHACurrentSwingMode()
        if self._swing_horizontal_modes:
            self.UpdateHACurrentSwingHorizontalMode()
        self.UpdateHAFanMode()
        self.UpdateHACurrentTemperature()

    def SyncState(self, acOptions={}):
        # Fetch current settings from HVAC
        _LOGGER.debug("Starting SyncState")

        if self._has_temp_sensor is None:
            _LOGGER.debug("Attempt to check whether device has an built-in temperature sensor")
            try:
                temp_sensor = self.GreeGetValues(["TemSen"])
            except Exception:
                _LOGGER.debug("Could not determine whether device has an built-in temperature sensor. Retrying at next update()")
            else:
                if temp_sensor:
                    self._has_temp_sensor = True
                    self._acOptions.update({"TemSen": None})
                    self._optionsToFetch.append("TemSen")
                    _LOGGER.debug("Device has an built-in temperature sensor")
                else:
                    self._has_temp_sensor = False
                    _LOGGER.debug("Device has no built-in temperature sensor")

        # Check if device has anti direct blow feature
        if self._has_anti_direct_blow is None:
            _LOGGER.debug("Attempt to check whether device has an anti direct blow feature")
            try:
                anti_direct_blow = self.GreeGetValues(["AntiDirectBlow"])
            except Exception:
                _LOGGER.debug("Could not determine whether device has an anti direct blow feature. Retrying at next update()")
            else:
                if anti_direct_blow:
                    self._has_anti_direct_blow = True
                    self._acOptions.update({"AntiDirectBlow": None})
                    self._optionsToFetch.append("AntiDirectBlow")
                    _LOGGER.debug("Device has an anti direct blow feature")
                else:
                    self._has_anti_direct_blow = False
                    _LOGGER.debug("Device has no anti direct blow feature")

        # Check if device has light sensor
        if self._has_light_sensor is None:
            _LOGGER.debug("Attempt to check whether device has a built-in light sensor")
            try:
                light_sensor = self.GreeGetValues(["LigSen"])
            except Exception:
                _LOGGER.debug("Could not determine whether device has a built-in light sensor. Retrying at next update()")
            else:
                if light_sensor:
                    self._has_light_sensor = True
                    self._acOptions.update({"LigSen": None})
                    self._optionsToFetch.append("LigSen")
                    _LOGGER.debug("Device has a built-in light sensor")
                else:
                    self._has_light_sensor = False
                    _LOGGER.debug("Device has no built-in light sensor")

        optionsToFetch = self._optionsToFetch

        try:
            currentValues = self.GreeGetValues(optionsToFetch)
        except Exception:
            _LOGGER.info("Could not connect with device. ")
            if not self._disable_available_check:
                self._online_attempts += 1
                if self._online_attempts == self._max_online_attempts:
                    _LOGGER.info("Could not connect with device %s times. Set it as offline." % self._max_online_attempts)
                    self._device_online = False
                    self._online_attempts = 0
        else:
            if not self._disable_available_check:
                if not self._device_online:
                    self._device_online = True
                    self._online_attempts = 0
            # Set latest status from device
            self._acOptions = self.SetAcOptions(self._acOptions, optionsToFetch, currentValues)

            # Overwrite status with our choices
            if not (acOptions == {}):
                self._acOptions = self.SetAcOptions(self._acOptions, acOptions)

            # Initialize the receivedJsonPayload variable (for return)
            receivedJsonPayload = ""

            # If not the first (boot) run, update state towards the HVAC
            if not (self._firstTimeRun):
                if not (acOptions == {}):
                    # loop used to send changed settings from HA to HVAC
                    self.SendStateToAc(self._timeout)
            else:
                # loop used once for Gree Climate initialisation only
                self._firstTimeRun = False

            # Update HA state to current HVAC state
            self.UpdateHAStateToCurrentACState()

            _LOGGER.debug("Finished SyncState")
            return receivedJsonPayload

    @property
    def should_poll(self):
        _LOGGER.debug("should_poll()")
        # Return the polling state.
        return True

    @property
    def available(self):
        if self._disable_available_check:
            return True
        else:
            if self._device_online:
                _LOGGER.info("available(): Device is online")
                return True
            else:
                _LOGGER.info("available(): Device is offline")
                return False

    def update(self):
        _LOGGER.debug("update()")
        if not self._encryption_key:
            if self.encryption_version == 1:
                key = GetDeviceKey(self._mac_addr, self._ip_addr, self._port, self._timeout)
                if key:
                    self._encryption_key = key
                    self.CIPHER = AES.new(self._encryption_key, AES.MODE_ECB)
                    self.SyncState()
            elif self.encryption_version == 2:
                key = GetDeviceKeyGCM(self._mac_addr, self._ip_addr, self._port, self._timeout)
                if key:
                    self._encryption_key = key
                    self.CIPHER = GetGCMCipher(self._encryption_key)
                    self.SyncState()
            else:
                _LOGGER.error("Encryption version %s is not implemented." % self.encryption_version)
        else:
            self.SyncState()

    @property
    def name(self):
        _LOGGER.debug("name(): " + str(self._name))
        # Return the name of the climate device.
        return self._name

    @property
    def temperature_unit(self):
        _LOGGER.debug("temperature_unit(): " + str(self._unit_of_measurement))
        # Return the unit of measurement.
        return self._unit_of_measurement

    @property
    def current_temperature(self):
        _LOGGER.debug("current_temperature(): " + str(self._current_temperature))
        # Return the current temperature.
        return self._current_temperature

    @property
    def min_temp(self):
        if self._unit_of_measurement == "°C":
            MIN_TEMP = MIN_TEMP_C
        else:
            MIN_TEMP = MIN_TEMP_F

        _LOGGER.debug("min_temp(): " + str(MIN_TEMP))
        # Return the minimum temperature.
        return MIN_TEMP

    @property
    def max_temp(self):
        if self._unit_of_measurement == "°C":
            MAX_TEMP = MAX_TEMP_C
        else:
            MAX_TEMP = MAX_TEMP_F

        _LOGGER.debug("max_temp(): " + str(MAX_TEMP))
        # Return the maximum temperature.
        return MAX_TEMP

    @property
    def target_temperature(self):
        _LOGGER.debug("target_temperature(): " + str(self._target_temperature))
        # Return the temperature we try to reach.
        return self._target_temperature

    @property
    def target_temperature_step(self):
        _LOGGER.debug("target_temperature_step(): " + str(self._target_temperature_step))
        return self._target_temperature_step

    @property
    def hvac_mode(self):
        _LOGGER.debug("hvac_mode(): " + str(self._hvac_mode))
        # Return current operation mode ie. heat, cool, idle.
        return self._hvac_mode

    @property
    def swing_mode(self):
        if self._swing_modes:
            _LOGGER.debug("swing_mode(): " + str(self._swing_mode))
            # get the current swing mode
            return self._swing_mode
        else:
            return None

    @property
    def swing_modes(self):
        _LOGGER.debug("swing_modes(): " + str(self._swing_modes))
        # get the list of available swing modes
        return self._swing_modes

    @property
    def swing_horizontal_mode(self):
        if self._swing_horizontal_modes:
            _LOGGER.debug("swing_horizontal_mode(): " + str(self._swing_horizontal_mode))
            # get the current preset mode
            return self._swing_horizontal_mode
        else:
            return None

    @property
    def swing_horizontal_modes(self):
        _LOGGER.debug("swing_horizontal_modes(): " + str(self._swing_horizontal_modes))
        # get the list of available preset modes
        return self._swing_horizontal_modes

    @property
    def hvac_modes(self):
        _LOGGER.debug("hvac_modes(): " + str(self._hvac_modes))
        # Return the list of available operation modes.
        return self._hvac_modes

    @property
    def fan_mode(self):
        _LOGGER.debug("fan_mode(): " + str(self._fan_mode))
        # Return the fan mode.
        return self._fan_mode

    @property
    def fan_modes(self):
        _LOGGER.debug("fan_list(): " + str(self._fan_modes))
        # Return the list of available fan modes.
        return self._fan_modes

    @property
    def supported_features(self):
        sf = SUPPORT_FLAGS
        if self._swing_modes:
            sf = sf | ClimateEntityFeature.SWING_MODE
        if self._swing_horizontal_modes:
            sf = sf | ClimateEntityFeature.SWING_HORIZONTAL_MODE
        _LOGGER.debug("supported_features(): " + str(sf))
        # Return the list of supported features.
        return sf

    @property
    def unique_id(self):
        # Return unique_id
        return self._unique_id

    def set_temperature(self, **kwargs):
        s = kwargs.get(ATTR_TEMPERATURE)

        _LOGGER.info("set_temperature(): " + str(s) + str(self._unit_of_measurement))
        # Set new target temperatures.
        if s is not None:
            # do nothing if temperature is none
            if not (self._acOptions["Pow"] == 0):
                # do nothing if HVAC is switched off

                if self._unit_of_measurement == "°C":
                    SetTem, TemRec = encode_temp_c(T=s)  # takes care of 1/2 degrees
                elif self._unit_of_measurement == "°F":
                    SetTem, TemRec = gree_f_to_c(desired_temp_f=s)
                else:
                    _LOGGER.error("Unable to set temperature. Units not set to °C or °F")
                    return

                self.SyncState({"SetTem": int(SetTem), "TemRec": int(TemRec)})
                _LOGGER.debug("method set_temperature: Set Temp to " + str(s) + str(self._unit_of_measurement) + " ->  SyncState with SetTem=" + str(SetTem) + ", SyncState with TemRec=" + str(TemRec))

                self.schedule_update_ha_state()

    def set_swing_mode(self, swing_mode):
        _LOGGER.info("Set swing mode(): " + str(swing_mode))
        # set the swing mode
        if not (self._acOptions["Pow"] == 0):
            # do nothing if HVAC is switched off
            try:
                sw_up_dn = MODES_MAPPING.get("SwUpDn").get(swing_mode)
                _LOGGER.info("SyncState with SwUpDn=" + str(sw_up_dn))
                self.SyncState({"SwUpDn": sw_up_dn})
                self.schedule_update_ha_state()
            except ValueError:
                _LOGGER.error(f"Unknown swing mode: {swing_mode}")
                return

    def set_swing_horizontal_mode(self, swing_horizontal_mode):
        if not (self._acOptions["Pow"] == 0):
            # do nothing if HVAC is switched off
            try:
                swing_lf_rig = MODES_MAPPING.get("SwingLfRig").get(swing_horizontal_mode)
                _LOGGER.info("SyncState with SwingLfRig=" + str(swing_lf_rig))
                self.SyncState({"SwingLfRig": swing_lf_rig})
                self.schedule_update_ha_state()
            except ValueError:
                _LOGGER.error(f"Unknown preset mode: {swing_horizontal_mode}")
                return

    def set_fan_mode(self, fan):
        _LOGGER.info("set_fan_mode(): " + str(fan))
        # Set the fan mode.
        if not (self._acOptions["Pow"] == 0):
            try:
                wd_spd = MODES_MAPPING.get("WdSpd").get(fan)

                # Check if this is turbo mode
                if fan == "turbo":
                    _LOGGER.info("Enabling turbo mode")
                    self.SyncState({"Tur": 1, "Quiet": 0})
                # Check if this is quiet mode
                elif fan == "quiet":
                    _LOGGER.info("Enabling quiet mode")
                    self.SyncState({"Tur": 0, "Quiet": 1})
                else:
                    _LOGGER.info("Setting normal fan mode to " + str(wd_spd))
                    self.SyncState({"WdSpd": str(wd_spd), "Tur": 0, "Quiet": 0})

                self.schedule_update_ha_state()
            except ValueError:
                _LOGGER.error(f"Unknown fan mode: {fan}")
                return

    def set_hvac_mode(self, hvac_mode):
        _LOGGER.info("set_hvac_mode(): " + str(hvac_mode))
        # Set new operation mode.
        c = {}
        if hvac_mode == HVACMode.OFF:
            c.update({"Pow": 0})
            if hasattr(self, "_auto_light") and self._auto_light:
                c.update({"Lig": 0})
        else:
            mod = MODES_MAPPING.get("Mod").get(hvac_mode)
            c.update({"Pow": 1, "Mod": mod})
            if hasattr(self, "_auto_light") and self._auto_light:
                c.update({"Lig": 1})
            if hasattr(self, "_auto_xfan") and self._auto_xfan:
                if (hvac_mode == HVACMode.COOL) or (hvac_mode == HVACMode.DRY):
                    c.update({"Blo": 1})
        self.SyncState(c)
        self.schedule_update_ha_state()

    def turn_on(self):
        _LOGGER.info("turn_on(): ")
        # Turn on.
        c = {"Pow": 1}
        if hasattr(self, "_auto_light") and self._auto_light:
            c.update({"Lig": 1})
        self.SyncState(c)
        self.schedule_update_ha_state()

    def turn_off(self):
        _LOGGER.info("turn_off(): ")
        # Turn off.
        c = {"Pow": 0}
        if hasattr(self, "_auto_light") and self._auto_light:
            c.update({"Lig": 0})
        self.SyncState(c)
        self.schedule_update_ha_state()

    async def async_added_to_hass(self):
        _LOGGER.info("Gree climate device added to hass()")
        self.update()

    async def async_will_remove_from_hass(self) -> None:
        """Clean up when entity is removed."""
        for name, entity_id, unsub in self._listeners:
            _LOGGER.debug("Deregistering %s listener for %s", name, entity_id)
            unsub()
        self._listeners.clear()
