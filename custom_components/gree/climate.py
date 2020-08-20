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

from homeassistant.components.climate import (ClimateEntity, PLATFORM_SCHEMA)

from homeassistant.components.climate.const import (
    HVAC_MODE_OFF, HVAC_MODE_AUTO, HVAC_MODE_COOL, HVAC_MODE_DRY,
    HVAC_MODE_FAN_ONLY, HVAC_MODE_HEAT, SUPPORT_FAN_MODE,
    SUPPORT_TARGET_TEMPERATURE, SUPPORT_SWING_MODE)

from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT, ATTR_TEMPERATURE, 
    CONF_NAME, CONF_HOST, CONF_PORT, CONF_MAC, CONF_TIMEOUT, CONF_CUSTOMIZE, 
    STATE_ON, STATE_OFF, STATE_UNKNOWN, 
    TEMP_CELSIUS, PRECISION_WHOLE, PRECISION_TENTHS)

from homeassistant.components.fan import SPEED_HIGH, SPEED_LOW, SPEED_MEDIUM

from homeassistant.helpers.event import (async_track_state_change)
from homeassistant.core import callback
from homeassistant.helpers.restore_state import RestoreEntity
from configparser import ConfigParser
from Crypto.Cipher import AES
try: import simplejson
except ImportError: import json as simplejson

REQUIREMENTS = ['pycryptodome']

_LOGGER = logging.getLogger(__name__)

SUPPORT_FLAGS = SUPPORT_TARGET_TEMPERATURE | SUPPORT_FAN_MODE | SUPPORT_SWING_MODE

DEFAULT_NAME = 'Gree Climate'

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

DEFAULT_PORT = 7000
DEFAULT_TIMEOUT = 10
DEFAULT_TARGET_TEMP_STEP = 1

# from the remote control and gree app
MIN_TEMP = 16
MAX_TEMP = 30

# fixed values in gree mode lists
HVAC_MODES = [HVAC_MODE_AUTO, HVAC_MODE_COOL, HVAC_MODE_DRY, HVAC_MODE_FAN_ONLY, HVAC_MODE_HEAT, HVAC_MODE_OFF]

FAN_MODES = ['Auto', SPEED_LOW, 'Medium-Low', SPEED_MEDIUM, 'Medium-High', SPEED_HIGH, 'Turbo', 'Quiet']
SWING_MODES = ['Default', 'Swing in full range', 'Fixed in the upmost position', 'Fixed in the middle-up position', 'Fixed in the middle position', 'Fixed in the middle-low position', 'Fixed in the lowest position', 'Swing in the downmost region', 'Swing in the middle-low region', 'Swing in the middle region', 'Swing in the middle-up region', 'Swing in the upmost region']

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
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
    vol.Optional(CONF_UID): cv.positive_int
})

@asyncio.coroutine
def async_setup_platform(hass, config, async_add_devices, discovery_info=None):
    _LOGGER.info('Setting up Gree climate platform')
    name = config.get(CONF_NAME)
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
    hvac_modes = HVAC_MODES
    fan_modes = FAN_MODES
    swing_modes = SWING_MODES
    encryption_key = config.get(CONF_ENCRYPTION_KEY)
    uid = config.get(CONF_UID)
    
    _LOGGER.info('Adding Gree climate device to hass')
    async_add_devices([
        GreeClimate(hass, name, ip_addr, port, mac_addr, timeout, target_temp_step, temp_sensor_entity_id, lights_entity_id, xfan_entity_id, health_entity_id, powersave_entity_id, sleep_entity_id, eightdegheat_entity_id, air_entity_id, hvac_modes, fan_modes, swing_modes, encryption_key, uid)
    ])

class GreeClimate(ClimateEntity):

    def __init__(self, hass, name, ip_addr, port, mac_addr, timeout, target_temp_step, temp_sensor_entity_id, lights_entity_id, xfan_entity_id, health_entity_id, powersave_entity_id, sleep_entity_id, eightdegheat_entity_id, air_entity_id, hvac_modes, fan_modes, swing_modes, encryption_key=None, uid=None):
        _LOGGER.info('Initialize the GREE climate device')
        self.hass = hass
        self._name = name
        self._ip_addr = ip_addr
        self._port = port
        self._mac_addr = mac_addr.decode('utf-8').lower()
        self._timeout = timeout

        self._target_temperature = None
        self._target_temperature_step = target_temp_step
        self._unit_of_measurement = hass.config.units.temperature_unit
        
        self._current_temperature = None
        self._temp_sensor_entity_id = temp_sensor_entity_id
        self._lights_entity_id = lights_entity_id
        self._xfan_entity_id = xfan_entity_id
        self._health_entity_id = health_entity_id
        self._powersave_entity_id = powersave_entity_id
        self._sleep_entity_id = sleep_entity_id
        self._eightdegheat_entity_id = eightdegheat_entity_id
        self._air_entity_id = air_entity_id

        self._hvac_mode = None
        self._fan_mode = None
        self._swing_mode = None
        self._current_lights = None
        self._current_xfan = None
        self._current_health = None
        self._current_powersave = None
        self._current_sleep = None
        self._current_eightdegheat = None
        self._current_air = None

        self._hvac_modes = hvac_modes
        self._fan_modes = fan_modes
        self._swing_modes = swing_modes

        if encryption_key:
            _LOGGER.info('Using configured encryption key: {}'.format(encryption_key))
            self._encryption_key = encryption_key.encode("utf8")
        else:
            self._encryption_key = self.GetDeviceKey().encode("utf8")
            _LOGGER.info('Fetched device encrytion key: %s' % str(self._encryption_key))

        if uid:
            self._uid = uid
        else:
            self._uid = 0
        
        self._acOptions = { 'Pow': None, 'Mod': None, 'SetTem': None, 'WdSpd': None, 'Air': None, 'Blo': None, 'Health': None, 'SwhSlp': None, 'Lig': None, 'SwingLfRig': None, 'SwUpDn': None, 'Quiet': None, 'Tur': None, 'StHt': None, 'TemUn': None, 'HeatCoolType': None, 'TemRec': None, 'SvSt': None, 'SlpMod': None }

        self._firstTimeRun = True

        # Cipher to use to encrypt/decrypt
        self.CIPHER = AES.new(self._encryption_key, AES.MODE_ECB)

        if temp_sensor_entity_id:
            _LOGGER.info('Setting up temperature sensor: ' + str(temp_sensor_entity_id))
            async_track_state_change(
                hass, temp_sensor_entity_id, self._async_temp_sensor_changed)
                
        if lights_entity_id:
            _LOGGER.info('Setting up lights entity: ' + str(lights_entity_id))
            async_track_state_change(
                hass, lights_entity_id, self._async_lights_entity_state_changed)

        if xfan_entity_id:
            _LOGGER.info('Setting up xfan entity: ' + str(xfan_entity_id))
            async_track_state_change(
                hass, xfan_entity_id, self._async_xfan_entity_state_changed)

        if health_entity_id:
            _LOGGER.info('Setting up health entity: ' + str(health_entity_id))
            async_track_state_change(
                hass, health_entity_id, self._async_health_entity_state_changed)

        if powersave_entity_id:
            _LOGGER.info('Setting up powersave entity: ' + str(powersave_entity_id))
            async_track_state_change(
                hass, powersave_entity_id, self._async_powersave_entity_state_changed)

        if sleep_entity_id:
            _LOGGER.info('Setting up sleep entity: ' + str(sleep_entity_id))
            async_track_state_change(
                hass, sleep_entity_id, self._async_sleep_entity_state_changed)

        if eightdegheat_entity_id:
            _LOGGER.info('Setting up 8℃ heat entity: ' + str(eightdegheat_entity_id))
            async_track_state_change(
                hass, eightdegheat_entity_id, self._async_eightdegheat_entity_state_changed)

        if air_entity_id:
            _LOGGER.info('Setting up air entity: ' + str(air_entity_id))
            async_track_state_change(
                hass, air_entity_id, self._async_air_entity_state_changed)

    # Pad helper method to help us get the right string for encrypting
    def Pad(self, s):
        aesBlockSize = 16
        return s + (aesBlockSize - len(s) % aesBlockSize) * chr(aesBlockSize - len(s) % aesBlockSize)            

    def FetchResult(self, cipher, ip_addr, port, timeout, json):
        _LOGGER.info('Fetching(%s, %s, %s, %s)' % (ip_addr, port, timeout, json))
        clientSock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        clientSock.settimeout(timeout)
        clientSock.sendto(bytes(json, "utf-8"), (ip_addr, port))
        data, addr = clientSock.recvfrom(64000)
        receivedJson = simplejson.loads(data)
        clientSock.close()
        pack = receivedJson['pack']
        base64decodedPack = base64.b64decode(pack)
        decryptedPack = cipher.decrypt(base64decodedPack)
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
        return self.FetchResult(cipher, self._ip_addr, self._port, self._timeout, jsonPayloadToSend)['key']

    def GreeGetValues(self, propertyNames):
        jsonPayloadToSend = '{"cid":"app","i":0,"pack":"' + base64.b64encode(self.CIPHER.encrypt(self.Pad('{"cols":' + simplejson.dumps(propertyNames) + ',"mac":"' + str(self._mac_addr) + '","t":"status"}').encode("utf8"))).decode('utf-8') + '","t":"pack","tcid":"' + str(self._mac_addr) + '","uid":{}'.format(self._uid) + '}'
        return self.FetchResult(self.CIPHER, self._ip_addr, self._port, self._timeout, jsonPayloadToSend)['dat']

    def SetAcOptions(self, acOptions, newOptionsToOverride, optionValuesToOverride = None):
        if not (optionValuesToOverride is None):
            _LOGGER.info('Setting acOptions with retrieved HVAC values')
            for key in newOptionsToOverride:
                _LOGGER.info('Setting %s: %s' % (key, optionValuesToOverride[newOptionsToOverride.index(key)]))
                acOptions[key] = optionValuesToOverride[newOptionsToOverride.index(key)]
            _LOGGER.info('Done setting acOptions')
        else:
            _LOGGER.info('Overwriting acOptions with new settings')
            for key, value in newOptionsToOverride.items():
                _LOGGER.info('Overwriting %s: %s' % (key, value))
                acOptions[key] = value
            _LOGGER.info('Done overwriting acOptions')
        return acOptions
        
    def SendStateToAc(self, timeout):
        _LOGGER.info('Start sending state to HVAC')
        statePackJson = '{' + '"opt":["Pow","Mod","SetTem","WdSpd","Air","Blo","Health","SwhSlp","Lig","SwingLfRig","SwUpDn","Quiet","Tur","StHt","TemUn","HeatCoolType","TemRec","SvSt","SlpMod"],"p":[{Pow},{Mod},{SetTem},{WdSpd},{Air},{Blo},{Health},{SwhSlp},{Lig},{SwingLfRig},{SwUpDn},{Quiet},{Tur},{StHt},{TemUn},{HeatCoolType},{TemRec},{SvSt},{SlpMod}],"t":"cmd"'.format(**self._acOptions) + '}'
        sentJsonPayload = '{"cid":"app","i":0,"pack":"' + base64.b64encode(self.CIPHER.encrypt(self.Pad(statePackJson).encode("utf8"))).decode('utf-8') + '","t":"pack","tcid":"' + str(self._mac_addr) + '","uid":{}'.format(self._uid) + '}'
        # Setup UDP Client & start transfering
        clientSock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        clientSock.settimeout(timeout)
        clientSock.sendto(bytes(sentJsonPayload, "utf-8"), (self._ip_addr, self._port))
        data, addr = clientSock.recvfrom(64000)
        receivedJson = simplejson.loads(data)
        clientSock.close()
        pack = receivedJson['pack']
        base64decodedPack = base64.b64decode(pack)
        decryptedPack = self.CIPHER.decrypt(base64decodedPack)
        decodedPack = decryptedPack.decode("utf-8")
        replacedPack = decodedPack.replace('\x0f', '').replace(decodedPack[decodedPack.rindex('}')+1:], '')
        receivedJsonPayload = simplejson.loads(replacedPack)
        _LOGGER.info('Done sending state to HVAC: ' + str(receivedJsonPayload))

    def UpdateHATargetTemperature(self):
        # Sync set temperature to HA. If 8℃ heating is active we set the temp in HA to 8℃ so that it shows the same as the AC display.
        if (int(self._acOptions['StHt']) == 1):
            self._target_temperature = 8
            _LOGGER.info('HA target temp set according to HVAC state to 8℃ since 8℃ heating mode is active')
        else:
            self._target_temperature = self._acOptions['SetTem']
            _LOGGER.info('HA target temp set according to HVAC state to: ' + str(self._acOptions['SetTem']))

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
        _LOGGER.info('HA lights option set according to HVAC state to: ' + str(self._current_lights))
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
        _LOGGER.info('HA xfan option set according to HVAC state to: ' + str(self._current_xfan))
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
        _LOGGER.info('HA health option set according to HVAC state to: ' + str(self._current_health))
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
        _LOGGER.info('HA powersave option set according to HVAC state to: ' + str(self._current_powersave))
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
        _LOGGER.info('HA sleep option set according to HVAC state to: ' + str(self._current_sleep))
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
        _LOGGER.info('HA 8℃ heat option set according to HVAC state to: ' + str(self._current_eightdegheat))
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
        _LOGGER.info('HA air option set according to HVAC state to: ' + str(self._current_air))

    def UpdateHAHvacMode(self):
        # Sync current HVAC operation mode to HA
        if (self._acOptions['Pow'] == 0):
            self._hvac_mode = HVAC_MODE_OFF
        else:
            self._hvac_mode = self._hvac_modes[self._acOptions['Mod']]
        _LOGGER.info('HA operation mode set according to HVAC state to: ' + str(self._hvac_mode))

    def UpdateHACurrentSwingMode(self):
        # Sync current HVAC Swing mode state to HA
        self._swing_mode = self._swing_modes[self._acOptions['SwUpDn']]
        _LOGGER.info('HA swing mode set according to HVAC state to: ' + str(self._swing_mode))

    def UpdateHAFanMode(self):
        # Sync current HVAC Fan mode state to HA
        if (int(self._acOptions['Tur']) == 1):
            self._fan_mode = 'Turbo'
        elif (int(self._acOptions['Quiet']) >= 1):
            self._fan_mode = 'Quiet'
        else:
            self._fan_mode = self._fan_modes[int(self._acOptions['WdSpd'])]
        _LOGGER.info('HA fan mode set according to HVAC state to: ' + str(self._fan_mode))

    def UpdateHAStateToCurrentACState(self):
        self.UpdateHATargetTemperature()
        self.UpdateHAOptions()
        self.UpdateHAHvacMode()
        self.UpdateHACurrentSwingMode()
        self.UpdateHAFanMode()

    def SyncState(self, acOptions = {}):
        #Fetch current settings from HVAC
        _LOGGER.info('Starting SyncState')

        optionsToFetch = ["Pow","Mod","SetTem","WdSpd","Air","Blo","Health","SwhSlp","Lig","SwingLfRig","SwUpDn","Quiet","Tur","StHt","TemUn","HeatCoolType","TemRec","SvSt","SlpMod"]
        currentValues = self.GreeGetValues(optionsToFetch)

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

        _LOGGER.info('Finished SyncState')
        return receivedJsonPayload

    @asyncio.coroutine
    def _async_temp_sensor_changed(self, entity_id, old_state, new_state):
        _LOGGER.info('temp_sensor state changed |' + str(entity_id) + '|' + str(old_state) + '|' + str(new_state))
        # Handle temperature changes.
        if new_state is None:
            return
        self._async_update_current_temp(new_state)
        yield from self.async_update_ha_state()
        
    @callback
    def _async_update_current_temp(self, state):
        _LOGGER.info('Thermostat updated with changed temp_sensor state |' + str(state))
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
        try:
            _state = state.state
            _LOGGER.info('Current state temp_sensor: ' + _state)
            if self.represents_float(_state):
                self._current_temperature = self.hass.config.units.temperature(
                    float(_state), unit)
                _LOGGER.info('Current temp: ' + str(self._current_temperature))
        except ValueError as ex:
            _LOGGER.error('Unable to update from temp_sensor: %s' % ex)

    def represents_float(self, s):
        _LOGGER.info('temp_sensor state represents_float |' + str(s))
        try: 
            float(s)
            return True
        except ValueError:
            return False     

    @asyncio.coroutine
    def _async_lights_entity_state_changed(self, entity_id, old_state, new_state):
        _LOGGER.info('lights_entity state changed |' + str(entity_id) + '|' + str(old_state) + '|' + str(new_state))
        if new_state is None:
            return
        if new_state.state is self._current_lights:
            # do nothing if state change is triggered due to Sync with HVAC
            return
        self._async_update_current_lights(new_state)
        yield from self.async_update_ha_state()

    @callback
    def _async_update_current_lights(self, state):
        _LOGGER.info('Updating HVAC with changed lights_entity state |' + str(state))
        if state.state is STATE_ON:
            self.SyncState({'Lig': 1})
            return
        elif state.state is STATE_OFF:
            self.SyncState({'Lig': 0})
            return
        _LOGGER.error('Unable to update from lights_entity!')

    @asyncio.coroutine
    def _async_xfan_entity_state_changed(self, entity_id, old_state, new_state):
        _LOGGER.info('xfan_entity state changed |' + str(entity_id) + '|' + str(old_state) + '|' + str(new_state))
        if new_state is None:
            return
        if new_state.state is self._current_xfan:
            # do nothing if state change is triggered due to Sync with HVAC
            return
        if not self._hvac_mode in (HVAC_MODE_COOL, HVAC_MODE_DRY):
            # do nothing if not in cool or dry mode
            _LOGGER.info('Cant set xfan in %s mode' % str(self._hvac_mode))
            return
        self._async_update_current_xfan(new_state)
        yield from self.async_update_ha_state()

    @callback
    def _async_update_current_xfan(self, state):
        _LOGGER.info('Updating HVAC with changed xfan_entity state |' + str(state))
        if state.state is STATE_ON:
            self.SyncState({'Blo': 1})
            return
        elif state.state is STATE_OFF:
            self.SyncState({'Blo': 0})
            return
        _LOGGER.error('Unable to update from xfan_entity!')

    @asyncio.coroutine
    def _async_health_entity_state_changed(self, entity_id, old_state, new_state):
        _LOGGER.info('health_entity state changed |' + str(entity_id) + '|' + str(old_state) + '|' + str(new_state))
        if new_state is None:
            return
        if new_state.state is self._current_health:
            # do nothing if state change is triggered due to Sync with HVAC
            return
        self._async_update_current_health(new_state)
        yield from self.async_update_ha_state()

    @callback
    def _async_update_current_health(self, state):
        _LOGGER.info('Updating HVAC with changed health_entity state |' + str(state))
        if state.state is STATE_ON:
            self.SyncState({'Health': 1})
            return
        elif state.state is STATE_OFF:
            self.SyncState({'Health': 0})
            return
        _LOGGER.error('Unable to update from health_entity!')

    @asyncio.coroutine
    def _async_powersave_entity_state_changed(self, entity_id, old_state, new_state):
        _LOGGER.info('powersave_entity state changed |' + str(entity_id) + '|' + str(old_state) + '|' + str(new_state))
        if new_state is None:
            return
        if new_state.state is self._current_powersave:
            # do nothing if state change is triggered due to Sync with HVAC
            return
        if not self._hvac_mode in (HVAC_MODE_COOL):
            # do nothing if not in cool mode
            _LOGGER.info('Cant set powersave in %s mode' % str(self._hvac_mode))
            return
        self._async_update_current_powersave(new_state)
        yield from self.async_update_ha_state()

    @callback
    def _async_update_current_powersave(self, state):
        _LOGGER.info('Udating HVAC with changed powersave_entity state |' + str(state))
        if state.state is STATE_ON:
            self.SyncState({'SvSt': 1})
            return
        elif state.state is STATE_OFF:
            self.SyncState({'SvSt': 0})
            return
        _LOGGER.error('Unable to update from powersave_entity!')


    @asyncio.coroutine
    def _async_sleep_entity_state_changed(self, entity_id, old_state, new_state):
        _LOGGER.info('sleep_entity state changed |' + str(entity_id) + '|' + str(old_state) + '|' + str(new_state))
        if new_state is None:
            return
        if new_state.state is self._current_sleep:
            # do nothing if state change is triggered due to Sync with HVAC
            return
        if not self._hvac_mode in (HVAC_MODE_COOL, HVAC_MODE_HEAT):
            # do nothing if not in cool or heat mode
            _LOGGER.info('Cant set sleep in %s mode' % str(self._hvac_mode))
            return
        self._async_update_current_sleep(new_state)
        yield from self.async_update_ha_state()

    @callback
    def _async_update_current_sleep(self, state):
        _LOGGER.info('Updating HVAC with changed sleep_entity state |' + str(state))
        if state.state is STATE_ON:
            self.SyncState({'SwhSlp': 1, 'SlpMod': 1})
            return
        elif state.state is STATE_OFF:
            self.SyncState({'SwhSlp': 0, 'SlpMod': 0})
            return
        _LOGGER.error('Unable to update from sleep_entity!')

    @asyncio.coroutine
    def _async_eightdegheat_entity_state_changed(self, entity_id, old_state, new_state):
        _LOGGER.info('eightdegheat_entity state changed |' + str(entity_id) + '|' + str(old_state) + '|' + str(new_state))
        if new_state is None:
            return
        if new_state.state is self._current_eightdegheat:
            # do nothing if state change is triggered due to Sync with HVAC
            return
        if not self._hvac_mode in (HVAC_MODE_HEAT):
            # do nothing if not in heat mode
            _LOGGER.info('Cant set 8℃ heat in %s mode' % str(self._hvac_mode))
            return
        self._async_update_current_eightdegheat(new_state)
        yield from self.async_update_ha_state()

    @callback
    def _async_update_current_eightdegheat(self, state):
        _LOGGER.info('Updating HVAC with changed eightdegheat_entity state |' + str(state))
        if state.state is STATE_ON:
            self.SyncState({'StHt': 1})
            return
        elif state.state is STATE_OFF:
            self.SyncState({'StHt': 0})
            return
        _LOGGER.error('Unable to update from eightdegheat_entity!')

    @asyncio.coroutine
    def _async_air_entity_state_changed(self, entity_id, old_state, new_state):
        _LOGGER.info('air_entity state changed |' + str(entity_id) + '|' + str(old_state) + '|' + str(new_state))
        if new_state is None:
            return
        if new_state.state is self._current_air:
            # do nothing if state change is triggered due to Sync with HVAC
            return
        self._async_update_current_air(new_state)
        yield from self.async_update_ha_state()

    @callback
    def _async_update_current_air(self, state):
        _LOGGER.info('Updating HVAC with changed air_entity state |' + str(state))
        if state.state is STATE_ON:
            self.SyncState({'Air': 1})
            return
        elif state.state is STATE_OFF:
            self.SyncState({'Air': 0})
            return
        _LOGGER.error('Unable to update from air_entity!')



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
        _LOGGER.info('name(): ' + str(self._name))
        # Return the name of the climate device.
        return self._name

    @property
    def temperature_unit(self):
        _LOGGER.info('temperature_unit(): ' + str(self._unit_of_measurement))
        # Return the unit of measurement.
        return self._unit_of_measurement

    @property
    def current_temperature(self):
        _LOGGER.info('current_temperature(): ' + str(self._current_temperature))
        # Return the current temperature.
        return self._current_temperature

    @property
    def min_temp(self):
        _LOGGER.info('min_temp(): ' + str(MIN_TEMP))
        # Return the minimum temperature.
        return MIN_TEMP
        
    @property
    def max_temp(self):
        _LOGGER.info('max_temp(): ' + str(MAX_TEMP))
        # Return the maximum temperature.
        return MAX_TEMP
        
    @property
    def target_temperature(self):
        _LOGGER.info('target_temperature(): ' + str(self._target_temperature))
        # Return the temperature we try to reach.
        return self._target_temperature
        
    @property
    def target_temperature_step(self):
        _LOGGER.info('target_temperature_step(): ' + str(self._target_temperature_step))
        # Return the supported step of target temperature.
        return self._target_temperature_step

    @property
    def hvac_mode(self):
        _LOGGER.info('hvac_mode(): ' + str(self._hvac_mode))
        # Return current operation mode ie. heat, cool, idle.
        return self._hvac_mode

    @property
    def swing_mode(self):
        _LOGGER.info('swing_mode(): ' + str(self._swing_mode))
        # get the current swing mode
        return self._swing_mode

    @property
    def swing_modes(self):
        _LOGGER.info('swing_modes(): ' + str(self._swing_modes))
        # get the list of available swing modes
        return self._swing_modes

    @property
    def hvac_modes(self):
        _LOGGER.info('hvac_modes(): ' + str(self._hvac_modes))
        # Return the list of available operation modes.
        return self._hvac_modes

    @property
    def fan_mode(self):
        _LOGGER.info('fan_mode(): ' + str(self._fan_mode))
        # Return the fan mode.
        return self._fan_mode

    @property
    def fan_modes(self):
        _LOGGER.info('fan_list(): ' + str(self._fan_modes))
        # Return the list of available fan modes.
        return self._fan_modes
        
    @property
    def supported_features(self):
        _LOGGER.info('supported_features(): ' + str(SUPPORT_FLAGS))
        # Return the list of supported features.
        return SUPPORT_FLAGS        
 
    def set_temperature(self, **kwargs):
        _LOGGER.info('set_temperature(): ' + str(kwargs.get(ATTR_TEMPERATURE)))
        # Set new target temperatures.
        if kwargs.get(ATTR_TEMPERATURE) is not None:
            # do nothing if temperature is none
            if not (self._acOptions['Pow'] == 0):
                # do nothing if HVAC is switched off
                _LOGGER.info('SyncState with SetTem=' + str(kwargs.get(ATTR_TEMPERATURE)))
                self.SyncState({ 'SetTem': int(kwargs.get(ATTR_TEMPERATURE))})
                self.schedule_update_ha_state()

    def set_swing_mode(self, swing_mode):
        _LOGGER.info('Set swing mode(): ' + str(swing_mode))
        # set the swing mode
        if not (self._acOptions['Pow'] == 0):
            # do nothing if HVAC is switched off
            _LOGGER.info('SyncState with SwUpDn=' + str(swing_mode))
            self.SyncState({'SwUpDn': self._swing_modes.index(swing_mode)})
            self.schedule_update_ha_state()

    def set_fan_mode(self, fan):
        _LOGGER.info('set_fan_mode(): ' + str(fan))
        # Set the fan mode.
        if not (self._acOptions['Pow'] == 0):
            if (fan.lower() == 'turbo'):
                _LOGGER.info('Enabling turbo mode')
                self.SyncState({'Tur': 1, 'Quiet': 0})
            elif (fan.lower() == 'quiet'):
                _LOGGER.info('Enabling quiet mode')
                self.SyncState({'Tur': 0, 'Quiet': 1})
            else:
                _LOGGER.info('Setting normal fan mode to ' + str(self._fan_modes.index(fan)))
                self.SyncState({'WdSpd': str(self._fan_modes.index(fan)), 'Tur': 0, 'Quiet': 0})
            self.schedule_update_ha_state()

    def set_hvac_mode(self, hvac_mode):
        _LOGGER.info('set_hvac_mode(): ' + str(hvac_mode))
        # Set new operation mode.
        if (hvac_mode == HVAC_MODE_OFF):
            self.SyncState({'Pow': 0})
        else:
            self.SyncState({'Mod': self._hvac_modes.index(hvac_mode), 'Pow': 1})
        self.schedule_update_ha_state()

    @asyncio.coroutine
    def async_added_to_hass(self):
        _LOGGER.info('Gree climate device added to hass()')
        self.SyncState()
