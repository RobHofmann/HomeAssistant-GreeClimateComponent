#!/usr/bin/python
# Do basic imports
import socket
import base64

import logging
import voluptuous as vol
import homeassistant.helpers.config_validation as cv

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
    PLATFORM_SCHEMA
)

from homeassistant.const import (
    ATTR_TEMPERATURE,
    ATTR_UNIT_OF_MEASUREMENT,
    CONF_HOST,
    CONF_MAC,
    CONF_NAME,
    CONF_PORT,
    CONF_TIMEOUT,
    STATE_OFF,
    STATE_ON,
    STATE_UNKNOWN
)

from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    callback,
)
from homeassistant.helpers.event import async_track_state_change_event
from Crypto.Cipher import AES
from .translations_helper import (
    get_all_translated_modes,
    get_translated_name,
    get_mode_key_by_index,
    FAN_MODE_KEYS,
    SWING_MODE_KEYS,
    PRESET_MODE_KEYS
)
try: import simplejson
except ImportError: import json as simplejson
from datetime import timedelta

REQUIREMENTS = ['pycryptodome']

_LOGGER = logging.getLogger(__name__)

SUPPORT_FLAGS = ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE | ClimateEntityFeature.SWING_MODE | ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF

# DEFAULT_NAME will be set dynamically based on language

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
CONF_HORIZONTAL_SWING = 'horizontal_swing'
CONF_ANTI_DIRECT_BLOW = 'anti_direct_blow'
CONF_ENCRYPTION_VERSION = 'encryption_version'
CONF_DISABLE_AVAILABLE_CHECK  = 'disable_available_check'
CONF_MAX_ONLINE_ATTEMPTS = 'max_online_attempts'
CONF_LIGHT_SENSOR = 'light_sensor'
CONF_BEEPER = 'beeper'
CONF_TEMP_SENSOR_OFFSET = 'temp_sensor_offset'
CONF_LANGUAGE = 'language'

# Keys that can be updated via the options flow
OPTION_KEYS = {
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
    CONF_HORIZONTAL_SWING,
    CONF_ANTI_DIRECT_BLOW,
    CONF_DISABLE_AVAILABLE_CHECK,
    CONF_MAX_ONLINE_ATTEMPTS,
    CONF_LIGHT_SENSOR,
    CONF_BEEPER,
    CONF_TEMP_SENSOR_OFFSET,
    CONF_LANGUAGE,
}

DEFAULT_PORT = 7000
DEFAULT_TIMEOUT = 10
DEFAULT_TARGET_TEMP_STEP = 1

# from the remote control and gree app
MIN_TEMP_C = 16
MAX_TEMP_C = 30

MIN_TEMP_F = 61
MAX_TEMP_F = 86

TEMSEN_OFFSET = 40

# update() interval
SCAN_INTERVAL = timedelta(seconds=60)

# HVAC modes - these come from Home Assistant and are standard
HVAC_MODES = [HVACMode.AUTO, HVACMode.COOL, HVACMode.DRY, HVACMode.FAN_ONLY, HVACMode.HEAT, HVACMode.OFF]

FAN_MODES = ['Auto', 'Low', 'Medium-Low', 'Medium', 'Medium-High', 'High', 'Turbo', 'Quiet']
SWING_MODES = ['Default', 'Swing in full range', 'Fixed in the upmost position', 'Fixed in the middle-up position', 'Fixed in the middle position', 'Fixed in the middle-low position', 'Fixed in the lowest position', 'Swing in the downmost region', 'Swing in the middle-low region', 'Swing in the middle region', 'Swing in the middle-up region', 'Swing in the upmost region']
PRESET_MODES = ['Default', 'Full swing', 'Fixed in the leftmost position', 'Fixed in the middle-left position', 'Fixed in the middle postion','Fixed in the middle-right position', 'Fixed in the rightmost position']

GCM_IV = b'\x54\x40\x78\x44\x49\x67\x5a\x51\x6c\x5e\x63\x13'
GCM_ADD = b'qualcomm-test'

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_NAME, default='Gree Climate'): cv.string,
    vol.Required(CONF_HOST): cv.string,
    vol.Required(CONF_PORT, default=DEFAULT_PORT): cv.positive_int,
    vol.Required(CONF_MAC): cv.string,
    vol.Optional(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): cv.positive_int,
    vol.Optional(CONF_TARGET_TEMP_STEP, default=DEFAULT_TARGET_TEMP_STEP): vol.Coerce(float),
    vol.Optional(CONF_TEMP_SENSOR): cv.entity_id,
    vol.Optional(CONF_LIGHTS): cv.entity_id,
    vol.Optional(CONF_XFAN): cv.entity_id,
    vol.Optional(CONF_HEALTH): cv.entity_id,
    vol.Optional(CONF_POWERSAVE): cv.entity_id,
    vol.Optional(CONF_SLEEP): cv.entity_id,
    vol.Optional(CONF_EIGHTDEGHEAT): cv.entity_id,
    vol.Optional(CONF_AIR): cv.entity_id,
    vol.Optional(CONF_ENCRYPTION_KEY): cv.string,
    vol.Optional(CONF_UID): cv.positive_int,
    vol.Optional(CONF_AUTO_XFAN): cv.entity_id,
    vol.Optional(CONF_AUTO_LIGHT): cv.entity_id,
    vol.Optional(CONF_TARGET_TEMP): cv.entity_id,
    vol.Optional(CONF_ENCRYPTION_VERSION, default=1): cv.positive_int,
    vol.Optional(CONF_HORIZONTAL_SWING, default=False): cv.boolean,
    vol.Optional(CONF_ANTI_DIRECT_BLOW): cv.entity_id,
    vol.Optional(CONF_DISABLE_AVAILABLE_CHECK, default=False): cv.boolean,
    vol.Optional(CONF_MAX_ONLINE_ATTEMPTS, default=3): cv.positive_int,
    vol.Optional(CONF_LIGHT_SENSOR): cv.entity_id,
    vol.Optional(CONF_BEEPER): cv.entity_id,
    vol.Optional(CONF_TEMP_SENSOR_OFFSET): cv.boolean,
    vol.Optional(CONF_LANGUAGE): cv.string,
})

async def async_setup_platform(hass, config, async_add_devices, discovery_info=None):
    _LOGGER.info('Setting up Gree climate platform')

    # Get language preference
    language = config.get(CONF_LANGUAGE)

    # Get translated default name if no name is provided
    default_name = await get_translated_name(hass, language)
    name = config.get(CONF_NAME) or default_name
    ip_addr = config.get(CONF_HOST)
    port = config.get(CONF_PORT)
    mac_addr = config.get(CONF_MAC).encode().replace(b':', b'')
    timeout = config.get(CONF_TIMEOUT)

    target_temp_step = config.get(CONF_TARGET_TEMP_STEP)
    temp_sensor_entity_id = config.get(CONF_TEMP_SENSOR)
    lights_entity_id = config.get(CONF_LIGHTS)
    xfan_entity_id = config.get(CONF_XFAN)
    health_entity_id = config.get(CONF_HEALTH)
    powersave_entity_id = config.get(CONF_POWERSAVE)
    sleep_entity_id = config.get(CONF_SLEEP)
    eightdegheat_entity_id = config.get(CONF_EIGHTDEGHEAT)
    air_entity_id = config.get(CONF_AIR)
    target_temp_entity_id = config.get(CONF_TARGET_TEMP)
    hvac_modes = HVAC_MODES

    # Get all translated modes at once
    translated_modes = await get_all_translated_modes(hass, language)
    fan_modes = translated_modes['fan_mode']
    swing_modes = translated_modes['swing_mode']
    preset_modes = translated_modes['preset_mode']
    encryption_key = config.get(CONF_ENCRYPTION_KEY)
    uid = config.get(CONF_UID)
    auto_xfan_entity_id = config.get(CONF_AUTO_XFAN)
    auto_light_entity_id = config.get(CONF_AUTO_LIGHT)
    horizontal_swing = config.get(CONF_HORIZONTAL_SWING)
    anti_direct_blow_entity_id = config.get(CONF_ANTI_DIRECT_BLOW)
    light_sensor_entity_id = config.get(CONF_LIGHT_SENSOR)
    encryption_version = config.get(CONF_ENCRYPTION_VERSION)
    disable_available_check = config.get(CONF_DISABLE_AVAILABLE_CHECK)
    max_online_attempts = config.get(CONF_MAX_ONLINE_ATTEMPTS)
    beeper_entity_id = config.get(CONF_BEEPER)
    temp_sensor_offset = config.get(CONF_TEMP_SENSOR_OFFSET)

    _LOGGER.info('Adding Gree climate device to hass')

    async_add_devices([
        GreeClimate(
            hass,
            name,
            ip_addr,
            port,
            mac_addr,
            timeout,
            target_temp_step,
            temp_sensor_entity_id,
            lights_entity_id,
            xfan_entity_id,
            health_entity_id,
            powersave_entity_id,
            sleep_entity_id,
            eightdegheat_entity_id,
            air_entity_id,
            target_temp_entity_id,
            anti_direct_blow_entity_id,
            hvac_modes,
            fan_modes,
            swing_modes,
            preset_modes,
            auto_xfan_entity_id,
            auto_light_entity_id,
            horizontal_swing,
            light_sensor_entity_id,
            encryption_version,
            disable_available_check,
            max_online_attempts,
            encryption_key,
            uid,
            beeper_entity_id,
            temp_sensor_offset,
            language,
        )
    ])


async def async_setup_entry(hass, entry, async_add_devices):
    """Set up Gree climate from a config entry."""
    config = {**entry.data}
    for key, value in entry.options.items():
        if key in OPTION_KEYS and value is not None:
            config[key] = value
    await async_setup_platform(hass, config, async_add_devices)


async def async_unload_entry(hass, entry):
    """Unload a config entry."""
    return True

class GreeClimate(ClimateEntity):

    def __init__(self, hass, name, ip_addr, port, mac_addr, timeout, target_temp_step, temp_sensor_entity_id, lights_entity_id, xfan_entity_id, health_entity_id, powersave_entity_id, sleep_entity_id, eightdegheat_entity_id, air_entity_id, target_temp_entity_id, anti_direct_blow_entity_id, hvac_modes, fan_modes, swing_modes, preset_modes, auto_xfan_entity_id, auto_light_entity_id, horizontal_swing, light_sensor_entity_id, encryption_version, disable_available_check, max_online_attempts, encryption_key=None, uid=None, beeper_entity_id=None, temp_sensor_offset=None, language=None):
        _LOGGER.info('Initialize the GREE climate device')
        self.hass = hass
        self._name = name
        self._ip_addr = ip_addr
        self._port = port
        self._mac_addr = mac_addr.decode('utf-8').lower()
        self._timeout = timeout
        self._unique_id = 'climate.gree_' + mac_addr.decode('utf-8').lower()
        self._device_online = None
        self._online_attempts = 0
        self._max_online_attempts = max_online_attempts
        self._disable_available_check = disable_available_check

        self._target_temperature = None
        self._target_temperature_step = target_temp_step
        # Device uses a combination of Celsius + a set bit for Fahrenheit, so the integration needs to be aware of the units.
        self._unit_of_measurement = hass.config.units.temperature_unit
        _LOGGER.info("Unit of measurement: %s", self._unit_of_measurement)

        self._hvac_modes = hvac_modes
        self._hvac_mode = HVACMode.OFF
        self._fan_modes = fan_modes
        self._fan_mode = None
        self._swing_modes = swing_modes
        self._swing_mode = None
        self._preset_modes = preset_modes
        self._preset_mode = None

        self._temp_sensor_entity_id = temp_sensor_entity_id
        self._lights_entity_id = lights_entity_id
        self._xfan_entity_id = xfan_entity_id
        self._health_entity_id = health_entity_id
        self._powersave_entity_id = powersave_entity_id
        self._sleep_entity_id = sleep_entity_id
        self._eightdegheat_entity_id = eightdegheat_entity_id
        self._air_entity_id = air_entity_id
        self._target_temp_entity_id = target_temp_entity_id
        self._anti_direct_blow_entity_id = anti_direct_blow_entity_id
        self._light_sensor_entity_id = light_sensor_entity_id
        self._auto_xfan_entity_id = auto_xfan_entity_id
        self._auto_light_entity_id = auto_light_entity_id
        self._temp_sensor_offset = temp_sensor_offset

        # Keep unsub callbacks for deregistering listeners
        self._listeners: list[tuple[str, str, CALLBACK_TYPE]] = []

        self._horizontal_swing = horizontal_swing
        self._has_temp_sensor = None
        self._has_anti_direct_blow = None
        self._has_light_sensor = None

        # Store the language preference
        self._language = language

        self._current_temperature = None
        self._current_lights = None
        self._current_xfan = None
        self._current_health = None
        self._current_powersave = None
        self._current_sleep = None
        self._current_eightdegheat = None
        self._current_air = None
        self._current_anti_direct_blow = None
        self._current_light_sensor = None

        self._firstTimeRun = True

        self._enable_turn_on_off_backwards_compatibility = False

        self.encryption_version = encryption_version
        self.CIPHER = None

        if encryption_key:
            _LOGGER.info('Using configured encryption key: {}'.format(encryption_key))
            self._encryption_key = encryption_key.encode("utf8")
            if encryption_version == 1:
                # Cipher to use to encrypt/decrypt
                self.CIPHER = AES.new(self._encryption_key, AES.MODE_ECB)
            elif encryption_version != 2:
                _LOGGER.error('Encryption version %s is not implemented.' % encryption_version)
        else:
            self._encryption_key = None

        if uid:
            self._uid = uid
        else:
            self._uid = 0


        self._acOptions = { 'Pow': None, 'Mod': None, 'SetTem': None, 'WdSpd': None, 'Air': None, 'Blo': None, 'Health': None, 'SwhSlp': None, 'Lig': None, 'SwingLfRig': None, 'SwUpDn': None, 'Quiet': None, 'Tur': None, 'StHt': None, 'TemUn': None, 'HeatCoolType': None, 'TemRec': None, 'SvSt': None, 'SlpMod': None }
        self._optionsToFetch = ["Pow","Mod","SetTem","WdSpd","Air","Blo","Health","SwhSlp","Lig","SwingLfRig","SwUpDn","Quiet","Tur","StHt","TemUn","HeatCoolType","TemRec","SvSt","SlpMod"]

        if temp_sensor_entity_id:
            _LOGGER.info('Setting up remote temperature sensor: %s', temp_sensor_entity_id)
            unsub = async_track_state_change_event(
                hass, temp_sensor_entity_id, self._async_temp_sensor_changed
            )
            self._listeners.append(('temp_sensor', temp_sensor_entity_id, unsub))

        if lights_entity_id:
            _LOGGER.info('Setting up lights entity: %s', lights_entity_id)
            unsub = async_track_state_change_event(
                hass, lights_entity_id, self._async_lights_entity_state_changed
            )
            self._listeners.append(('lights', lights_entity_id, unsub))

        if xfan_entity_id:
            _LOGGER.info('Setting up xfan entity: %s', xfan_entity_id)
            unsub = async_track_state_change_event(
                hass, xfan_entity_id, self._async_xfan_entity_state_changed
            )
            self._listeners.append(('xfan', xfan_entity_id, unsub))

        if health_entity_id:
            _LOGGER.info('Setting up health entity: %s', health_entity_id)
            unsub = async_track_state_change_event(
                hass, health_entity_id, self._async_health_entity_state_changed
            )
            self._listeners.append(('health', health_entity_id, unsub))

        if powersave_entity_id:
            _LOGGER.info('Setting up powersave entity: %s', powersave_entity_id)
            unsub = async_track_state_change_event(
                hass, powersave_entity_id, self._async_powersave_entity_state_changed
            )
            self._listeners.append(('powersave', powersave_entity_id, unsub))

        if sleep_entity_id:
            _LOGGER.info('Setting up sleep entity: %s', sleep_entity_id)
            unsub = async_track_state_change_event(
                hass, sleep_entity_id, self._async_sleep_entity_state_changed
            )
            self._listeners.append(('sleep', sleep_entity_id, unsub))

        if eightdegheat_entity_id:
            _LOGGER.info('Setting up 8℃ heat entity: %s', eightdegheat_entity_id)
            unsub = async_track_state_change_event(
                hass, eightdegheat_entity_id, self._async_eightdegheat_entity_state_changed
            )
            self._listeners.append(('eightdegheat', eightdegheat_entity_id, unsub))

        if air_entity_id:
            _LOGGER.info('Setting up air entity: %s', air_entity_id)
            unsub = async_track_state_change_event(
                hass, air_entity_id, self._async_air_entity_state_changed
            )
            self._listeners.append(('air', air_entity_id, unsub))

        if target_temp_entity_id:
            _LOGGER.info('Setting up target temp entity: %s', target_temp_entity_id)
            unsub = async_track_state_change_event(
                hass, target_temp_entity_id, self._async_target_temp_entity_state_changed
            )
            self._listeners.append(('target_temp', target_temp_entity_id, unsub))

        if anti_direct_blow_entity_id:
            _LOGGER.info('Setting up anti direct blow entity: %s', anti_direct_blow_entity_id)
            unsub = async_track_state_change_event(
                hass, anti_direct_blow_entity_id, self._async_anti_direct_blow_entity_state_changed
            )
            self._listeners.append(('anti_direct_blow', anti_direct_blow_entity_id, unsub))

        if light_sensor_entity_id:
            _LOGGER.info('Setting up light sensor entity: %s', light_sensor_entity_id)
            if self.hass.states.get(light_sensor_entity_id) is not None and self.hass.states.get(light_sensor_entity_id).state is STATE_ON:
                self._enable_light_sensor = True
            else:
                self._enable_light_sensor = False
            unsub = async_track_state_change_event(
                hass, light_sensor_entity_id, self._async_light_sensor_entity_state_changed
            )
            self._listeners.append(('light_sensor', light_sensor_entity_id, unsub))
        else:
            self._enable_light_sensor = False

        if auto_light_entity_id:
            _LOGGER.info('Setting up auto light entity: %s', auto_light_entity_id)
            if self.hass.states.get(auto_light_entity_id) is not None and self.hass.states.get(auto_light_entity_id).state is STATE_ON:
                self._auto_light = True
            else:
                self._auto_light = False
            unsub = async_track_state_change_event(
                hass, auto_light_entity_id, self._async_auto_light_entity_state_changed
            )
            self._listeners.append(('auto_light', auto_light_entity_id, unsub))
        else:
            self._auto_light = False

        if auto_xfan_entity_id:
            _LOGGER.info('Setting up auto xfan entity: %s', auto_xfan_entity_id)
            if self.hass.states.get(auto_xfan_entity_id) is not None and self.hass.states.get(auto_xfan_entity_id).state is STATE_ON:
                self._auto_xfan = True
            else:
                self._auto_xfan = False
            unsub = async_track_state_change_event(
                hass, auto_xfan_entity_id, self._async_auto_xfan_entity_state_changed
            )
            self._listeners.append(('auto_xfan', auto_xfan_entity_id, unsub))
        else:
            self._auto_xfan = False

        # helper method to determine TemSen offset
        self._process_temp_sensor = self.TempOffsetResolver()

        self._beeper_entity_id = beeper_entity_id
        self._current_beeper_enabled = True # Default to beeper ON (silent mode OFF)

        if self._beeper_entity_id:
            _LOGGER.info('Setting up beeper control entity: %s', self._beeper_entity_id)
            initial_beeper_state = self.hass.states.get(self._beeper_entity_id)
            if initial_beeper_state and initial_beeper_state.state == STATE_ON:
                self._current_beeper_enabled = True

            unsub = async_track_state_change_event(
                hass, self._beeper_entity_id, self._async_beeper_entity_state_changed
            )
            self._listeners.append(('beeper', self._beeper_entity_id, unsub))

    # Pad helper method to help us get the right string for encrypting

    def Pad(self, s):
        aesBlockSize = 16
        return s + (aesBlockSize - len(s) % aesBlockSize) * chr(aesBlockSize - len(s) % aesBlockSize)

    def FetchResult(self, cipher, ip_addr, port, timeout, json):
        _LOGGER.debug('Fetching(%s, %s, %s, %s)' % (ip_addr, port, timeout, json))
        clientSock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        clientSock.settimeout(timeout)
        clientSock.sendto(bytes(json, "utf-8"), (ip_addr, port))
        data, addr = clientSock.recvfrom(64000)
        receivedJson = simplejson.loads(data)
        clientSock.close()
        pack = receivedJson['pack']
        base64decodedPack = base64.b64decode(pack)
        decryptedPack = cipher.decrypt(base64decodedPack)
        if self.encryption_version == 2:
            tag = receivedJson['tag']
            cipher.verify(base64.b64decode(tag))
        decodedPack = decryptedPack.decode("utf-8")
        replacedPack = decodedPack.replace('\x0f', '').replace(decodedPack[decodedPack.rindex('}')+1:], '')
        loadedJsonPack = simplejson.loads(replacedPack)
        return loadedJsonPack

    def GetDeviceKey(self):
        _LOGGER.info('Retrieving HVAC encryption key')
        GENERIC_GREE_DEVICE_KEY = "a3K8Bx%2r8Y7#xDh"
        cipher = AES.new(GENERIC_GREE_DEVICE_KEY.encode("utf8"), AES.MODE_ECB)
        pack = base64.b64encode(cipher.encrypt(self.Pad('{"mac":"' + str(self._mac_addr) + '","t":"bind","uid":0}').encode("utf8"))).decode('utf-8')
        jsonPayloadToSend = '{"cid": "app","i": 1,"pack": "' + pack + '","t":"pack","tcid":"' + str(self._mac_addr) + '","uid": 0}'
        try:
            self._encryption_key = self.FetchResult(cipher, self._ip_addr, self._port, self._timeout, jsonPayloadToSend)['key'].encode("utf8")
        except:
            _LOGGER.info('Error getting device encryption key!')
            self._device_online = False
            self._online_attempts = 0
            return False
        else:
            _LOGGER.info('Fetched device encrytion key: %s' % str(self._encryption_key))
            self.CIPHER = AES.new(self._encryption_key, AES.MODE_ECB)
            self._device_online = True
            self._online_attempts = 0
            return True

    def GetGCMCipher(self, key):
        cipher = AES.new(key, AES.MODE_GCM, nonce=GCM_IV)
        cipher.update(GCM_ADD)
        return cipher

    def EncryptGCM(self, key, plaintext):
        encrypted_data, tag = self.GetGCMCipher(key).encrypt_and_digest(plaintext.encode("utf8"))
        pack = base64.b64encode(encrypted_data).decode('utf-8')
        tag = base64.b64encode(tag).decode('utf-8')
        return (pack, tag)

    def GetDeviceKeyGCM(self):
        _LOGGER.info('Retrieving HVAC encryption key')
        GENERIC_GREE_DEVICE_KEY = b'{yxAHAY_Lm6pbC/<'
        plaintext = '{"cid":"' + str(self._mac_addr) + '", "mac":"' + str(self._mac_addr) + '","t":"bind","uid":0}'
        pack, tag = self.EncryptGCM(GENERIC_GREE_DEVICE_KEY, plaintext)
        jsonPayloadToSend = '{"cid": "app","i": 1,"pack": "' + pack + '","t":"pack","tcid":"' + str(self._mac_addr) + '","uid": 0, "tag" : "' + tag + '"}'
        try:
            self._encryption_key = self.FetchResult(self.GetGCMCipher(GENERIC_GREE_DEVICE_KEY), self._ip_addr, self._port, self._timeout, jsonPayloadToSend)['key'].encode("utf8")
        except:
            _LOGGER.info('Error getting device encryption key!')
            self._device_online = False
            self._online_attempts = 0
            return False
        else:
            _LOGGER.info('Fetched device encrytion key: %s' % str(self._encryption_key))
            self._device_online = True
            self._online_attempts = 0
            return True

    def GreeGetValues(self, propertyNames):
        plaintext = '{"cols":' + simplejson.dumps(propertyNames) + ',"mac":"' + str(self._mac_addr) + '","t":"status"}'
        if self.encryption_version == 1:
            cipher = self.CIPHER
            jsonPayloadToSend = '{"cid":"app","i":0,"pack":"' + base64.b64encode(cipher.encrypt(self.Pad(plaintext).encode("utf8"))).decode('utf-8') + '","t":"pack","tcid":"' + str(self._mac_addr) + '","uid":{}'.format(self._uid) + '}'
        elif self.encryption_version == 2:
            pack, tag = self.EncryptGCM(self._encryption_key, plaintext)
            jsonPayloadToSend = '{"cid":"app","i":0,"pack":"' + pack + '","t":"pack","tcid":"' + str(self._mac_addr) + '","uid":{}'.format(self._uid) + ',"tag" : "' + tag + '"}'
            cipher = self.GetGCMCipher(self._encryption_key)
        return self.FetchResult(cipher, self._ip_addr, self._port, self._timeout, jsonPayloadToSend)['dat']

    def SetAcOptions(self, acOptions, newOptionsToOverride, optionValuesToOverride = None):
        if not (optionValuesToOverride is None):
            _LOGGER.debug('Setting acOptions with retrieved HVAC values')
            for key in newOptionsToOverride:
                _LOGGER.debug('Setting %s: %s' % (key, optionValuesToOverride[newOptionsToOverride.index(key)]))
                acOptions[key] = optionValuesToOverride[newOptionsToOverride.index(key)]
            _LOGGER.debug('Done setting acOptions')
        else:
            _LOGGER.debug('Overwriting acOptions with new settings')
            for key, value in newOptionsToOverride.items():
                _LOGGER.debug('Overwriting %s: %s' % (key, value))
                acOptions[key] = value
            _LOGGER.debug('Done overwriting acOptions')
        return acOptions

    def SendStateToAc(self, timeout):
        opt = '"Pow","Mod","SetTem","WdSpd","Air","Blo","Health","SwhSlp","Lig","SwingLfRig","SwUpDn","Quiet","Tur","StHt","TemUn","HeatCoolType","TemRec","SvSt","SlpMod"'
        p = '{Pow},{Mod},{SetTem},{WdSpd},{Air},{Blo},{Health},{SwhSlp},{Lig},{SwingLfRig},{SwUpDn},{Quiet},{Tur},{StHt},{TemUn},{HeatCoolType},{TemRec},{SvSt},{SlpMod}'.format(**self._acOptions)

        buzzer_command_value = 0 if self._current_beeper_enabled else 1

        opt += ',"Buzzer_ON_OFF"'
        p += ',' + str(buzzer_command_value)
        _LOGGER.debug(f"Sending with Buzzer_ON_OFF={buzzer_command_value} (Silent mode HA toggle is ON: {self._current_beeper_enabled})")

        if self._has_anti_direct_blow:
            opt += ',"AntiDirectBlow"'
            p += ',' + str(self._acOptions['AntiDirectBlow'])
        if self._has_light_sensor:
            opt += ',"LigSen"'
            p += ',' + str(self._acOptions['LigSen'])
        statePackJson = '{"opt":[' + opt + '],"p":[' + p + '],"t":"cmd"}'
        if self.encryption_version == 1:
            cipher = self.CIPHER
            sentJsonPayload = '{"cid":"app","i":0,"pack":"' + base64.b64encode(cipher.encrypt(self.Pad(statePackJson).encode("utf8"))).decode('utf-8') + '","t":"pack","tcid":"' + str(self._mac_addr) + '","uid":{}'.format(self._uid) + '}'
        elif self.encryption_version == 2:
            pack, tag = self.EncryptGCM(self._encryption_key, statePackJson)
            sentJsonPayload = '{"cid":"app","i":0,"pack":"' + pack + '","t":"pack","tcid":"' + str(self._mac_addr) + '","uid":{}'.format(self._uid) + ',"tag":"' + tag +'"}'
            cipher = self.GetGCMCipher(self._encryption_key)
        receivedJsonPayload = self.FetchResult(cipher, self._ip_addr, self._port, timeout, sentJsonPayload)
        _LOGGER.debug('Done sending state to HVAC: ' + str(receivedJsonPayload))

    def UpdateHATargetTemperature(self):
        # Sync set temperature to HA. If 8℃ heating is active we set the temp in HA to 8℃ so that it shows the same as the AC display.
        if (int(self._acOptions['StHt']) == 1):
            self._target_temperature = 8
            _LOGGER.info('HA target temp set according to HVAC state to 8℃ since 8℃ heating mode is active')
        else:
            temp_c = self.decode_temp_c(SetTem=self._acOptions['SetTem'], TemRec=self._acOptions['TemRec']) # takes care of 1/2 degrees
            temp_f = self.gree_c_to_f(SetTem=self._acOptions['SetTem'], TemRec=self._acOptions['TemRec'])

            if (self._unit_of_measurement == "°C"):
                display_temp = temp_c
            elif(self._unit_of_measurement == "°F"):
                display_temp = temp_f
            else:
                display_temp = temp_c # default to deg c
                _LOGGER.error('Unknown unit of measurement: %s' % self._unit_of_measurement)

            self._target_temperature = display_temp

            if self._target_temp_entity_id:
                target_temp_state = self.hass.states.get(self._target_temp_entity_id)
                if target_temp_state:
                    attr = target_temp_state.attributes
                    self.hass.states.async_set(self._target_temp_entity_id, float(self._target_temperature), attr)

            _LOGGER.info(
                f"UpdateHATargetTemperature: HA target temp set to: {self._target_temperature} {self._unit_of_measurement}. "
                f"Device commands: SetTem: {self._acOptions['SetTem']}, TemRec: {self._acOptions['TemRec']}"
            )

    def UpdateHAOptions(self):
        # Sync HA with retreived HVAC options
        # WdSpd = fanspeed (0=auto), SvSt = powersave, Air = Air in/out (1=air in, 2=air out), Health = health
        # SwhSlp,SlpMod = sleep (both needed for sleep deactivation), StHt = 8℃ deg heating, Lig = lights, Blo = xfan
        # Sync current HVAC lights option to HA
        if (self._acOptions['Lig'] == 1):
            self._current_lights = STATE_ON
        elif (self._acOptions['Lig'] == 0):
            self._current_lights = STATE_OFF
        else:
            self._current_lights = STATE_UNKNOWN
        if self._lights_entity_id:
            lights_state = self.hass.states.get(self._lights_entity_id)
            if lights_state:
                attr = lights_state.attributes
                if self._current_lights in (STATE_ON, STATE_OFF):
                    self.hass.states.async_set(self._lights_entity_id, self._current_lights, attr)
        _LOGGER.debug('HA lights option set according to HVAC state to: ' + str(self._current_lights))
        # Sync current HVAC xfan option to HA
        if (self._acOptions['Blo'] == 1):
            self._current_xfan = STATE_ON
        elif (self._acOptions['Blo'] == 0):
            self._current_xfan = STATE_OFF
        else:
            self._current_xfan = STATE_UNKNOWN
        if self._xfan_entity_id:
            xfan_state = self.hass.states.get(self._xfan_entity_id)
            if xfan_state:
                attr = xfan_state.attributes
                if self._current_xfan in (STATE_ON, STATE_OFF):
                    self.hass.states.async_set(self._xfan_entity_id, self._current_xfan, attr)
        _LOGGER.debug('HA xfan option set according to HVAC state to: ' + str(self._current_xfan))
        # Sync current HVAC health option to HA
        if (self._acOptions['Health'] == 1):
            self._current_health = STATE_ON
        elif (self._acOptions['Health'] == 0):
            self._current_health = STATE_OFF
        else:
            self._current_health = STATE_UNKNOWN
        if self._health_entity_id:
            health_state = self.hass.states.get(self._health_entity_id)
            if health_state:
                attr = health_state.attributes
                if self._current_health in (STATE_ON, STATE_OFF):
                    self.hass.states.async_set(self._health_entity_id, self._current_health, attr)
        _LOGGER.debug('HA health option set according to HVAC state to: ' + str(self._current_health))
        # Sync current HVAC powersave option to HA
        if (self._acOptions['SvSt'] == 1):
            self._current_powersave = STATE_ON
        elif (self._acOptions['SvSt'] == 0):
            self._current_powersave = STATE_OFF
        else:
            self._current_powersave = STATE_UNKNOWN
        if self._powersave_entity_id:
            powersave_state = self.hass.states.get(self._powersave_entity_id)
            if powersave_state:
                attr = powersave_state.attributes
                if self._current_powersave in (STATE_ON, STATE_OFF):
                    self.hass.states.async_set(self._powersave_entity_id, self._current_powersave, attr)
        _LOGGER.debug('HA powersave option set according to HVAC state to: ' + str(self._current_powersave))
        # Sync current HVAC sleep option to HA
        if (self._acOptions['SwhSlp'] == 1) and (self._acOptions['SlpMod'] == 1):
            self._current_sleep = STATE_ON
        elif (self._acOptions['SwhSlp'] == 0) and (self._acOptions['SlpMod'] == 0):
            self._current_sleep = STATE_OFF
        else:
            self._current_sleep = STATE_UNKNOWN
        if self._sleep_entity_id:
            sleep_state = self.hass.states.get(self._sleep_entity_id)
            if sleep_state:
                attr = sleep_state.attributes
                if self._current_sleep in (STATE_ON, STATE_OFF):
                    self.hass.states.async_set(self._sleep_entity_id, self._current_sleep, attr)
        _LOGGER.debug('HA sleep option set according to HVAC state to: ' + str(self._current_sleep))
        # Sync current HVAC 8℃ heat option to HA
        if (self._acOptions['StHt'] == 1):
            self._current_eightdegheat = STATE_ON
        elif (self._acOptions['StHt'] == 0):
            self._current_eightdegheat = STATE_OFF
        else:
            self._current_eightdegheat = STATE_UNKNOWN
        if self._eightdegheat_entity_id:
            eightdegheat_state = self.hass.states.get(self._eightdegheat_entity_id)
            if eightdegheat_state:
                attr = eightdegheat_state.attributes
                if self._current_eightdegheat in (STATE_ON, STATE_OFF):
                    self.hass.states.async_set(self._eightdegheat_entity_id, self._current_eightdegheat, attr)
        _LOGGER.debug('HA 8℃ heat option set according to HVAC state to: ' + str(self._current_eightdegheat))
        # Sync current HVAC air option to HA
        if (self._acOptions['Air'] == 1):
            self._current_air = STATE_ON
        elif (self._acOptions['Air'] == 0):
            self._current_air = STATE_OFF
        else:
            self._current_air = STATE_UNKNOWN
        if self._air_entity_id:
            air_state = self.hass.states.get(self._air_entity_id)
            if air_state:
                attr = air_state.attributes
                if self._current_air in (STATE_ON, STATE_OFF):
                    self.hass.states.async_set(self._air_entity_id, self._current_air, attr)
        _LOGGER.debug('HA air option set according to HVAC state to: ' + str(self._current_air))
        # Sync current HVAC anti direct blow option to HA
        if self._has_anti_direct_blow:
            if (self._acOptions['AntiDirectBlow'] == 1):
                self._current_anti_direct_blow = STATE_ON
            elif (self._acOptions['AntiDirectBlow'] == 0):
                self._current_anti_direct_blow = STATE_OFF
            else:
                self._current_anti_direct_blow = STATE_UNKNOWN
            if self._anti_direct_blow_entity_id:
                adb_state = self.hass.states.get(self._anti_direct_blow_entity_id)
                if adb_state:
                    attr = adb_state.attributes
                    if self._current_anti_direct_blow in (STATE_ON, STATE_OFF):
                        self.hass.states.async_set(self._anti_direct_blow_entity_id, self._current_anti_direct_blow, attr)
            _LOGGER.debug('HA anti direct blow option set according to HVAC state to: ' + str(self._current_anti_direct_blow))

    def UpdateHAHvacMode(self):
        # Sync current HVAC operation mode to HA
        if (self._acOptions['Pow'] == 0):
            self._hvac_mode = HVACMode.OFF
        else:
            self._hvac_mode = self._hvac_modes[self._acOptions['Mod']]
        _LOGGER.debug('HA operation mode set according to HVAC state to: ' + str(self._hvac_mode))

    def UpdateHACurrentSwingMode(self):
        # Sync current HVAC Swing mode state to HA
        self._swing_mode = self._swing_modes[self._acOptions['SwUpDn']]
        _LOGGER.debug('HA swing mode set according to HVAC state to: ' + str(self._swing_mode))

    def UpdateHACurrentPresetMode(self):
        # Sync current HVAC preset mode state to HA
        self._preset_mode = self._preset_modes[self._acOptions['SwingLfRig']]
        _LOGGER.debug('HA preset mode set according to HVAC state to: ' + str(self._preset_mode))

    def UpdateHAFanMode(self):
        # Sync current HVAC Fan mode state to HA
        if (int(self._acOptions['Tur']) == 1):
            # Find Turbo mode in current language
            turbo_index = FAN_MODE_KEYS.index('turbo')
            self._fan_mode = self._fan_modes[turbo_index]
        elif (int(self._acOptions['Quiet']) >= 1):
            # Find Quiet mode in current language
            quiet_index = FAN_MODE_KEYS.index('quiet')
            self._fan_mode = self._fan_modes[quiet_index]
        else:
            self._fan_mode = self._fan_modes[int(self._acOptions['WdSpd'])]
        _LOGGER.debug('HA fan mode set according to HVAC state to: ' + str(self._fan_mode))

    def UpdateHACurrentTemperature(self):
        if not self._temp_sensor_entity_id:
            if self._has_temp_sensor:

                _LOGGER.debug("method UpdateHACurrentTemperature: TemSen: " + str(self._acOptions['TemSen']))

                if self._temp_sensor_offset is None:  # user hasn't chosen an offset
                    # User hasn't set automaticaly, so try to determine the offset
                    temp_c = self._process_temp_sensor(self._acOptions['TemSen'])
                    _LOGGER.debug("method UpdateHACurrentTemperature: User has not chosen an offset, using process_temp_sensor() to"
                                  " automatically determine offset.")
                else:
                    # User set
                    if self._temp_sensor_offset is True:
                        temp_c = self._acOptions['TemSen'] - TEMSEN_OFFSET

                    elif self._temp_sensor_offset is False:
                        temp_c = self._acOptions['TemSen']

                    _LOGGER.debug(f"method UpdateHACurrentTemperature: User has chosen an offset ({self._temp_sensor_offset})")

                temp_f = self.gree_c_to_f(SetTem=temp_c, TemRec=0) # Convert to Fahrenheit using TemRec bit

                if (self._unit_of_measurement == "°C"):
                    self._current_temperature = temp_c
                elif(self._unit_of_measurement == "°F"):
                    self._current_temperature = temp_f
                else:
                    _LOGGER.error("Unknown unit of measurement: %s" % self._unit_of_measurement)

                _LOGGER.debug('method UpdateHACurrentTemperature: HA current temperature set with device built-in temperature sensor state : ' + str(self._current_temperature) + str(self._unit_of_measurement))

    def UpdateHAStateToCurrentACState(self):
        self.UpdateHATargetTemperature()
        self.UpdateHAOptions()
        self.UpdateHAHvacMode()
        self.UpdateHACurrentSwingMode()
        if self._horizontal_swing:
            self.UpdateHACurrentPresetMode()
        self.UpdateHAFanMode()
        self.UpdateHACurrentTemperature()


    def SyncState(self, acOptions = {}):
        #Fetch current settings from HVAC
        _LOGGER.debug('Starting SyncState')

        if not self._temp_sensor_entity_id:
            if self._has_temp_sensor is None:
                _LOGGER.debug('Attempt to check whether device has an built-in temperature sensor')
                try:
                    temp_sensor = self.GreeGetValues(["TemSen"])
                except:
                    _LOGGER.debug('Could not determine whether device has an built-in temperature sensor. Retrying at next update()')
                else:
                    if temp_sensor:
                        self._has_temp_sensor = True
                        self._acOptions.update({'TemSen': None})
                        self._optionsToFetch.append("TemSen")
                        _LOGGER.debug('Device has an built-in temperature sensor')
                    else:
                        self._has_temp_sensor = False
                        _LOGGER.debug('Device has no built-in temperature sensor')

        if self._anti_direct_blow_entity_id:
            if self._has_anti_direct_blow is None:
                _LOGGER.debug('Attempt to check whether device has an anti direct blow feature')
                try:
                    anti_direct_blow = self.GreeGetValues(["AntiDirectBlow"])
                except:
                    _LOGGER.debug('Could not determine whether device has an anti direct blow feature. Retrying at next update()')
                else:
                    if anti_direct_blow:
                        self._has_anti_direct_blow = True
                        self._acOptions.update({'AntiDirectBlow': None})
                        self._optionsToFetch.append("AntiDirectBlow")
                        _LOGGER.debug('Device has an anti direct blow feature')
                    else:
                        self._has_anti_direct_blow = False
                        _LOGGER.debug('Device has no anti direct blow feature')

        if self._light_sensor_entity_id:
            if self._has_light_sensor is None:
                _LOGGER.debug('Attempt to check whether device has an built-in light sensor')
                try:
                    light_sensor = self.GreeGetValues(["LigSen"])
                except:
                    _LOGGER.debug('Could not determine whether device has an built-in light sensor. Retrying at next update()')
                else:
                    if light_sensor:
                        self._has_light_sensor = True
                        self._acOptions.update({'LigSen': None})
                        self._optionsToFetch.append("LigSen")
                        _LOGGER.debug('Device has an built-in light sensor')
                    else:
                        self._has_light_sensor = False
                        _LOGGER.debug('Device has no built-in light sensor')

        optionsToFetch = self._optionsToFetch

        try:
            currentValues = self.GreeGetValues(optionsToFetch)
        except:
            _LOGGER.info('Could not connect with device. ')
            if not self._disable_available_check:
                self._online_attempts +=1
                if (self._online_attempts == self._max_online_attempts):
                    _LOGGER.info('Could not connect with device %s times. Set it as offline.' % self._max_online_attempts)
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
            if not(acOptions == {}):
                self._acOptions = self.SetAcOptions(self._acOptions, acOptions)

            # Initialize the receivedJsonPayload variable (for return)
            receivedJsonPayload = ''

            # If not the first (boot) run, update state towards the HVAC
            if not (self._firstTimeRun):
                if not(acOptions == {}):
                    # loop used to send changed settings from HA to HVAC
                    self.SendStateToAc(self._timeout)
            else:
                # loop used once for Gree Climate initialisation only
                self._firstTimeRun = False

            # Update HA state to current HVAC state
            self.UpdateHAStateToCurrentACState()

            _LOGGER.debug('Finished SyncState')
            return receivedJsonPayload

    async def _async_temp_sensor_changed(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        old_state = event.data["old_state"]
        new_state = event.data["new_state"]
        s = str(old_state.state) if hasattr(old_state,'state') else "None"
        _LOGGER.info('temp_sensor state changed | ' + str(entity_id) + ' from ' + s + ' to ' + str(new_state.state))
        # Handle temperature changes.
        if new_state is None:
            return
        self._async_update_current_temp(new_state)
        return self.schedule_update_ha_state(True)

    @callback
    def _async_update_current_temp(self, state):
        _LOGGER.debug('method _async_update_current_temp Thermostat updated with changed temp_sensor state | ' + str(state.state))
        # Set unit = unit of measurement in the climate entity
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
        _LOGGER.debug('method _async_update_current_temp Unit updated with changed temp_sensor unit | ' + str(unit))
        try:
            _state = state.state
            if self.represents_float(_state):
                self._current_temperature = self.hass.config.units.temperature(float(_state), unit)
                _LOGGER.info('method _async_update_current_temp: Current temp: ' + str(self._current_temperature))
        except ValueError as ex:
            _LOGGER.error('method _async_update_current_temp: Unable to update from temp_sensor: %s' % ex)

    def represents_float(self, s):
        _LOGGER.debug('temp_sensor state represents_float |' + str(s))
        try:
            float(s)
            return True
        except ValueError:
            return False

    async def _async_lights_entity_state_changed(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        old_state = event.data["old_state"]
        new_state = event.data["new_state"]
        _LOGGER.info('lights_entity state changed | ' + str(entity_id) + ' from ' + (str(old_state.state) if hasattr(old_state,'state') else "None") + ' to ' + str(new_state.state))
        if new_state is None:
            return
        if new_state.state == "off" and (old_state is None or old_state.state is None):
            _LOGGER.info('lights_entity state changed to off, but old state is None. Ignoring to avoid beeps.')
            return
        if new_state.state is self._current_lights:
            # do nothing if state change is triggered due to Sync with HVAC
            return
        self._async_update_current_lights(new_state)
        return self.schedule_update_ha_state(True)

    @callback
    def _async_update_current_lights(self, state):
        _LOGGER.info('Updating HVAC with changed lights_entity state | ' + str(state.state))
        if state.state is STATE_ON:
            self.SyncState({'Lig': 1})
            return
        elif state.state is STATE_OFF:
            self.SyncState({'Lig': 0})
            return
        _LOGGER.error('Unable to update from lights_entity!')

    async def _async_xfan_entity_state_changed(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        old_state = event.data["old_state"]
        new_state = event.data["new_state"]
        _LOGGER.info('xfan_entity state changed | ' + str(entity_id) + ' from ' + (str(old_state.state) if hasattr(old_state,'state') else "None") + ' to ' + str(new_state.state))
        if new_state is None:
            return
        if new_state.state == "off" and (old_state is None or old_state.state is None):
            _LOGGER.info('xfan_entity state changed to off, but old state is None. Ignoring to avoid beeps.')
            return
        if new_state.state == self._current_xfan:
            # do nothing if state change is triggered due to Sync with HVAC
            return
        if not self._hvac_mode in (HVACMode.COOL, HVACMode.DRY):
            # do nothing if not in cool or dry mode
            _LOGGER.info('Cant set xfan in %s mode' % str(self._hvac_mode))
            return
        self._async_update_current_xfan(new_state)
        return self.schedule_update_ha_state(True)

    @callback
    def _async_update_current_xfan(self, state):
        _LOGGER.info('Updating HVAC with changed xfan_entity state | ' + str(state.state))
        if state.state is STATE_ON:
            self.SyncState({'Blo': 1})
            return
        elif state.state is STATE_OFF:
            self.SyncState({'Blo': 0})
            return
        _LOGGER.error('Unable to update from xfan_entity!')

    async def _async_health_entity_state_changed(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        old_state = event.data["old_state"]
        new_state = event.data["new_state"]
        _LOGGER.info('health_entity state changed | ' + str(entity_id) + ' from ' + (str(old_state.state) if hasattr(old_state,'state') else "None") + ' to ' + str(new_state.state))
        if new_state is None:
            return
        if new_state.state == "off" and (old_state is None or old_state.state is None):
            _LOGGER.info('health_entity state changed to off, but old state is None. Ignoring to avoid beeps.')
            return
        if new_state.state is self._current_health:
            # do nothing if state change is triggered due to Sync with HVAC
            return
        self._async_update_current_health(new_state)
        return self.schedule_update_ha_state(True)

    @callback
    def _async_update_current_health(self, state):
        _LOGGER.info('Updating HVAC with changed health_entity state | ' + str(state.state))
        if state.state is STATE_ON:
            self.SyncState({'Health': 1})
            return
        elif state.state is STATE_OFF:
            self.SyncState({'Health': 0})
            return
        _LOGGER.error('Unable to update from health_entity!')

    async def _async_powersave_entity_state_changed(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        old_state = event.data["old_state"]
        new_state = event.data["new_state"]
        _LOGGER.info('powersave_entity state changed | ' + str(entity_id) + ' from ' + (str(old_state.state) if hasattr(old_state,'state') else "None") + ' to ' + str(new_state.state))
        if new_state is None:
            return
        if new_state.state == "off" and (old_state is None or old_state.state is None):
            _LOGGER.info('powersave_entity state changed to off, but old state is None. Ignoring to avoid beeps.')
            return
        if new_state.state is self._current_powersave:
            # do nothing if state change is triggered due to Sync with HVAC
            return
        if not hasattr(self, "_hvac_mode"):
            _LOGGER.info('Cant set powersave in unknown mode')
            return
        if self._hvac_mode is None:
            _LOGGER.info('Cant set powersave in unknown HVAC mode (self._hvac_mode is None)')
            return
        if not self._hvac_mode in (HVACMode.COOL):
            # do nothing if not in cool mode
            _LOGGER.info('Cant set powersave in %s mode' % str(self._hvac_mode))
            return
        self._async_update_current_powersave(new_state)
        return self.schedule_update_ha_state(True)

    @callback
    def _async_update_current_powersave(self, state):
        _LOGGER.info('Udating HVAC with changed powersave_entity state | ' + str(state.state))
        if state.state is STATE_ON:
            self.SyncState({'SvSt': 1})
            return
        elif state.state is STATE_OFF:
            self.SyncState({'SvSt': 0})
            return
        _LOGGER.error('Unable to update from powersave_entity!')


    async def _async_sleep_entity_state_changed(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        old_state = event.data["old_state"]
        new_state = event.data["new_state"]
        _LOGGER.info('sleep_entity state changed | ' + str(entity_id) + ' from ' + (str(old_state.state) if hasattr(old_state,'state') else "None") + ' to ' + str(new_state.state))
        if new_state is None:
            return
        if new_state.state == "off" and (old_state is None or old_state.state is None):
            _LOGGER.info('sleep_entity state changed to off, but old state is None. Ignoring to avoid beeps.')
            return
        if new_state.state is self._current_sleep:
            # do nothing if state change is triggered due to Sync with HVAC
            return
        if not self._hvac_mode in (HVACMode.COOL, HVACMode.HEAT):
            # do nothing if not in cool or heat mode
            _LOGGER.info('Cant set sleep in %s mode' % str(self._hvac_mode))
            return
        self._async_update_current_sleep(new_state)
        return self.schedule_update_ha_state(True)

    @callback
    def _async_update_current_sleep(self, state):
        _LOGGER.info('Updating HVAC with changed sleep_entity state | ' + str(state.state))
        if state.state is STATE_ON:
            self.SyncState({'SwhSlp': 1, 'SlpMod': 1})
            return
        elif state.state is STATE_OFF:
            self.SyncState({'SwhSlp': 0, 'SlpMod': 0})
            return
        _LOGGER.error('Unable to update from sleep_entity!')

    async def _async_eightdegheat_entity_state_changed(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        old_state = event.data["old_state"]
        new_state = event.data["new_state"]
        _LOGGER.info('eightdegheat_entity state changed | ' + str(entity_id) + ' from ' + (str(old_state.state) if hasattr(old_state,'state') else "None") + ' to ' + str(new_state.state))
        if new_state is None:
            return
        if new_state.state == "off" and (old_state is None or old_state.state is None):
            _LOGGER.info('eightdegheat_entity state changed to off, but old state is None. Ignoring to avoid beeps.')
            return
        if new_state.state == self._current_eightdegheat:
            # do nothing if state change is triggered due to Sync with HVAC
            return
        if not self._hvac_mode in (HVACMode.HEAT):
            # do nothing if not in heat mode
            _LOGGER.info('Cant set 8℃ heat in %s mode' % str(self._hvac_mode))
            return
        self._async_update_current_eightdegheat(new_state)
        return self.schedule_update_ha_state(True)

    @callback
    def _async_update_current_eightdegheat(self, state):
        _LOGGER.info('Updating HVAC with changed eightdegheat_entity state | ' + str(state.state))
        if state.state is STATE_ON:
            self.SyncState({'StHt': 1})
            return
        elif state.state is STATE_OFF:
            self.SyncState({'StHt': 0})
            return
        _LOGGER.error('Unable to update from eightdegheat_entity!')

    def _async_air_entity_state_changed(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        old_state = event.data["old_state"]
        new_state = event.data["new_state"]
        _LOGGER.info('air_entity state changed | ' + str(entity_id) + ' from ' + (str(old_state.state) if hasattr(old_state,'state') else "None") + ' to ' + str(new_state.state))
        if new_state is None:
            return
        if new_state.state == "off" and (old_state is None or old_state.state is None):
            _LOGGER.info('air_entity state changed to off, but old state is None. Ignoring to avoid beeps.')
            return
        if new_state.state is self._current_air:
            # do nothing if state change is triggered due to Sync with HVAC
            return
        self._async_update_current_air(new_state)
        return self.schedule_update_ha_state(True)

    @callback
    def _async_update_current_air(self, state):
        _LOGGER.info('Updating HVAC with changed air_entity state | ' + str(state.state))
        if state.state is STATE_ON:
            self.SyncState({'Air': 1})
            return
        elif state.state is STATE_OFF:
            self.SyncState({'Air': 0})
            return
        _LOGGER.error('Unable to update from air_entity!')

    def _async_anti_direct_blow_entity_state_changed(self, event: Event[EventStateChangedData]) -> None:
        if self._has_anti_direct_blow:
            entity_id = event.data["entity_id"]
            old_state = event.data["old_state"]
            new_state = event.data["new_state"]
            _LOGGER.info('anti_direct_blow_entity state changed | ' + str(entity_id) + ' from ' + (str(old_state.state) if hasattr(old_state,'state') else "None") + ' to ' + str(new_state.state))
            if new_state is None:
                return
            if new_state.state == "off" and (old_state is None or old_state.state is None):
                _LOGGER.info('anti_direct_blow_entity state changed to off, but old state is None. Ignoring to avoid beeps.')
                return
            if new_state.state == self._current_anti_direct_blow:
                # do nothing if state change is triggered due to Sync with HVAC
                return
            self._async_update_current_anti_direct_blow(new_state)
            return self.schedule_update_ha_state(True)

    @callback
    def _async_update_current_anti_direct_blow(self, state):
        _LOGGER.info('Updating HVAC with changed anti_direct_blow_entity state | ' + str(state.state))
        if state.state is STATE_ON:
            self.SyncState({'AntiDirectBlow': 1})
            return
        elif state.state is STATE_OFF:
            self.SyncState({'AntiDirectBlow': 0})
            return
        _LOGGER.error('Unable to update from anti_direct_blow_entity!')

    def _async_light_sensor_entity_state_changed(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        old_state = event.data["old_state"]
        new_state = event.data["new_state"]
        _LOGGER.info('light_sensor_entity state changed | ' + str(entity_id) + ' from ' + (str(old_state.state) if hasattr(old_state,'state') else "None") + ' to ' + str(new_state.state))
        if new_state is None:
            return
        if new_state.state == "off" and (old_state is None or old_state.state is None):
            _LOGGER.info('light_sensor_entity state changed to off, but old state is None. Ignoring to avoid beeps.')
            return
        if new_state.state is self._enable_light_sensor:
            # do nothing if state change is triggered due to Sync with HVAC
            return
        self._async_update_light_sensor(new_state)
        return self.schedule_update_ha_state(True)

    @callback
    def _async_update_light_sensor(self, state):
        _LOGGER.info('Updating enable_light_sensor with changed light_sensor_entity state | ' + str(state.state))
        if state.state is STATE_ON:
            self._enable_light_sensor = True
            if self._has_light_sensor and self._hvac_mode != HVACMode.OFF:
                self.SyncState({'Lig': 1, 'LigSen': 0})
            return
        elif state.state is STATE_OFF:
            self._enable_light_sensor = False
            return
        _LOGGER.error('Unable to update from light_sensor_entity!')

    def _async_auto_light_entity_state_changed(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        old_state = event.data["old_state"]
        new_state = event.data["new_state"]
        _LOGGER.info('auto_light_entity state changed | ' + str(entity_id) + ' from ' + (str(old_state.state) if hasattr(old_state,'state') else "None") + ' to ' + str(new_state.state))
        if new_state is None:
            return
        if new_state.state == "off" and (old_state is None or old_state.state is None):
            _LOGGER.info('auto_light_entity state changed to off, but old state is None. Ignoring to avoid beeps.')
            return
        if not hasattr(self, "_auto_light"):
            _LOGGER.info('auto_light_entity state changed | auto_light not (yet) initialized. Skipping.')
            return
        if new_state.state is self._auto_light:
            # do nothing if state change is triggered due to Sync with HVAC
            return
        self._async_update_auto_light(new_state)
        return self.schedule_update_ha_state(True)

    @callback
    def _async_update_auto_light(self, state):
        _LOGGER.info('Updating auto_light with changed auto_light_entity state | ' + str(state.state))
        if state.state is STATE_ON:
            self._auto_light = True
            if (self._hvac_mode != HVACMode.OFF):
                self.SyncState({'Lig': 1})
            else:
                self.SyncState({'Lig': 0})
            return
        elif state.state is STATE_OFF:
            self._auto_light = False
            return
        _LOGGER.error('Unable to update from auto_light_entity!')

    def _async_auto_xfan_entity_state_changed(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        old_state = event.data["old_state"]
        new_state = event.data["new_state"]
        _LOGGER.info('auto_xfan_entity state changed | ' + str(entity_id) + ' from ' + (str(old_state.state) if hasattr(old_state,'state') else "None") + ' to ' + str(new_state.state))
        if new_state is None:
            return
        if new_state.state == "off" and (old_state is None or old_state.state is None):
            _LOGGER.info('auto_xfan_entity state changed to off, but old state is None. Ignoring to avoid beeps.')
            return
        if not hasattr(self, "_auto_xfan"):
            _LOGGER.info('auto_xfan_entity state changed | auto_xfan not (yet) initialized. Skipping.')
            return
        if new_state.state is self._auto_xfan:
            # do nothing if state change is triggered due to Sync with HVAC
            return
        self._async_update_auto_xfan(new_state)
        return self.schedule_update_ha_state(True)

    @callback
    def _async_update_auto_xfan(self, state):
        _LOGGER.info('Updating auto_xfan with changed auto_xfan_entity state | ' + str(state.state))
        if state.state is STATE_ON:
            self._auto_xfan = True
            return
        elif state.state is STATE_OFF:
            self._auto_xfan = False
            self.SyncState({'Blo': 0})
            return
        _LOGGER.error('Unable to update from auto_xfan_entity!')

    def _async_target_temp_entity_state_changed(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        old_state = event.data["old_state"]
        new_state = event.data["new_state"]
        _LOGGER.info('target_temp_entity state changed | ' + str(entity_id) + ' from ' + (str(old_state.state) if hasattr(old_state,'state') else "None") + ' to ' + str(new_state.state))
        if new_state is None:
            return
        if new_state.state == "off" and (old_state is None or old_state.state is None):
            _LOGGER.info('target_temp_entity state changed to off, but old state is None. Ignoring to avoid beeps.')
            return
        # check if new_state.state is a number
        if self.represents_float(new_state.state):
            if int(float(new_state.state)) is self._target_temperature:
                # do nothing if state change is triggered due to Sync with HVAC
                return
        self._async_update_current_target_temp(new_state)
        return self.schedule_update_ha_state(True)

    @callback
    def _async_update_current_target_temp(self, state):

        if not self.represents_float(state.state):
            _LOGGER.error('Unable to update from target_temp_entity! State is: %s' % state.state)
            return

        s = int(float(state.state))
        _LOGGER.info('method _async_update_current_target_temp: Updating HVAC with changed target_temp_entity state | ' + str(s))
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) # specific to this temperature sensor.
        _LOGGER.info('method _async_update_current_target_temp: target_temp_entity state unit | ' + str(unit))

        if (unit == "°C"):
            SetTem, TemRec = self.encode_temp_c(T=s) # takes care of 1/2 degrees
        elif (unit == "°F"):
            SetTem, TemRec = self.gree_f_to_c(desired_temp_f=s)
        else:
            _LOGGER.error('Unable to update from target_temp_entity! Units not °C or °F')
            return

        self.SyncState({'SetTem': int(SetTem), 'TemRec': int(TemRec)})

        _LOGGER.info('method _async_update_current_target_temp: Set Temp to ' + str(s) + str(unit)
                     + ' ->  SyncState with SetTem=' + str(SetTem) + ', SyncState with TemRec=' + str(TemRec))

    @callback
    async def _async_beeper_entity_state_changed(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        old_state = event.data["old_state"]
        new_state = event.data["new_state"]
        _LOGGER.info(f'Beeper entity {entity_id} state changed from '
                    f'{(str(old_state.state) if hasattr(old_state,"state") else "None")} '
                    f'to {str(new_state.state)}')

        if new_state is None:
            return

        if new_state.state == STATE_ON:
            self._current_beeper_enabled = True # Silent mode ON
            _LOGGER.info('Silent mode enabled (beeper will be turned off with commands).')
        else: # STATE_OFF or other
            self._current_beeper_enabled = False # Silent mode OFF
            _LOGGER.info('Silent mode disabled (beeper will be turned on with commands).')


    @property
    def should_poll(self):
        _LOGGER.debug('should_poll()')
        # Return the polling state.
        return True

    @property
    def available(self):
        if self._disable_available_check:
            return True
        else:
            if self._device_online:
                _LOGGER.info('available(): Device is online')
                return True
            else:
                _LOGGER.info('available(): Device is offline')
                return False

    def update(self):
        _LOGGER.debug('update()')
        if not self._encryption_key:
            if self.encryption_version == 1:
                if self.GetDeviceKey():
                    self.SyncState()
            elif self.encryption_version == 2:
                if self.GetDeviceKeyGCM():
                    self.SyncState()
            else:
                _LOGGER.error('Encryption version %s is not implemented.' % encryption_version)
        else:
            self.SyncState()

    @property
    def name(self):
        _LOGGER.debug('name(): ' + str(self._name))
        # Return the name of the climate device.
        return self._name

    @property
    def temperature_unit(self):
        _LOGGER.debug('temperature_unit(): ' + str(self._unit_of_measurement))
        # Return the unit of measurement.
        return self._unit_of_measurement

    @property
    def current_temperature(self):
        _LOGGER.debug('current_temperature(): ' + str(self._current_temperature))
        # Return the current temperature.
        return self._current_temperature

    @property
    def min_temp(self):
        if (self._unit_of_measurement == "°C"):
            MIN_TEMP = MIN_TEMP_C
        else:
            MIN_TEMP = MIN_TEMP_F

        _LOGGER.debug('min_temp(): ' + str(MIN_TEMP))
        # Return the minimum temperature.
        return MIN_TEMP

    @property
    def max_temp(self):
        if (self._unit_of_measurement == "°C"):
            MAX_TEMP = MAX_TEMP_C
        else:
            MAX_TEMP = MAX_TEMP_F

        _LOGGER.debug('max_temp(): ' + str(MAX_TEMP))
        # Return the maximum temperature.
        return MAX_TEMP

    @property
    def target_temperature(self):
        _LOGGER.debug('target_temperature(): ' + str(self._target_temperature))
        # Return the temperature we try to reach.
        return self._target_temperature

    @property
    def target_temperature_step(self):
        _LOGGER.debug('target_temperature_step(): ' + str(self._target_temperature_step))
        # Return the supported step of target temperature.
        return self._target_temperature_step

    @property
    def hvac_mode(self):
        _LOGGER.debug('hvac_mode(): ' + str(self._hvac_mode))
        # Return current operation mode ie. heat, cool, idle.
        return self._hvac_mode

    @property
    def swing_mode(self):
        _LOGGER.debug('swing_mode(): ' + str(self._swing_mode))
        # get the current swing mode
        return self._swing_mode

    @property
    def swing_modes(self):
        _LOGGER.debug('swing_modes(): ' + str(self._swing_modes))
        # get the list of available swing modes
        return self._swing_modes

    @property
    def preset_mode(self):
        if hasattr(self, "_horizontal_swing") and self._horizontal_swing:
            _LOGGER.debug('preset_mode(): ' + str(self._preset_mode))
            # get the current preset mode
            return self._preset_mode
        else:
            return None

    @property
    def preset_modes(self):
        _LOGGER.debug('preset_modes(): ' + str(self._preset_modes))
        # get the list of available preset modes
        return self._preset_modes

    @property
    def hvac_modes(self):
        _LOGGER.debug('hvac_modes(): ' + str(self._hvac_modes))
        # Return the list of available operation modes.
        return self._hvac_modes

    @property
    def fan_mode(self):
        _LOGGER.debug('fan_mode(): ' + str(self._fan_mode))
        # Return the fan mode.
        return self._fan_mode

    @property
    def fan_modes(self):
        _LOGGER.debug('fan_list(): ' + str(self._fan_modes))
        # Return the list of available fan modes.
        return self._fan_modes

    @property
    def supported_features(self):
        if hasattr(self, "_horizontal_swing") and self._horizontal_swing:
            sf = SUPPORT_FLAGS | ClimateEntityFeature.PRESET_MODE
        else:
            sf = SUPPORT_FLAGS
        _LOGGER.debug('supported_features(): ' + str(sf))
        # Return the list of supported features.
        return sf

    @property
    def unique_id(self):
        # Return unique_id
        return self._unique_id

    def set_temperature(self, **kwargs):
        s = kwargs.get(ATTR_TEMPERATURE)

        _LOGGER.info('set_temperature(): ' + str(s) + str(self._unit_of_measurement))
        # Set new target temperatures.
        if s is not None:
            # do nothing if temperature is none
            if not (self._acOptions['Pow'] == 0):
                # do nothing if HVAC is switched off

                if (self._unit_of_measurement == "°C"):
                    SetTem, TemRec = self.encode_temp_c(T=s) # takes care of 1/2 degrees
                elif (self._unit_of_measurement == "°F"):
                    SetTem, TemRec = self.gree_f_to_c(desired_temp_f=s)
                else:
                    _LOGGER.error('Unable to set temperature. Units not set to °C or °F')
                    return

                self.SyncState({'SetTem': int(SetTem), 'TemRec': int(TemRec)})
                _LOGGER.debug('method set_temperature: Set Temp to ' + str(s) + str(self._unit_of_measurement)
                             + ' ->  SyncState with SetTem=' + str(SetTem) + ', SyncState with TemRec=' + str(TemRec))

                self.schedule_update_ha_state()

    def set_swing_mode(self, swing_mode):
        _LOGGER.info('Set swing mode(): ' + str(swing_mode))
        # set the swing mode
        if not (self._acOptions['Pow'] == 0):
            # do nothing if HVAC is switched off
            try:
                swing_index = self._swing_modes.index(swing_mode)
                _LOGGER.info('SyncState with SwUpDn=' + str(swing_index))
                self.SyncState({'SwUpDn': swing_index})
                self.schedule_update_ha_state()
            except ValueError:
                _LOGGER.error(f'Unknown swing mode: {swing_mode}')
                return

    def set_preset_mode(self, preset_mode):
        if not (self._acOptions['Pow'] == 0):
            # do nothing if HVAC is switched off
            try:
                preset_index = self._preset_modes.index(preset_mode)
                _LOGGER.info('SyncState with SwingLfRig=' + str(preset_index))
                self.SyncState({'SwingLfRig': preset_index})
                self.schedule_update_ha_state()
            except ValueError:
                _LOGGER.error(f'Unknown preset mode: {preset_mode}')
                return

    def set_fan_mode(self, fan):
        _LOGGER.info('set_fan_mode(): ' + str(fan))
        # Set the fan mode.
        if not (self._acOptions['Pow'] == 0):
            try:
                fan_index = self._fan_modes.index(fan)
                fan_key = get_mode_key_by_index('fan_mode', fan_index)

                # Check if this is turbo mode
                if fan_key == 'turbo':
                    _LOGGER.info('Enabling turbo mode')
                    self.SyncState({'Tur': 1, 'Quiet': 0})
                # Check if this is quiet mode
                elif fan_key == 'quiet':
                    _LOGGER.info('Enabling quiet mode')
                    self.SyncState({'Tur': 0, 'Quiet': 1})
                else:
                    _LOGGER.info('Setting normal fan mode to ' + str(fan_index))
                    self.SyncState({'WdSpd': str(fan_index), 'Tur': 0, 'Quiet': 0})

                self.schedule_update_ha_state()
            except ValueError:
                _LOGGER.error(f'Unknown fan mode: {fan}')
                return

    def set_hvac_mode(self, hvac_mode):
        _LOGGER.info('set_hvac_mode(): ' + str(hvac_mode))
        # Set new operation mode.
        c = {}
        if (hvac_mode == HVACMode.OFF):
            c.update({'Pow': 0})
            if hasattr(self, "_auto_light") and self._auto_light:
                c.update({'Lig': 0})
                if hasattr(self, "_has_light_sensor") and self._has_light_sensor and hasattr(self, "_enable_light_sensor") and self._enable_light_sensor:
                    c.update({'LigSen': 1})
        else:
            c.update({'Pow': 1, 'Mod': self.hvac_modes.index(hvac_mode)})
            if hasattr(self, "_auto_light") and self._auto_light:
                c.update({'Lig': 1})
                if hasattr(self, "_has_light_sensor") and self._has_light_sensor and hasattr(self, "_enable_light_sensor") and self._enable_light_sensor:
                    c.update({'LigSen': 0})
            if hasattr(self, "_auto_xfan") and self._auto_xfan:
                if (hvac_mode == HVACMode.COOL) or (hvac_mode == HVACMode.DRY):
                    c.update({'Blo': 1})
        self.SyncState(c)
        self.schedule_update_ha_state()

    def turn_on(self):
        _LOGGER.info('turn_on(): ')
        # Turn on.
        c = {'Pow': 1}
        if hasattr(self, "_auto_light") and self._auto_light:
            c.update({'Lig': 1})
            if hasattr(self, "_has_light_sensor") and self._has_light_sensor and hasattr(self, "_enable_light_sensor") and self._enable_light_sensor:
                c.update({'LigSen': 0})
        self.SyncState(c)
        self.schedule_update_ha_state()

    def turn_off(self):
        _LOGGER.info('turn_off(): ')
        # Turn off.
        c = {'Pow': 0}
        if hasattr(self, "_auto_light") and self._auto_light:
            c.update({'Lig': 0})
            if hasattr(self, "_has_light_sensor") and self._has_light_sensor and hasattr(self, "_enable_light_sensor") and self._enable_light_sensor:
                c.update({'LigSen': 1})
        self.SyncState(c)
        self.schedule_update_ha_state()

    async def async_added_to_hass(self):
        _LOGGER.info('Gree climate device added to hass()')
        self.update()

    async def async_will_remove_from_hass(self) -> None:
        """Clean up when entity is removed."""
        for name, entity_id, unsub in self._listeners:
            _LOGGER.debug('Deregistering %s listener for %s', name, entity_id)
            unsub()
        self._listeners.clear()


    def gree_f_to_c(self, desired_temp_f):
        # Convert to fractional C values for AC
        # See: https://github.com/tomikaa87/gree-remote
        SetTem = round((desired_temp_f - 32.0) * 5.0 / 9.0)
        TemRec = (int)((((desired_temp_f - 32.0) * 5.0 / 9.0) - SetTem) > -0.001)

        return SetTem, TemRec

    def gree_c_to_f(self,SetTem, TemRec):
        # Convert SetTem back to the minimum and maximum Fahrenheit before rounding
        # We consider the worst case scenario: SetTem could be the result of rounding from any value in a range
        # If TemRec is 1, it indicates the value was closer to the upper range of the rounding
        # If TemRec is 0, it indicates the value was closer to the lower range

        if TemRec == 1:
            # SetTem is closer to its higher bound, so we consider SetTem as the lower limit
            min_celsius = SetTem
            max_celsius = SetTem + 0.4999  # Just below the next rounding threshold
        else:
            # SetTem is closer to its lower bound, so we consider SetTem-1 as the potential lower limit
            min_celsius = SetTem - 0.4999  # Just above the previous rounding threshold
            max_celsius = SetTem

        # Convert these Celsius values back to Fahrenheit
        min_fahrenheit = (min_celsius * 9.0 / 5.0) + 32.0
        max_fahrenheit = (max_celsius * 9.0 / 5.0) + 32.0

        int_fahrenheit = round((min_fahrenheit + max_fahrenheit) / 2.0)

        return int_fahrenheit

    def encode_temp_c(self,T):
        """
        Used for encoding 1/2 degree Celsius values.
        Encode any floating‐point temperature T into:
          ‣ temp_int: the integer (°C) portion of the nearest 0.0/0.5 step,
          ‣ half_bit: 1 if the nearest step has a ".5", else 0.

        This "finds the closest multiple of 0.5" to T, then:
          n = round(T * 2)
          temp_int = n >> 1      (i.e. floor(n/2))
          half_bit = n & 1       (1 if it's an odd half‐step)
        """
        # 1) Compute "twice T" and round to nearest integer:
        #    math.floor(T * 2 + 0.5) is equivalent to rounding ties upward.
        n = int(round(T * 2))

        # 2) The low bit of n says ".5" (odd) versus ".0" (even):
        TemRec = n & 1

        # 3) Shifting right by 1 gives floor(n/2), i.e. the integer °C of that nearest half‐step:
        SetTem = n >> 1

        return SetTem, TemRec

    def decode_temp_c(self,SetTem: int, TemRec: int) -> float:
        """
        Given:
          SetTem = the "rounded-down" integer (⌊T⌋ or for negatives, floor(T))
          TemRec = 0 or 1, where 1 means "there was a 0.5"
        Returns the original temperature as a float.
        """
        return SetTem + (0.5 if TemRec else 0.0)

    class TempOffsetResolver:
        """
        Detect whether this sensor reports temperatures in °C
        or in (°C + 40).  Continues to check, and bases decision
        on historical min and max raw values, since there are extreme
        cases which would result in a switch. Two running values are
        stored (min & max raw).

        Note: This could be simplified by just using 40C as a max point
        for the unoffset case and a min point for the offset case. But
        this doesn't account for the marginal cases around 40C as well.

        Example:

        if raw < 40:
            return raw
        else:
            return raw - 40

        """


        def __init__(self,
                     indoor_min: float = -15.0,  # coldest plausible indoor °C
                     indoor_max: float = 40.0,  # hottest plausible indoor °C
                     offset:     float = TEMSEN_OFFSET,  # device's fixed offset
                     margin:     float = 2.0):  # tolerance before "impossible":
            self._lo_lim      = indoor_min - margin
            self._hi_lim      = indoor_max + margin
            self._offset      = offset

            self._min_raw: float | None = None
            self._max_raw: float | None = None
            self._has_offset: bool | None = None   # undecided until True/False

        def __call__(self, raw: float) -> float:

            # ---- original path (still undecided) ------------------------------
            if self._min_raw is None or raw < self._min_raw:
                self._min_raw = raw
            if self._max_raw is None or raw > self._max_raw:
                self._max_raw = raw

            self._evaluate()  # evaluate every time, so it can change it's mind as needed

            return raw - self._offset if self._has_offset else raw

        def _evaluate(self) -> None:
            """
            Compare the raw range and (raw-offset) range against the
            plausible indoor envelope.  Whichever fits strictly better wins.
            """
            lo, hi = self._min_raw, self._max_raw

            penalty_no  = self._penalty(lo,             hi)
            penalty_off = self._penalty(lo - self._offset,
                                        hi - self._offset)

            if penalty_no == penalty_off:
                return # still ambiguous – keep collecting data

            self._has_offset = penalty_off < penalty_no

        def _penalty(self, lo: float, hi: float) -> float:
            """
            Distance (°C) by which the [lo, hi] interval lies outside
            the indoor envelope.  Zero means entirely plausible.
            """
            pen = 0.0
            if lo < self._lo_lim:
                pen += self._lo_lim - lo
            if hi > self._hi_lim:
                pen += hi - self._hi_lim
            return pen
