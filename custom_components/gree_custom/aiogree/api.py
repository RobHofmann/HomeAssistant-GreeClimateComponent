"""Contains the API to interface with the Gree device."""

from dataclasses import dataclass
from enum import IntEnum, StrEnum, unique
import json
import logging
import re
from typing import Any

from .cipher import CipherBase, EncryptionVersion, get_cipher
from .const import DEFAULT_DEVICE_PORT
from .errors import GreeBindingError, GreeConnectionError, GreeError, GreeProtocolError
from .transport import GreeTransport, async_udp_broadcast_request

_LOGGER = logging.getLogger(__name__)


class GreeProp(StrEnum):
    """Enumeration of Gree device properties."""

    # HVAC CONTROLS
    # power state of the device
    POWER = "Pow"
    # mode of operation
    OP_MODE = "Mod"

    # fan speed mode
    FAN_SPEED = "WdSpd"
    # the swing mode of the horizontal air blades (available on limited number of devices)
    SWING_HORIZONTAL = "SwingLfRig"
    # the swing mode of the vertical air blades
    SWING_VERTICAL = "SwUpDn"

    # target temperature
    TARGET_TEMPERATURE = "SetTem"
    # used to distinguish between Fahrenheit values
    TARGET_TEMPERATURE_BIT = "TemRec"
    # defines the unit of temperature for the target temperature
    TARGET_TEMPERATURE_UNIT = "TemUn"

    # Quiet mode which slows down the fan to its most quiet speed. Not available in Dry and Fan mode.
    FEAT_QUIET_MODE = "Quiet"
    # Turbo mode sets fan speed to the maximum. Fan speed cannot be changed while active and only available in Dry and Cool mode
    FEAT_TURBO_MODE = "Tur"
    # OPTIONAL FEATURES/MODES
    # controls the state of the fresh air valve (not available on all units)
    FEAT_FRESH_AIR = "Air"
    # "Blow" or "X-Fan", this function keeps the fan running for a while after shutting down. Only usable in Dry and Cool mode
    FEAT_XFAN = "Blo"
    # controls Health ("Cold plasma") mode, only for devices equipped with "anion generator", which absorbs dust and kills bacteria
    FEAT_HEALTH = "Health"
    # sleep mode enabled, which gradually changes the temperature in Cool and Heat modes
    FEAT_SLEEP_MODE = "SlpMod"
    # sleep mode setting, controls different sleep modes
    FEAT_SLEEP_MODE_TYPE = "SwhSlp"
    # turns all indicators and the display on the unit on or off
    FEAT_LIGHT = "Lig"
    # Anti Freeze maintain the room temperature steadily at 8°C and prevent the room from freezing by heating operation when nobody is at home for long in severe winter
    FEAT_SMART_HEAT_8C = "StHt"
    # energy saving mode
    FEAT_ENERGY_SAVING = "SvSt"
    # prevents the wind from blowing directly on people
    FEAT_ANTI_DIRECT_BLOW = "AntiDirectBlow"
    # use light sensor for unit display
    FEAT_SENSOR_LIGHT = "LigSen"

    # SENSORS
    # indoor temperature sensor, used to read the current room temperature, if available
    SENSOR_TEMPERATURE = "TemSen"
    # outside temperature sensor, used to read the current outdooors temperature, if available
    SENSOR_OUTSIDE_TEMPERATURE = "OutEnvTem"
    # indoor humidity sensor, used to read the current room humidity, if available
    SENSOR_HUMIDITY = "DwatSen"
    # error display. 0 if no error, otherwise error
    SENSOR_FAULT = "FaultDisplay"

    # OTHER
    _UNKNOWN_HEAT_COOL_TYPE = "HeatCoolType"

    # If set to 0 the unit will beep on every command
    BEEPER = "Buzzer_ON_OFF"
    # If set to 1 the unit will beep on every command (available on newer firmwares)
    BEEPER_NEW = "BuzzerCtrl"


PROP_KEY_TO_ENUM = {prop.value: prop for prop in GreeProp}


class OtherProps(StrEnum):
    """Enumeration of other Gree device properties."""

    _UNKN_MODEL = "ModelType"
    _UNKN_ACStupPos = "ACStupPos"
    _UNKN_ActiveTime = "ActiveTime"
    _UNKN_Add0_1 = "Add0.1"
    _UNKN_Add0_5 = "Add0.5"
    _UNKN_AirQ = "AirQ"
    _UNKN_AllErr = "AllErr"
    _UNKN_Antifreeze = "Antifreeze"
    _UNKN_AssHt = "AssHt"
    _UNKN_AutoClean = "AutoClean"
    _UNKN_AutoComnCloud = "AutoComnCloud"
    _UNKN_AutoUpdate = "AutoUpdate"
    _UNKN_BlkTemCom = "BlkTemCom"
    _UNKN_ChildLock = "ChildLock"
    _UNKN_CO2 = "CO2"
    _UNKN_CO2Level = "CO2Level"
    _UNKN_CommErr = "CommErr"
    _UNKN_CompressorFqy = "CompressorFqy"
    _UNKN_CompressorTem = "CompressorTem"
    _UNKN_Coolmod = "Coolmod"
    _UNKN_CoolNoise = "CoolNoise"
    _UNKN_CoolSvStTemMin = "CoolSvStTemMin"
    _UNKN_CpsTem = "CpsTem"
    _UNKN_CurTmHor = "CurTmHor"
    _UNKN_CurTmMin = "CurTmMin"
    _UNKN_Dazzling = "Dazzling"
    _UNKN_Defrost = "Defrost"
    _UNKN_Dfltr = "Dfltr"
    _UNKN_DFPoint = "DFPoint"
    _UNKN_DIYGra1PoiAmo = "DIYGra1PoiAmo"
    _UNKN_Dmod = "Dmod"
    _UNKN_DnPLLRSwing = "DnPLLRSwing"
    _UNKN_DnPRLRSwing = "DnPRLRSwing"
    _UNKN_DnPUDSwing = "DnPUDSwing"
    _UNKN_Dpump = "Dpump"
    _UNKN_DsplySt = "DsplySt"
    _UNKN_DwatFul = "DwatFul"
    _UNKN_Dwet = "Dwet"
    _UNKN_Elc1Kwh = "Elc1Kwh"
    _UNKN_ElcAllKwhClr = "ElcAllKwhClr"
    _UNKN_ElcAllKwhH = "ElcAllKwhH"
    _UNKN_ElcAllKwhL = "ElcAllKwhL"
    _UNKN_ElcDatDte = "ElcDatDte"
    _UNKN_ElcDatHor = "ElcDatHor"
    _UNKN_ElcDatMth = "ElcDatMth"
    _UNKN_ElcErg = "ElcErg"
    _UNKN_ElcGear = "ElcGear"
    _UNKN_ElcOnKwh = "ElcOnKwh"
    _UNKN_ElcP = "ElcP"
    _UNKN_Emod = "Emod"
    _UNKN_EnergyFlow = "EnergyFlow"
    _UNKN_EnvArea1St = "EnvArea1St"
    _UNKN_EnvArea2St = "EnvArea2St"
    _UNKN_EnvArea3St = "EnvArea3St"
    _UNKN_EnvArea4St = "EnvArea4St"
    _UNKN_EnvArea5St = "EnvArea5St"
    _UNKN_EnvArea6St = "EnvArea6St"
    _UNKN_EnvArea7St = "EnvArea7St"
    _UNKN_EnvArea8St = "EnvArea8St"
    _UNKN_EnvArea9St = "EnvArea9St"
    _UNKN_EnvFun = "EnvFun"
    _UNKN_EvapClr = "EvapClr"
    _UNKN_FanMod = "FanMod"
    _UNKN_FavorMode = "FavorMode"
    _UNKN_FbidBloPer = "FbidBloPer"
    _UNKN_GasAvail = "GasAvail"
    _UNKN_GasLED = "GasLED"
    _UNKN_GasMas = "GasMas"
    _UNKN_GasMod = "GasMod"
    _UNKN_GasN = "GasN"
    _UNKN_GetEr = "GetEr"
    _UNKN_HabitLearn = "HabitLearn"
    _UNKN_HandCtl = "HandCtl"
    _UNKN_HasTmr = "HasTmr"
    _UNKN_HeatCool = "HeatCool"
    _UNKN_HeatNoise = "HeatNoise"
    _UNKN_HeatSvStTemMax = "HeatSvStTemMax"
    _UNKN_HumiSvStTemMin = "HumiSvStTemMin"
    _UNKN_HumSen = "HumSen"
    _UNKN_HumSor = "HumSor"
    _UNKN_IDUAirQu = "IDUAirQu"
    _UNKN_ImageRecovery = "ImageRecovery"
    _UNKN_ImgUpdateCol = "ImgUpdateCol"
    _UNKN_ImgUpdateFail = "ImgUpdateFail"
    _UNKN_ImgUpdateSta = "ImgUpdateSta"
    _UNKN_ImgUpdateSucs = "ImgUpdateSucs"
    _UNKN_ImgVerSta = "ImgVerSta"
    _UNKN_InEvaTem = "InEvaTem"
    _UNKN_InHid = "InHid"
    _UNKN_InHidDownPer = "InHidDownPer"
    _UNKN_InHidSvrVer = "InHidSvrVer"
    _UNKN_JFErrorCode = "JFErrorCode"
    _UNKN_LedLig = "LedLig"
    _UNKN_LTemDry = "LTemDry"
    _UNKN_MaeS = "MaeS"
    _UNKN_MakeWat = "MakeWat"
    _UNKN_MasIDUMod = "MasIDUMod"
    _UNKN_MasSub = "MasSub"
    _UNKN_MicroSen = "MicroSen"
    _UNKN_MidType = "MidType"
    _UNKN_ModS = "ModS"
    _UNKN_NewTimer = "NewTimer"
    _UNKN_NewTimerSet = "NewTimerSet"
    _UNKN_NobodySave = "NobodySave"
    _UNKN_NoD = "NoD"
    _UNKN_NoiseSet = "NoiseSet"
    _UNKN_ODUViti = "ODUViti"
    _UNKN_OEEPHid = "OEEPHid"
    _UNKN_OEEPHidDownPer = "OEEPHidDownPer"
    _UNKN_OEEPHidSvrVer = "OEEPHidSvrVer"
    _UNKN_PctCle = "PctCle"
    _UNKN_PctCleOnTm = "PctCleOnTm"
    _UNKN_PctCleSetTm = "PctCleSetTm"
    _UNKN_PctRe = "PctRe"
    _UNKN_PM2P5 = "PM2P5"
    _UNKN_PM2P5Sta = "PM2P5Sta"
    _UNKN_PM2P5V = "PM2P5V"
    _UNKN_PMVComfort = "PMVComfort"
    _UNKN_Purify = "Purify"
    _UNKN_RemWarnLig = "RemWarnLig"
    _UNKN_ReplaceHEPA = "ReplaceHEPA"
    _UNKN_ReportCtrl = "ReportCtrl"
    _UNKN_ReportFreq = "ReportFreq"
    _UNKN_ReportInterval = "ReportInterval"
    _UNKN_RoomHigh = "RoomHigh"
    _UNKN_RoomLen = "RoomLen"
    _UNKN_RoomWid = "RoomWid"
    _UNKN_SaveGuid = "SaveGuid"
    _UNKN_Security = "Security"
    _UNKN_SecurityMode = "SecurityMode"
    _UNKN_Sfog = "Sfog"
    _UNKN_Slp1H1 = "Slp1H1"
    _UNKN_Slp1H2 = "Slp1H2"
    _UNKN_Slp1H3 = "Slp1H3"
    _UNKN_Slp1H4 = "Slp1H4"
    _UNKN_Slp1H5 = "Slp1H5"
    _UNKN_Slp1H6 = "Slp1H6"
    _UNKN_Slp1H7 = "Slp1H7"
    _UNKN_Slp1H8 = "Slp1H8"
    _UNKN_Slp1L1 = "Slp1L1"
    _UNKN_Slp1L2 = "Slp1L2"
    _UNKN_Slp1L3 = "Slp1L3"
    _UNKN_Slp1L4 = "Slp1L4"
    _UNKN_Slp1L5 = "Slp1L5"
    _UNKN_Slp1L6 = "Slp1L6"
    _UNKN_Slp1L7 = "Slp1L7"
    _UNKN_Slp1L8 = "Slp1L8"
    _UNKN_SmartMod = "SmartMod"
    _UNKN_SmartSlpMod = "SmartSlpMod"
    _UNKN_SmartSlpModEx = "SmartSlpModEx"
    _UNKN_SmartWind = "SmartWind"
    _UNKN_Smod = "Smod"
    _UNKN_SorErr = "SorErr"
    _UNKN_Srst = "Srst"
    _UNKN_SrstAF = "SrstAF"
    _UNKN_SrstCF = "SrstCF"
    _UNKN_SrstPF = "SrstPF"
    _UNKN_SrstPP = "SrstPP"
    _UNKN_SrstRF = "SrstRF"
    _UNKN_StSlp1C = "StSlp1C"
    _UNKN_StSlp1CInc = "StSlp1CInc"
    _UNKN_StSlp1CSp = "StSlp1CSp"
    _UNKN_StSlp1H = "StSlp1H"
    _UNKN_StSlp1HInc = "StSlp1HInc"
    _UNKN_StSlp1HSp = "StSlp1HSp"
    _UNKN_StSlp2C = "StSlp2C"
    _UNKN_StSlp2CInc = "StSlp2CInc"
    _UNKN_StSlp2CSp = "StSlp2CSp"
    _UNKN_StSlp2H = "StSlp2H"
    _UNKN_StSlp2HInc = "StSlp2HInc"
    _UNKN_StSlp2HSp = "StSlp2HSp"
    _UNKN_StSlp3C = "StSlp3C"
    _UNKN_StSlp3CInc = "StSlp3CInc"
    _UNKN_StSlp3CSp = "StSlp3CSp"
    _UNKN_StSlp3H = "StSlp3H"
    _UNKN_StSlp3HInc = "StSlp3HInc"
    _UNKN_StSlp3HSp = "StSlp3HSp"
    _UNKN_StSlp4C = "StSlp4C"
    _UNKN_StSlp4CInc = "StSlp4CInc"
    _UNKN_StSlp4CSp = "StSlp4CSp"
    _UNKN_StSlp4H = "StSlp4H"
    _UNKN_StSlp4HInc = "StSlp4HInc"
    _UNKN_StSlp4HSp = "StSlp4HSp"
    _UNKN_StTmr = "StTmr"
    _UNKN_Swash = "Swash"
    _UNKN_Swat = "Swat"
    _UNKN_SwhDIYGra1 = "SwhDIYGra1"
    _UNKN_SwhFreAir = "SwhFreAir"
    _UNKN_SwhSw = "SwhSw"
    _UNKN_SwhWifi = "SwhWifi"
    _UNKN_SwhWifiCo = "SwhWifiCo"
    _UNKN_SwhWifiRe = "SwhWifiRe"
    _UNKN_TemSor = "TemSor"
    _UNKN_TemsSenOut = "TemsSenOut"
    _UNKN_TmrLpTms = "TmrLpTms"
    _UNKN_TmrOff = "TmrOff"
    _UNKN_TmrOffHorLf = "TmrOffHorLf"
    _UNKN_TmrOffMinLf = "TmrOffMinLf"
    _UNKN_TmrOn = "TmrOn"
    _UNKN_TmrOnHorLf = "TmrOnHorLf"
    _UNKN_TmrOnMinLf = "TmrOnMinLf"
    _UNKN_UDFanPort = "UDFanPort"
    _UNKN_UnmanedOffTime = "UnmanedOffTime"
    _UNKN_UnmanedShutDown = "UnmanedShutDown"
    _UNKN_UvcControl = "UvcControl"
    _UNKN_Video = "Video"
    _UNKN_VitiGr = "VitiGr"
    _UNKN_VOC = "VOC"
    _UNKN_VocCtl = "VocCtl"
    _UNKN_VocIdiom = "VocIdiom"
    _UNKN_VocRole = "VocRole"
    _UNKN_VocUpdateCol = "VocUpdateCol"
    _UNKN_VocUpdateRes = "VocUpdateRes"
    _UNKN_VocUpdateSta = "VocUpdateSta"
    _UNKN_VocVerSta = "VocVerSta"
    _UNKN_WatErr = "WatErr"
    _UNKN_WatTmp = "WatTmp"
    _UNKN_Werr = "Werr"
    _UNKN_Wet = "Wet"
    _UNKN_Wmod = "Wmod"
    _UNKN_WschOff = "WschOff"
    _UNKN_WschOffMin = "WschOffMin"
    _UNKN_WschOn = "WschOn"
    _UNKN_WschOnMin = "WschOnMin"
    _UNKN_WsenNub = "WsenNub"
    _UNKN_WsenTmpH = "WsenTmpH"
    _UNKN_WsenTmpL = "WsenTmpL"
    _UNKN_WsenTmpM = "WsenTmpM"
    _UNKN_WsetTmp = "WsetTmp"
    _UNKN_WstpH = "WstpH"
    _UNKN_WstpSv = "WstpSv"
    _UNKN_Wtmr1 = "Wtmr1"
    _UNKN_Wtmr1Min = "Wtmr1Min"
    _UNKN_Wtmr2 = "Wtmr2"
    _UNKN_Wtmr2Min = "Wtmr2Min"
    _UNKN_Wtmr3 = "Wtmr3"
    _UNKN_Wtmr3Min = "Wtmr3Min"
    # # INVALID
    # _INV_MafIdf = "MafIdf"
    # _INV_DevId = "DevID"


@unique
class TemperatureUnits(IntEnum):
    """Enumeration of temperature units."""

    C = 0
    F = 1


@unique
class OperationMode(IntEnum):
    """Enumeration of HVAC modes."""

    auto = 0
    cool = 1
    dry = 2
    fan = 3
    heat = 4


@unique
class FanSpeed(IntEnum):
    """Enumeration of fan speeds."""

    auto = 0
    low = 1
    medium_low = 2
    medium = 3
    medium_high = 4
    high = 5


@unique
class HorizontalSwingMode(IntEnum):
    """Enumeration of horizontal swing modes."""

    default = 0
    full_swing = 1
    left = 2
    left_center = 3
    center = 4
    right_center = 5
    right = 6


@unique
class VerticalSwingMode(IntEnum):
    """Enumeration of vertical swing modes."""

    default = 0
    full_swing = 1
    fixed_upper = 2
    fixed_upper_middle = 3
    fixed_middle = 4
    fixed_lower_middle = 5
    fixed_lower = 6
    swing_upper = 7
    swing_upper_middle = 8
    swing_middle = 9
    swing_lower_middle = 10
    swing_lower = 11


@unique
class SleepMode(IntEnum):
    """Enumeration of sleep modes types."""

    disabled = 0
    normal = 1
    advanced = 2
    diy = 3


class GreeCommand(IntEnum):
    """Enumeration of Gree commands."""

    STATUS = 0
    BIND = 1


@dataclass
class GreeDiscoveredDevice:
    """Device discovered data."""

    name: str
    host: str
    mac: str
    port: int
    brand: str
    model: str
    uid: int
    subdevices: int


async def get_result_pack(
    json_data: dict, cipher: CipherBase, transport: GreeTransport
) -> dict:
    """Get the result pack from the device (async)."""

    try:
        recv_json = await transport.request_json(json_data)
        data = get_gree_response_data(recv_json, cipher)
    except GreeConnectionError:
        raise
    except json.JSONDecodeError as err:
        raise GreeProtocolError("Invalid JSON response from device") from err
    except Exception as err:
        raise GreeProtocolError("Error in device response") from err

    pack = data.get("pack", None)

    if pack is None:
        raise GreeProtocolError("Device response missing 'pack' field")

    # Do not modify the original data
    redacted = data.copy()
    if "key" in redacted["pack"] and redacted["pack"]["key"]:
        redacted["pack"] = redacted["pack"].copy()
        redacted["pack"]["key"] = str(redacted["pack"]["key"])[:5] + "[redacted]"

    _LOGGER.debug("Got data from %s: %s", transport.ip_addr, redacted)

    return pack


def get_gree_response_data(
    recv_json: dict,
    cipher: CipherBase,
) -> dict:
    """Decodes a response from a gree device."""

    encoded_pack = recv_json.get("pack")
    tag = recv_json.get("tag")

    if encoded_pack:
        decrypted_pack = cipher.decrypt(encoded_pack, tag)
        # Replace encrypted pack with decrypted data
        recv_json["pack"] = json.loads(decrypted_pack)

    return recv_json


def gree_encrypt_pack(
    pack: dict,
    cipher: CipherBase,
) -> tuple[str, str | None]:
    """Create an encrypted pack to send to the device."""

    if cipher is None:
        raise GreeError("Cipher must not be None")

    encrypted_data, tag = cipher.encrypt(json.dumps(pack))

    # WARNING: My device does not respond if the encrypted_pack is more that 1024 bytes
    if len(encrypted_data.encode("utf-8")) > 1024:
        _LOGGER.warning("Pack length is over 1024 bytes")

    return (encrypted_data, tag)


def gree_create_bind_pack(mac_addr: str, uid: int, cipher: CipherBase) -> dict:
    """Create a bind pack to send to the device."""

    pack: dict = {}

    if cipher.version == EncryptionVersion.V1:
        pack = {"mac": mac_addr, "t": "bind", "uid": uid}
    elif cipher.version == EncryptionVersion.V2:
        pack = {"cid": mac_addr, "mac": mac_addr, "t": "bind", "uid": uid}

    _LOGGER.debug("Bind Pack: %s", pack)
    return pack


def gree_create_sub_bind_pack(mac_addr: str) -> dict:
    """Create a bind pack to send to the device."""

    pack: dict = {"mac": mac_addr, "i": 1}

    _LOGGER.debug("Sub Bind Pack: %s", pack)
    return pack


def gree_create_status_pack(mac_addr: str, props: list[str]) -> dict:
    """Create a status pack to send to the device."""

    pack: dict = {"cols": props, "mac": mac_addr, "t": "status"}

    _LOGGER.debug("Status Pack: %s", pack)
    return pack


def gree_create_set_pack(mac_addr: str, props: dict[GreeProp, int]) -> dict:
    """Create a set pack to send to the device."""

    pack: dict = {
        "opt": [prop.value for prop in props],
        "p": list(props.values()),
        "t": "cmd",
        "sub": mac_addr,
    }

    _LOGGER.debug("Status Pack: %s", pack)
    return pack


def gree_create_payload(
    pack: str,
    payload_type: str,
    i_command: GreeCommand,
    mac_addr: str,
    uid: int,
    tag: str | None,
) -> dict:
    """Create the full payload to send to the device."""

    payload: dict[str, Any] = {
        "cid": "app",
        "i": i_command.value,
        "pack": pack,
        "t": payload_type,
        "tcid": mac_addr,
        "uid": uid,
    }

    if tag is not None:
        payload["tag"] = tag

    _LOGGER.debug("Payload: %s", payload)
    return payload


async def gree_try_bind(
    mac_addr: str,
    uid: int,
    version: EncryptionVersion | None,
    key: str | None,
    transport: GreeTransport,
) -> tuple[str, EncryptionVersion]:
    """Perform bind request to the device and return the valid version and key (async).

    Performs the bind with the provided key or version. Falls back to generic keys.
    If the provided key or version do not match the device, the function will return the correct device key and version.
    """

    ret_key: str = ""
    error: Exception | None = Exception("Binding failed")

    has_version = version is not None
    has_key = key is not None and bool(key.strip())

    ciphers: list[CipherBase] = []

    if has_version:
        ciphers.append(get_cipher(version))
        if has_key:
            _LOGGER.info(
                "Trying to perform binding. Prefer provided version (%s) and key (%s)",
                version,
                key[:5] + "[redacted]",
            )
        else:
            _LOGGER.info(
                "Trying to perform binding. Prefer provided version (%s) and generic key ",
                version,
            )
    elif has_key:
        _LOGGER.info(
            "Trying to perform binding. Prefering provided key (%s)",
            key[:5] + "[redacted]",
        )
    else:
        _LOGGER.info(
            "Trying to perform binding. Testing both versions with generic keys"
        )

    # Fallback to both default ciphers
    ciphers.append(get_cipher(EncryptionVersion.V1))
    ciphers.append(get_cipher(EncryptionVersion.V2))

    for cipher in ciphers:
        _LOGGER.debug(
            "Requesting bind to device with encryption key v%d", cipher.version
        )

        pack = gree_create_bind_pack(mac_addr, uid, cipher)
        encrypted_pack, tag = gree_encrypt_pack(pack, cipher)
        json_payload = gree_create_payload(
            encrypted_pack, "pack", GreeCommand.BIND, mac_addr, uid, tag
        )

        try:
            result = await get_result_pack(json_payload, cipher, transport)

        except Exception as err:
            _LOGGER.exception(
                "Error in bind request using encryption key with version %d",
                cipher.version,
            )

            # In case we are testing multiple ciphers, don't raise,
            # just save the error so we can continue testing the other ciphers
            error = err
            continue

        else:
            ret_key = result.get("key", "")

            if ret_key.strip() == "":
                raise GreeBindingError(
                    "Binding failed: Received empty encryption key from device"
                )

            if has_key and ret_key != key:
                _LOGGER.warning(
                    "Binding successful with different key. Using retrieved key. Expected '%s', got '%s'",
                    key[:5] + "[redacted]",
                    ret_key[:5] + "[redacted]",
                )

            if has_version and cipher.version != version:
                _LOGGER.warning(
                    "Binding successful with different version. Using retrieved version. Expected '%s', got '%s'",
                    version,
                    cipher.version,
                )

            _LOGGER.info("Bind request with version %d was successful", cipher.version)

            _LOGGER.debug("Fetched encryption key: %s[redacted]", ret_key[:5])

            return ret_key, cipher.version

    raise GreeBindingError(
        f"Binding failed: Unable to obtain valid encryption version and key pair for {mac_addr} at {transport.ip_addr}"
    ) from error


async def gree_get_status(
    mac_addr_controller: str,
    mac_addr: str,
    uid: int,
    props: list[str],
    cipher: CipherBase,
    transport: GreeTransport,
) -> tuple[dict[str, str], list[str]]:
    """Get the status of the device by sending a status request to the device (async). Also returns the props not present.

    Gree Protocol is a best-effort key/value response with no guaranteed completeness

    If a invalid prop is requested the response will not have it which is good
    However, some "invalid" props are returned in the response with no data, making it impossible to know in a batch where they are
    Note: Invalid != Unsupported

    Meaning:

    cols = what the device claims it is returning
    dat = best-effort values, possibly incomplete
    alignment between them is not guaranteed globally

    As such, it is only safe to batch props that are known to work.
    """

    _LOGGER.debug("Getting status for device '%s'", mac_addr)

    # Filter empty, none and white spaces
    props = [p for p in props if p is not None and p.strip()]

    pack = gree_create_status_pack(mac_addr, props)
    encrypted_pack, tag = gree_encrypt_pack(pack, cipher)

    json_payload = gree_create_payload(
        encrypted_pack, "pack", GreeCommand.STATUS, mac_addr_controller, uid, tag
    )

    try:
        result = await get_result_pack(json_payload, cipher, transport)

    except GreeConnectionError, GreeProtocolError:
        raise

    except Exception as err:
        raise GreeProtocolError("Error getting device status") from err

    cols = result.get("cols")
    dat = result.get("dat")

    if cols is None or dat is None:
        raise GreeProtocolError("No data received while getting device status")

    if len(cols) != len(dat):
        if len(cols) == 1:
            # if there is a single prop without value, add to missing
            _LOGGER.error(
                "Device '%s' was queried for invalid prop: %s", mac_addr, cols
            )
            return {}, [cols]

        raise GreeProtocolError(f"Malformed response: cols={len(cols)} dat={len(dat)}")

    status_values: dict[str, str] = {}
    returned_props: set[str] = set()

    for prop, value in zip(cols, dat, strict=True):
        returned_props.add(prop)
        status_values[prop] = value

    invalid_props = [p for p in props if p not in returned_props]

    _LOGGER.debug("Got status for device '%s': %s", mac_addr, status_values)

    if len(invalid_props) > 0:
        _LOGGER.error(
            "Device '%s' was queried for invalid props: %s", mac_addr, invalid_props
        )
    return status_values, invalid_props


async def gree_set_status(
    mac_addr_controller: str,
    mac_addr: str,
    uid: int,
    props: dict[GreeProp, int],
    cipher: CipherBase,
    transport: GreeTransport,
) -> dict[GreeProp, int]:
    """Set the status of the device by sending a status request to the device (async)."""

    _LOGGER.debug("Trying to set device status")

    pack = gree_create_set_pack(mac_addr, props)
    encrypted_pack, tag = gree_encrypt_pack(pack, cipher)
    json_payload = gree_create_payload(
        encrypted_pack, "pack", GreeCommand.STATUS, mac_addr_controller, uid, tag
    )

    try:
        result = await get_result_pack(json_payload, cipher, transport)

    except GreeConnectionError, GreeProtocolError:
        raise

    except Exception as err:
        raise GreeProtocolError("Error getting device status") from err

    if result["r"] is None or result["r"] != 200:
        raise GreeProtocolError(
            f"Error setting device status, response code: {result['r']}"
        )

    options_set = [PROP_KEY_TO_ENUM[c] for c in result["opt"] if c in PROP_KEY_TO_ENUM]
    if options_set is None or len(options_set) == 0:
        raise GreeProtocolError("No options were set, something went wrong")

    values_set_1 = result.get("p", None)
    values_set_2 = result.get("val", None)  # this one is optional

    if values_set_1 is None:
        raise GreeProtocolError("No values were set, something went wrong")
    values_set_1 = list(map(int, values_set_1))

    if values_set_2 is not None:
        values_set_2 = list(map(int, values_set_2))
        if len(values_set_1) != len(values_set_2):
            raise GreeProtocolError(
                f"Wrong option values received: {values_set_1} {values_set_2}"
            )

    if len(values_set_1) != len(options_set):
        raise GreeProtocolError(
            f"Options and values set mismatch {options_set} {values_set_1}"
        )

    updated_props = dict(zip(options_set, values_set_1, strict=True))
    if updated_props != props:
        _LOGGER.warning("Expected updated props %s but got %s", props, updated_props)

    return updated_props


async def gree_get_device_info(
    transport: GreeTransport, cipher: CipherBase | None = None
) -> dict[str, str | dict | None]:
    """Tries to retrive the device info."""

    data: dict = await get_result_pack(
        {"t": "scan"},
        cipher or get_cipher(EncryptionVersion.V1),
        transport,
    )

    _LOGGER.debug("Got device info: %s", data)

    info: dict[str, str | dict | None] = {}
    info["raw"] = data
    info["firmware_version"], info["firmware_code"] = extract_version(data)
    info["mac"] = data.get("mac", "")
    info["subdevices_count"] = data.get("subCnt", 0)
    return info


def extract_version(info: dict) -> tuple[str | None, str | None]:
    """Finds the firmware info."""
    hid = info.get("hid", "")
    ver_match = re.search(r"V([\d.]+)\.bin", hid)
    if ver_match:
        ver = ver_match.group(1)  # version from hid
    else:
        ver = info.get("ver")
        ver = ver.lstrip("V") if ver else None  # clean ver or None

    id_match = re.match(r"(\d+)", hid)  # leading digits
    device_id = id_match.group(1) if id_match else None
    return ver, device_id


async def discover_gree_devices(
    broadcast_addresses: list[str], timeout: int
) -> list[GreeDiscoveredDevice]:
    """Discovers gree devices in the network."""

    discovered_devices: list[GreeDiscoveredDevice] = []

    responses = await async_udp_broadcast_request(
        broadcast_addresses, DEFAULT_DEVICE_PORT, json.dumps({"t": "scan"}), timeout
    )

    for address, response in responses.items():
        data = get_gree_response_data(
            response,
            get_cipher(EncryptionVersion.V1),
        )
        if data is not None:
            pack = data.get("pack")
            if pack is not None:
                if pack.get("t") == "dev":
                    mac_addr = pack.get("mac", "")
                    if not mac_addr:
                        _LOGGER.debug("No MAC address in response from %s", address)
                        continue

                    # Just collect basic device info for now - encryption detection happens later
                    discovered_device = GreeDiscoveredDevice(
                        name=pack.get("name", "") or f"Gree {mac_addr[-4:]}",
                        host=address,
                        mac=mac_addr,
                        port=DEFAULT_DEVICE_PORT,
                        brand=pack.get("brand", "gree"),
                        model=pack.get("brand", "gree"),
                        uid=data.get("uid", 0),
                        subdevices=pack.get("subCnt", 0),
                    )

                    discovered_devices.append(discovered_device)
                    _LOGGER.debug("Discovered device: %s", discovered_device)

                    # # If VRF, the mac is of the main device and we have to query it for the sub devices
                    # # Sub-devices will be created with a mac of sub@main
                    # # check if the device has sub-devices
                    # sub_count = pack.get("subCnt", 0)

                    # if sub_count > 0:
                    #     # Is VRF with multiple sub devices
                    #     _LOGGER.debug(
                    #         "Trying to fetching sub-devices for '%s' (subCount=%d)",
                    #         mac_addr,
                    #         sub_count,
                    #     )
                    #     try:
                    #         discovered_sub_devices = await get_sub_devices_list(
                    #             discovered_device.mac,
                    #             discovered_device.host,
                    #             discovered_device.uid,
                    #             max_connection_attempts=2,
                    #             timeout=timeout,
                    #         )

                    #         for sub_device in discovered_sub_devices:
                    #             sub_mac = sub_device.get("mac", "")
                    #             if sub_mac:
                    #                 discovered_sub_device = GreeDiscoveredDevice(
                    #                     name=f"{discovered_device.name or f'Gree {mac_addr[-4:]}'}@{sub_mac[:4]}",
                    #                     host=discovered_device.host,
                    #                     mac=f"{sub_mac}@{discovered_device.mac}",
                    #                     port=discovered_device.port,
                    #                     brand=discovered_device.brand,
                    #                     model=sub_device.get("mid", discovered_device),
                    #                     uid=discovered_device.uid,
                    #                 )
                    #                 discovered_devices.append(discovered_sub_device)
                    #                 _LOGGER.debug(
                    #                     "Discovered sub-device: %s",
                    #                     discovered_sub_device,
                    #                 )
                    #     except Exception:
                    #         _LOGGER.exception("Failed to fetch sub-devices")

    return discovered_devices


async def gree_get_sub_devices_list(
    mac_addr: str, uid: int, cipher: CipherBase, transport: GreeTransport
) -> list:
    """Fetch the list of sub-devices for a Gree device."""
    try:
        pack = gree_create_sub_bind_pack(mac_addr)
        encrypted_pack, tag = gree_encrypt_pack(
            pack,
            cipher,
        )

        json_payload = gree_create_payload(
            encrypted_pack,
            "subList",
            GreeCommand.BIND,
            mac_addr,
            uid,
            tag,
        )

        result = await get_result_pack(json_payload, cipher, transport)

        return result.get("list", [])

    except Exception as err:
        raise GreeProtocolError(
            f"Error fetching sub-device list for '{mac_addr}'"
        ) from err
