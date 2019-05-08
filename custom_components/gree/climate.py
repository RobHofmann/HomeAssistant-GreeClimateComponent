#!/usr/bin/python
# Do basic imports
import importlib.util
import socket
import base64
import re
import sys

import asyncio
import logging
import binascii
import os.path
import voluptuous as vol
import homeassistant.helpers.config_validation as cv

from homeassistant.components.climate import (ClimateDevice, PLATFORM_SCHEMA)
from homeassistant.components.climate.const import (SUPPORT_OPERATION_MODE, SUPPORT_TARGET_TEMPERATURE, SUPPORT_FAN_MODE, SUPPORT_SWING_MODE, SUPPORT_ON_OFF, STATE_AUTO, STATE_COOL, STATE_DRY, STATE_FAN_ONLY, STATE_HEAT)
from homeassistant.const import (ATTR_UNIT_OF_MEASUREMENT, ATTR_TEMPERATURE, CONF_NAME, CONF_HOST, CONF_PORT, CONF_MAC, CONF_TIMEOUT, CONF_CUSTOMIZE, STATE_ON, STATE_OFF, STATE_UNKNOWN)
from homeassistant.helpers.event import (async_track_state_change)
from homeassistant.core import callback
from homeassistant.helpers.restore_state import RestoreEntity
from configparser import ConfigParser
from Crypto.Cipher import AES
try: import simplejson
except ImportError: import json as simplejson

REQUIREMENTS = ['pycryptodome']

_LOGGER = logging.getLogger(__name__)

SUPPORT_FLAGS = SUPPORT_TARGET_TEMPERATURE | SUPPORT_OPERATION_MODE | SUPPORT_FAN_MODE | SUPPORT_SWING_MODE | SUPPORT_ON_OFF

CONF_MIN_TEMP = 'min_temp'
CONF_MAX_TEMP = 'max_temp'
CONF_TARGET_TEMP = 'target_temp'
CONF_TARGET_TEMP_STEP = 'target_temp_step'
CONF_TEMP_SENSOR = 'temp_sensor'
CONF_OPERATIONS = 'operations'
CONF_FAN_MODES = 'fan_modes'
CONF_SWING_UPDN_MODES = 'swing_updn_modes'
CONF_DEFAULT_OPERATION = 'default_operation'
CONF_DEFAULT_FAN_MODE = 'default_fan_mode'
CONF_DEFAULT_SWING_UPDN_MODE = 'default_swing_updn_mode'
CONF_ENCRYPTION_KEY = 'encryption_key'
CONF_UID = 'uid'

CONF_DEFAULT_OPERATION_FROM_IDLE = 'default_operation_from_idle'

DEFAULT_NAME = 'Gree Climate'
DEFAULT_TIMEOUT = 10
DEFAULT_RETRY = 3
DEFAULT_MIN_TEMP = 16
DEFAULT_MAX_TEMP = 30
DEFAULT_TARGET_TEMP = 20
DEFAULT_TARGET_TEMP_STEP = 1
DEFAULT_OPERATION_LIST = [STATE_AUTO, STATE_COOL, STATE_DRY, STATE_FAN_ONLY, STATE_HEAT]
DEFAULT_FAN_MODE_LIST = [STATE_AUTO, 'Low', 'Medium-Low', 'Medium', 'Medium-High', 'High', 'Turbo', 'Quiet']
DEFAULT_SWING_UPDN_MODES = ['Default', 'Swing in full range', 'Fixed in the upmost position', 'Fixed in the middle-up position', 'Fixed in the middle position', 'Fixed in the middle-low position', 'Fixed in the lowest position', 'Swing in the downmost region', 'Swing in the middle-low region', 'Swing in the middle region', 'Swing in the middle-up region', 'Swing in the upmost region']
DEFAULT_OPERATION = 'Cool'
DEFAULT_FAN_MODE = 'Auto'
DEFAULT_SWING_UPDN_MODE = 'Fixed in the upmost position'

CUSTOMIZE_SCHEMA = vol.Schema({
    vol.Optional(CONF_OPERATIONS): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional(CONF_FAN_MODES): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional(CONF_SWING_UPDN_MODES): vol.All(cv.ensure_list, [cv.string])
})

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Required(CONF_HOST): cv.string,
    vol.Required(CONF_PORT): cv.positive_int,
    vol.Required(CONF_MAC): cv.string,
    vol.Optional(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): cv.positive_int, 
    vol.Optional(CONF_MIN_TEMP, default=DEFAULT_MIN_TEMP): cv.positive_int,
    vol.Optional(CONF_MAX_TEMP, default=DEFAULT_MAX_TEMP): cv.positive_int,
    vol.Optional(CONF_TARGET_TEMP, default=DEFAULT_TARGET_TEMP): cv.positive_int,
    vol.Optional(CONF_TARGET_TEMP_STEP, default=DEFAULT_TARGET_TEMP_STEP): cv.positive_int,
    vol.Optional(CONF_TEMP_SENSOR): cv.entity_id,
    vol.Optional(CONF_CUSTOMIZE, default={}): CUSTOMIZE_SCHEMA,
    vol.Optional(CONF_DEFAULT_OPERATION, default=DEFAULT_OPERATION): cv.string,
    vol.Optional(CONF_DEFAULT_FAN_MODE, default=DEFAULT_FAN_MODE): cv.string,
    vol.Optional(CONF_DEFAULT_SWING_UPDN_MODE, default = DEFAULT_SWING_UPDN_MODE): cv.string,
    vol.Optional(CONF_DEFAULT_OPERATION_FROM_IDLE): cv.string,
    vol.Optional(CONF_ENCRYPTION_KEY): cv.string,
    vol.Optional(CONF_UID): cv.positive_int
})

@asyncio.coroutine
def async_setup_platform(hass, config, async_add_devices, discovery_info=None):
    name = config.get(CONF_NAME)
    ip_addr = config.get(CONF_HOST)
    port = config.get(CONF_PORT)
    mac_addr = config.get(CONF_MAC).encode().replace(b':', b'')
      
    min_temp = config.get(CONF_MIN_TEMP)
    max_temp = config.get(CONF_MAX_TEMP)
    target_temp = config.get(CONF_TARGET_TEMP)
    target_temp_step = config.get(CONF_TARGET_TEMP_STEP)
    temp_sensor_entity_id = config.get(CONF_TEMP_SENSOR)
    operation_list = config.get(CONF_CUSTOMIZE).get(CONF_OPERATIONS, []) or DEFAULT_OPERATION_LIST
    fan_list = config.get(CONF_CUSTOMIZE).get(CONF_FAN_MODES, []) or DEFAULT_FAN_MODE_LIST
    swing_updn_mode_list = config.get(CONF_CUSTOMIZE).get(CONF_SWING_UPDN_MODES, []) or DEFAULT_SWING_UPDN_MODES
    default_operation = config.get(CONF_DEFAULT_OPERATION)
    default_fan_mode = config.get(CONF_DEFAULT_FAN_MODE)
    default_swing_updn_mode = config.get(CONF_DEFAULT_SWING_UPDN_MODE)
    encryption_key = config.get(CONF_ENCRYPTION_KEY)
    uid = config.get(CONF_UID)
    
    default_operation_from_idle = config.get(CONF_DEFAULT_OPERATION_FROM_IDLE)
        
    async_add_devices([
        GreeClimate(hass, name, ip_addr, port, mac_addr, min_temp, max_temp, target_temp, target_temp_step, temp_sensor_entity_id, operation_list, fan_list, swing_updn_mode_list, default_operation, default_fan_mode, default_operation_from_idle, default_swing_updn_mode, encryption_key, uid)
    ])

class GreeClimate(ClimateDevice):

    def __init__(self, hass, name, ip_addr, port, mac_addr, min_temp, max_temp, target_temp, target_temp_step, temp_sensor_entity_id, operation_list, fan_list, swing_updn_mode_list, default_operation, default_fan_mode, default_operation_from_idle, default_swing_updn_mode, encryption_key=None, uid=None):
        # Initialize the Broadlink IR Climate device.

        self.hass = hass
        self._name = name
        self._ip_addr = ip_addr
        self._port = port
        self._mac_addr = mac_addr.decode('utf-8').lower()
        
        self._min_temp = min_temp
        self._max_temp = max_temp
        self._target_temperature = target_temp
        self._target_temperature_step = target_temp_step
        self._unit_of_measurement = hass.config.units.temperature_unit
        
        self._current_temperature = None
        self._temp_sensor_entity_id = temp_sensor_entity_id

        self._current_operation = default_operation
        self._current_fan_mode = default_fan_mode
        self._current_swing_mode = default_swing_updn_mode
        self._current_state = STATE_OFF
        
        self._operation_list = operation_list
        self._fan_list = fan_list
        self._swing_updn_mode_list = swing_updn_mode_list

        self._default_operation_from_idle = default_operation_from_idle

        if encryption_key:
            _LOGGER.info('Using configured encryption key: {}'.format(encryption_key))
            self._encryption_key = encryption_key.encode("utf8")
        else:
            _LOGGER.info('Fetching Device Encryption Key')
            self._encryption_key = self.GetDeviceKey().encode("utf8")
            _LOGGER.info('Fetched Device Encryption Key: %s' % self._encryption_key)

        if uid:
            self._uid = uid
        else:
            self._uid = 0
        
        self._acOptions = { 'Pow': None, 'Mod': None, 'SetTem': None, 'WdSpd': None, 'Air': None, 'Blo': None, 'Health': None, 'SwhSlp': None, 'Lig': None, 'SwingLfRig': None, 'SwUpDn': None, 'Quiet': None, 'Tur': None, 'StHt': None, 'TemUn': None, 'HeatCoolType': None, 'TemRec': None, 'SvSt': None }

        self._firstTimeRun = True

        # Cipher to use to encrypt/decrypt
        self.CIPHER = AES.new(self._encryption_key, AES.MODE_ECB)

        if temp_sensor_entity_id:
            async_track_state_change(
                hass, temp_sensor_entity_id, self._async_temp_sensor_changed)
                
            sensor_state = hass.states.get(temp_sensor_entity_id)    
                
            if sensor_state:
                self._async_update_current_temp(sensor_state)

    # Pad helper method to help us get the right string for encrypting
    def Pad(self, s):
        aesBlockSize = 16
        return s + (aesBlockSize - len(s) % aesBlockSize) * chr(aesBlockSize - len(s) % aesBlockSize)            

    def FetchResult(self, cipher, ip_addr, port, json):
        _LOGGER.info('FetchResult(%s, %s, %s)' % (ip_addr, port, json))
        # Setup UDP Client & start transfering
        _LOGGER.info('Creating sock')
        clientSock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        clientSock.settimeout(3)
        _LOGGER.info('Sending over UDP')
        clientSock.sendto(bytes(json, "utf-8"), (ip_addr, port))
        _LOGGER.info('Receiving over UDP')
        data, addr = clientSock.recvfrom(64000)
        _LOGGER.info('Loading received JSON')
        receivedJson = simplejson.loads(data)
        _LOGGER.info('Closing socket')
        clientSock.close()

        pack = receivedJson['pack']
        _LOGGER.info('Base64-decoding received pack')
        base64decodedPack = base64.b64decode(pack)
        _LOGGER.info('Decrypting received pack')
        decryptedPack = cipher.decrypt(base64decodedPack)
        _LOGGER.info('Decoding received pack')
        decodedPack = decryptedPack.decode("utf-8")
        _LOGGER.info('Removing unneeded chars from received pack')
        replacedPack = decodedPack.replace('\x0f', '').replace(decodedPack[decodedPack.rindex('}')+1:], '')
        _LOGGER.info('Loading pack JSON')
        loadedJsonPack = simplejson.loads(replacedPack)
        _LOGGER.info('Returning pack JSON')
        return loadedJsonPack

    def GetDeviceKey(self):
        _LOGGER.info('GetDeviceKey()')
        _LOGGER.info('Creating encryptor with Device Key')
        GENERIC_GREE_DEVICE_KEY = "a3K8Bx%2r8Y7#xDh"
        cipher = AES.new(GENERIC_GREE_DEVICE_KEY.encode("utf8"), AES.MODE_ECB)
        _LOGGER.info('Encrypting Pack')
        pack = base64.b64encode(cipher.encrypt(self.Pad('{"mac":"' + str(self._mac_addr) + '","t":"bind","uid":0}').encode("utf8"))).decode('utf-8')
        _LOGGER.info('Creating JSON')
        jsonPayloadToSend = '{"cid": "app","i": 1,"pack": "' + pack + '","t":"pack","tcid":"' + str(self._mac_addr) + '","uid": 0}'
        _LOGGER.info('Fetching & Returning result')
        return self.FetchResult(cipher, self._ip_addr, self._port, jsonPayloadToSend)['key']

    def GreeGetValues(self, propertyNames):
        jsonPayloadToSend = '{"cid":"app","i":0,"pack":"' + base64.b64encode(self.CIPHER.encrypt(self.Pad('{"cols":' + simplejson.dumps(propertyNames) + ',"mac":"' + str(self._mac_addr) + '","t":"status"}').encode("utf8"))).decode('utf-8') + '","t":"pack","tcid":"' + str(self._mac_addr) + '","uid":{}'.format(self._uid) + '}'
        return self.FetchResult(self.CIPHER, self._ip_addr, self._port, jsonPayloadToSend)['dat']

    def SetAcOptions(self, acOptions, newOptionsToOverride, optionValuesValuesToOverride = None):
        if not (optionValuesValuesToOverride is None):
            _LOGGER.info('Setting script global state with current values')
            for key in newOptionsToOverride:
                _LOGGER.info('Setting %s: %s' % (key, optionValuesValuesToOverride[newOptionsToOverride.index(key)]))
                acOptions[key] = optionValuesValuesToOverride[newOptionsToOverride.index(key)]
            _LOGGER.info('Done setting script global state with current values')
        else:
            _LOGGER.info('Overwriting script global state with given def params')
            for key, value in newOptionsToOverride.items():
                _LOGGER.info('Setting %s: %s' % (key, value))
                acOptions[key] = value
            _LOGGER.info('Done overwriting script global state with given def params')
        return acOptions
        
    def SendStateToAc(self):
        _LOGGER.info('Defining statePackJson')
        #statePackJson = '{' + '"opt":["TemUn","SetTem","TemRec","Pow","SwUpDn","Quiet","Mod","WdSpd"],"p":[{TemUn},{SetTem},{TemRec},{Pow},{SwUpDn},{Quiet},{Mod},{WdSpd}],"t":"cmd"'.format(**self._acOptions) + '}'
        statePackJson = '{' + '"opt":["Pow","Mod","SetTem","WdSpd","Air","Blo","Health","SwhSlp","Lig","SwingLfRig","SwUpDn","Quiet","Tur","StHt","TemUn","HeatCoolType","TemRec","SvSt"],"p":[{Pow},{Mod}, {SetTem},{WdSpd},{Air},{Blo},{Health},{SwhSlp},{Lig},{SwingLfRig},{SwUpDn},{Quiet},{Tur},{StHt},{TemUn},{HeatCoolType},{TemRec},{SvSt}],"t":"cmd"'.format(**self._acOptions) + '}'
        _LOGGER.info('statePackJson: ' + statePackJson)
        _LOGGER.info('str(self._mac_addr): ' + str(self._mac_addr))
        sentJsonPayload = '{"cid":"app","i":0,"pack":"' + base64.b64encode(self.CIPHER.encrypt(self.Pad(statePackJson).encode("utf8"))).decode('utf-8') + '","t":"pack","tcid":"' + str(self._mac_addr) + '","uid":{}'.format(self._uid) + '}'
        _LOGGER.info('sentJsonPayload: ' + sentJsonPayload)

        # Setup UDP Client & start transfering
        _LOGGER.info('Creating socket')
        clientSock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        clientSock.settimeout(3)
        _LOGGER.info('Sending bytes to %s:%s' % (self._ip_addr, self._port))
        clientSock.sendto(bytes(sentJsonPayload, "utf-8"), (self._ip_addr, self._port))
        _LOGGER.info('Receiving response')
        data, addr = clientSock.recvfrom(64000)
        _LOGGER.info('Loading json')
        receivedJson = simplejson.loads(data)
        _LOGGER.info('Closing socket')
        clientSock.close()
        _LOGGER.info('Assigning pack json to var')
        pack = receivedJson['pack']
        _LOGGER.info('Base64 Decode pack')
        base64decodedPack = base64.b64decode(pack)
        _LOGGER.info('AES Decrypt pack')
        decryptedPack = self.CIPHER.decrypt(base64decodedPack)
        _LOGGER.info('Decode pack to UTF-8')
        decodedPack = decryptedPack.decode("utf-8")
        _LOGGER.info('Replacing unneeded characters in string')
        replacedPack = decodedPack.replace('\x0f', '').replace(decodedPack[decodedPack.rindex('}')+1:], '')
        _LOGGER.info('replacedPack: ' + str(replacedPack))
        _LOGGER.info('Loading pack into JSON')
        receivedJsonPayload = simplejson.loads(replacedPack)
        _LOGGER.info('receivedJsonPayload: ' + str(receivedJsonPayload))

    def UpdateHATargetTemperature(self):
        # Sync set temperature to HA
        self._target_temperature = self._acOptions['SetTem']
        _LOGGER.info('Set HA State target temp to ' + str(self._acOptions['SetTem']))

    def UpdateHACurrentOperation(self):
        # Sync current operation mode to HA
        self._current_operation = DEFAULT_OPERATION_LIST[self._acOptions['Mod']]
        _LOGGER.info('Set HA State current operation to ' + str(self._current_operation))

    def UpdateHAOnOffState(self):
        # Sync On/Off state to HA
        if (self._acOptions['Pow'] == 1):
            self._current_state = STATE_ON
        elif (self._acOptions['Pow'] == 0):
            self._current_state = STATE_OFF
        else:
            self._current_state = STATE_UNKNOWN
        _LOGGER.info('self._current_state after: ' + str(self._current_state))
        _LOGGER.info('Set HA State On/Off to ' + str(self._current_state))

    def UpdateHACurrentSwingMode(self):
        # Sync Current Swing mode state to HA
        self._current_swing_mode = DEFAULT_SWING_UPDN_MODES[self._acOptions['SwUpDn']]
        _LOGGER.info('Set HA State current_swing_mode to ' + str(self._current_swing_mode))

    def UpdateHAFanSpeedMode(self):
        # Sync Fan speed state to HA
        if (int(self._acOptions['Tur']) == 1):
            self._current_fan_mode = 'Turbo'
        elif (int(self._acOptions['Quiet']) == 1):
            self._current_fan_mode = 'Quiet'
        else:
            self._current_fan_mode = DEFAULT_FAN_MODE_LIST[int(self._acOptions['WdSpd'])]
        _LOGGER.info('Set HA State current fan mode to ' + str(self._current_fan_mode))

    def UpdateHAStateToCurrentACState(self):
        self.UpdateHATargetTemperature()
        self.UpdateHACurrentOperation()
        self.UpdateHAOnOffState()
        self.UpdateHACurrentSwingMode()
        self.UpdateHAFanSpeedMode()

    def SyncState(self, acOptions = {}):
        #Fetch current settings from AC
        _LOGGER.info('Starting SyncState')

        optionsToFetch = ["Pow","Mod","SetTem","WdSpd","Air","Blo","Health","SwhSlp","Lig","SwingLfRig","SwUpDn","Quiet","Tur","StHt","TemUn","HeatCoolType","TemRec","SvSt"]
        _LOGGER.info('optionsToFetch: ' + str(optionsToFetch))
        currentValues = self.GreeGetValues(optionsToFetch)
        _LOGGER.info('currentValues: ' + str(currentValues))

        # Set latest status from device
        self._acOptions = self.SetAcOptions(self._acOptions, optionsToFetch, currentValues)

        # Overwrite status with our choices
        if not(acOptions == {}):
            self._acOptions = self.SetAcOptions(self._acOptions, acOptions)

        # Initialize the receivedJsonPayload variable (for return)
        receivedJsonPayload = ''

        # If not the first (boot) run, update state towards the AC
        if not (self._firstTimeRun):
            if not(acOptions == {}):
                self.SendStateToAc()
        else:
            self._firstTimeRun = False

        # Update HA state to current AC state
        self.UpdateHAStateToCurrentACState()

        _LOGGER.info('Finished SyncState')
        return receivedJsonPayload

    @asyncio.coroutine
    def _async_temp_sensor_changed(self, entity_id, old_state, new_state):
        _LOGGER.info('_async_temp_sensor_changed() |' + str(entity_id) + '|' + str(old_state) + '|' + str(new_state))
        # Handle temperature changes.
        if new_state is None:
            return
        self._async_update_current_temp(new_state)
        yield from self.async_update_ha_state()
        
    @callback
    def _async_update_current_temp(self, state):
        _LOGGER.info('_async_update_current_temp() |' + str(state))
        # Update thermostat with latest state from sensor.
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)

        try:
            _state = state.state
            _LOGGER.info('Current temp state: ' + _state)
            if self.represents_float(_state):
                self._current_temperature = self.hass.config.units.temperature(
                    float(_state), unit)
                _LOGGER.info('Current temp: ' + str(self._current_temperature))
        except ValueError as ex:
            _LOGGER.error('Unable to update from sensor: %s', ex)    

    def represents_float(self, s):
        _LOGGER.info('represents_float() |' + str(s))
        try: 
            float(s)
            return True
        except ValueError:
            return False     

    
    @property
    def state(self):
        # Return the current state.
        return self._current_state

    @property
    def is_on(self):
        # Return true if on.
        if (self._current_state == STATE_ON):
            return True
        else:
            return False

    @property
    def should_poll(self):
        _LOGGER.info('should_poll()')
        # Return the polling state.
        return True

    def update(self):
        _LOGGER.info('update()')
        # Update HA State from Device
        self.SyncState()
        

    @property
    def name(self):
        _LOGGER.info('name()')
        # Return the name of the climate device.
        return self._name

    @property
    def temperature_unit(self):
        _LOGGER.info('temperature_unit()')
        # Return the unit of measurement.
        return self._unit_of_measurement

    @property
    def current_temperature(self):
        _LOGGER.info('current_temperature(): ' + str(self._current_temperature))
        # Return the current temperature.
        return self._current_temperature
        
    @property
    def min_temp(self):
        _LOGGER.info('min_temp()')
        # Return the polling state.
        return self._min_temp
        
    @property
    def max_temp(self):
        _LOGGER.info('max_temp()')
        # Return the polling state.
        return self._max_temp    
        
    @property
    def target_temperature(self):
        _LOGGER.info('target_temperature(): ' + str(self._target_temperature))
        # Return the temperature we try to reach.
        return self._target_temperature
        
    @property
    def target_temperature_step(self):
        _LOGGER.info('target_temperature_step()')
        # Return the supported step of target temperature.
        return self._target_temperature_step

    @property
    def current_operation(self):
        _LOGGER.info('current_operation(): ' + str(self._current_operation))
        # Return current operation ie. heat, cool, idle.
        return self._current_operation

    @property
    def current_swing_mode(self):
        _LOGGER.info('current_swing_mode(): ' + str(self._current_swing_mode))
        # get the current swing mode
        return self._current_swing_mode

    @property
    def swing_list(self):
        # get the list of available swing lists
        return self._swing_updn_mode_list

    @property
    def operation_list(self):
        _LOGGER.info('operation_list()')
        # Return the list of available operation modes.
        return self._operation_list

    @property
    def current_fan_mode(self):
        _LOGGER.info('current_fan_mode()')
        # Return the fan setting.
        return self._current_fan_mode

    @property
    def fan_list(self):
        _LOGGER.info('fan_list()')
        # Return the list of available fan modes.
        return self._fan_list
        
    @property
    def supported_features(self):
        _LOGGER.info('supported_features()')
        # Return the list of supported features.
        return SUPPORT_FLAGS        
 
    def set_temperature(self, **kwargs):
        _LOGGER.info('set_temperature()')
        # Set new target temperatures.
        _LOGGER.info('kwargs.get(ATTR_TEMPERATURE): ' + str(kwargs.get(ATTR_TEMPERATURE)))
        if kwargs.get(ATTR_TEMPERATURE) is not None:
            if not (self._acOptions['Pow'] == 0):
                _LOGGER.info('SyncState with SetTem=' + str(kwargs.get(ATTR_TEMPERATURE)))
                self.SyncState({ 'SetTem': int(kwargs.get(ATTR_TEMPERATURE))})
                self.schedule_update_ha_state()

    def set_swing_mode(self, swing_mode):
        _LOGGER.info('Set swing mode: ' + swing_mode)
        # set the swing mode
        if not (self._acOptions['Pow'] == 0):
            _LOGGER.info('SyncState with SwUpDn=' + str(swing_mode))
            self.SyncState({'SwUpDn': self._swing_updn_mode_list.index(swing_mode)})
            self.schedule_update_ha_state()

    def set_fan_mode(self, fan):
        _LOGGER.info('set_fan_mode() |' + str(fan))
        # Set new target temperature.

        if not (self._acOptions['Pow'] == 0):

            if (fan.lower() == 'turbo'):
                _LOGGER.info('Enabling turbo mode')
                self.SyncState({'Tur': 1, 'Quiet': 0})
            elif (fan.lower() == 'quiet'):
                _LOGGER.info('Enabling quiet mode')
                self.SyncState({'Tur': 0, 'Quiet': 1})
            else:
                _LOGGER.info('Setting normal fan mode to ' + str(self._fan_list.index(fan)))
                self.SyncState({'WdSpd': str(self._fan_list.index(fan)), 'Tur': 0, 'Quiet': 0})
            self.schedule_update_ha_state()

    def turn_on(self):
        # Turn device on.
        self.SyncState({'Pow': 1})
        self.schedule_update_ha_state()

    def turn_off(self):
        # Turn device off.
        self.SyncState({'Pow': 0})
        self.schedule_update_ha_state()

    def set_operation_mode(self, operation_mode):
        _LOGGER.info('set_operation_mode() |' + str(operation_mode))
        # Set new target temperature.
        self.SyncState({'Mod': self._operation_list.index(operation_mode)})
        self.schedule_update_ha_state()
        
    @asyncio.coroutine
    def async_added_to_hass(self):
        _LOGGER.info('async_added_to_hass()')
        self.SyncState()
