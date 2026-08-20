"""Contains the API to interface with the Gree device."""

from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from enum import IntEnum, StrEnum, unique
import json
import logging
import re
from typing import Any, NamedTuple

from pydantic import BaseModel, ConfigDict

from .cipher import CipherBase, EncryptionVersion, get_cipher
from .cloud_api import GreeCloudApi
from .const import DEFAULT_DEVICE_PORT, DEFAULT_DEVICE_USERID, MAX_PACK_SIZE
from .errors import GreeBindingError, GreeConnectionError, GreeError, GreeProtocolError
from .helpers import gree_extract_macs, redact_str
from .transport import GreeBaseTransport
from .transport_udp import GreeUdpTransport, async_udp_broadcast_request

_LOGGER = logging.getLogger(__name__)


class GreeProp(StrEnum):
    """Enumeration of device properties."""

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
    # humidity control mode. uses dry under cool mode
    FEATURE_HUMIDITY_CONTROL = "Dmod"
    # humidity control mode. sets the humidity target for the humidity control mode. (HUM% - 15) / 5
    FEATURE_HUMIDITY_TARGET = "Dwet"

    # SENSORS
    # indoor temperature sensors, used to read the current room temperature, if available, ordered by preference
    SENSOR_INDOOR_TEMPERATURE_1 = "EnvTem"
    SENSOR_INDOOR_TEMPERATURE_2 = "InEvaTem"
    SENSOR_INDOOR_TEMPERATURE_3 = "TemSen"  # value heavily varies with operation mode
    # outside temperature sensors, used to read the current outdooors temperature, if available, ordered by preference
    SENSOR_OUTSIDE_TEMPERATURE_1 = "OutEnvTem"
    SENSOR_OUTSIDE_TEMPERATURE_2 = "TemsSenOut"
    # indoor humidity sensor, used to read the current room humidity, if available, ordered by preference
    SENSOR_HUMIDITY_1 = "DwatSen"
    SENSOR_HUMIDITY_2 = "HumSen"
    # error display. 0 if no error, otherwise error
    SENSOR_FAULT = "FaultDisplay"

    # If set to 0 the unit will beep on every command
    BEEPER = "Buzzer_ON_OFF"
    # If set to 1 the unit will beep on every command (available on newer firmwares)
    BEEPER_NEW = "BuzzerCtrl"


PROP_KEY_TO_ENUM = {prop.value: prop for prop in GreeProp}


class InfoProp(StrEnum):
    """Enumeration of props that return device information."""

    DEVICE_MAC = "mac"
    DEVICE_NAME = "name"
    BC = "bc"
    MODEL_TYPE = "ModelType"
    MODEL_NEW = "ModelNew"
    MID = "mid"
    MID_TYPE = "MidType"
    HID = "hid"
    SERVER = "host"
    VENDER = "vender"
    PROTOCOL_VERSION = "ver"
    WIFI_STATUS = "wifiStatus"
    WIFI_RESET = "wifiReset"
    BUS = "busVol"


INFOPROP_KEY_TO_ENUM = {prop.value: prop for prop in InfoProp}


class OtherProps(StrEnum):
    """Enumeration of additional device properties."""

    UNKN_ACStupPos = "ACStupPos"
    UNKN_ActiveTime = "ActiveTime"
    UNKN_Add0_1 = "Add0.1"
    UNKN_Add0_5 = "Add0.5"
    UNKN_AirQ = "AirQ"
    UNKN_AllErr = "AllErr"
    UNKN_Antifreeze = "Antifreeze"
    UNKN_AppTimer = "AppTimer"
    UNKN_AssHt = "AssHt"
    UNKN_AutoClean = "AutoClean"
    UNKN_AutoCleanSta = "AutoCleanSta"
    UNKN_AutoCleanStaEx = "AutoCleanStaEx"
    UNKN_AutoComnCloud = "AutoComnCloud"
    UNKN_AutoPowReduce = "AutoPowReduce"
    UNKN_AutoUpdate = "AutoUpdate"
    UNKN_BlkTemCom = "BlkTemCom"
    UNKN_ChildLock = "ChildLock"
    UNKN_CO2 = "CO2"
    UNKN_CO2Level = "CO2Level"
    UNKN_CommErr = "CommErr"
    UNKN_CompressorFqy = "CompressorFqy"
    UNKN_CompressorTem = "CompressorTem"
    UNKN_CoolFeel = "CoolFeel"
    UNKN_Coolmod = "Coolmod"
    UNKN_CoolNoise = "CoolNoise"
    UNKN_CoolSvStTemMin = "CoolSvStTemMin"
    UNKN_CpsTem = "CpsTem"
    UNKN_CurTmHor = "CurTmHor"
    UNKN_CurTmMin = "CurTmMin"
    UNKN_Dazzling = "Dazzling"
    UNKN_Defrost = "Defrost"
    UNKN_Dfltr = "Dfltr"
    UNKN_DFPoint = "DFPoint"
    UNKN_DIYGra1PoiAmo = "DIYGra1PoiAmo"
    UNKN_DnPLLRSwing = "DnPLLRSwing"
    UNKN_DnPRLRSwing = "DnPRLRSwing"
    UNKN_DnPUDSwing = "DnPUDSwing"
    UNKN_Dpump = "Dpump"
    UNKN_DsplySt = "DsplySt"
    UNKN_DwatFul = "DwatFul"
    UNKN_Elc1Kwh = "Elc1Kwh"
    UNKN_ElcAllKwhClr = "ElcAllKwhClr"
    UNKN_ElcAllKwhH = "ElcAllKwhH"
    UNKN_ElcAllKwhL = "ElcAllKwhL"
    UNKN_ElcDatDte = "ElcDatDte"
    UNKN_ElcDatHor = "ElcDatHor"
    UNKN_ElcDatMth = "ElcDatMth"
    UNKN_ElcEn = "ElcEn"
    UNKN_ElcErg = "ElcErg"
    UNKN_ElcGear = "ElcGear"
    UNKN_ElcOnKwh = "ElcOnKwh"
    UNKN_ElcP = "ElcP"
    UNKN_Emod = "Emod"
    UNKN_EnergyFlow = "EnergyFlow"
    UNKN_EnvArea1St = "EnvArea1St"
    UNKN_EnvArea2St = "EnvArea2St"
    UNKN_EnvArea3St = "EnvArea3St"
    UNKN_EnvArea4St = "EnvArea4St"
    UNKN_EnvArea5St = "EnvArea5St"
    UNKN_EnvArea6St = "EnvArea6St"
    UNKN_EnvArea7St = "EnvArea7St"
    UNKN_EnvArea8St = "EnvArea8St"
    UNKN_EnvArea9St = "EnvArea9St"
    UNKN_EnvFun = "EnvFun"
    UNKN_EnvTem = "EnvTem"
    UNKN_estateInsta21 = "estateInsta21"
    UNKN_estateInsta22 = "estateInsta22"
    UNKN_estateInsta23 = "estateInsta23"
    UNKN_estateInsta24 = "estateInsta24"
    UNKN_EvapClr = "EvapClr"
    UNKN_FanMod = "FanMod"
    UNKN_FavorMode = "FavorMode"
    UNKN_FbidBloPer = "FbidBloPer"
    UNKN_GasAvail = "GasAvail"
    UNKN_GasLED = "GasLED"
    UNKN_GasMas = "GasMas"
    UNKN_GasMod = "GasMod"
    UNKN_GasN = "GasN"
    UNKN_GetEr = "GetEr"
    UNKN_HabitLearn = "HabitLearn"
    UNKN_HandCtl = "HandCtl"
    UNKN_HasTmr = "HasTmr"
    UNKN_HeatCool = "HeatCool"
    UNKN_HeatCoolType = "HeatCoolType"
    UNKN_HeatNoise = "HeatNoise"
    UNKN_HeatSvStTemMax = "HeatSvStTemMax"
    UNKN_HumiSvStTemMin = "HumiSvStTemMin"
    UNKN_HumSor = "HumSor"
    UNKN_IDUAirQu = "IDUAirQu"
    UNKN_ImageRecovery = "ImageRecovery"
    UNKN_ImgUpdateCol = "ImgUpdateCol"
    UNKN_ImgUpdateFail = "ImgUpdateFail"
    UNKN_ImgUpdateSta = "ImgUpdateSta"
    UNKN_ImgUpdateSucs = "ImgUpdateSucs"
    UNKN_ImgVerSta = "ImgVerSta"
    UNKN_InEvaTem = "InEvaTem"
    UNKN_InHid = "InHid"
    UNKN_InHidDownPer = "InHidDownPer"
    UNKN_InHidSvrVer = "InHidSvrVer"
    UNKN_JFErrorCode = "JFErrorCode"
    UNKN_LedLig = "LedLig"
    UNKN_LedLight = "LedLight"
    UNKN_LTemDry = "LTemDry"
    UNKN_MaeS = "MaeS"
    UNKN_MakeWat = "MakeWat"
    UNKN_MasIDUMod = "MasIDUMod"
    UNKN_MasSub = "MasSub"
    UNKN_MicroSen = "MicroSen"
    UNKN_MMWPosRpt = "MMWPosRpt"
    UNKN_ModS = "ModS"
    UNKN_NewTimer = "NewTimer"
    UNKN_NewTimerSet = "NewTimerSet"
    UNKN_NightLig = "NightLig"
    UNKN_NobodySave = "NobodySave"
    UNKN_NoD = "NoD"
    UNKN_NoiseSet = "NoiseSet"
    UNKN_ODUViti = "ODUViti"
    UNKN_OEEPHid = "OEEPHid"
    UNKN_OEEPHidDownPer = "OEEPHidDownPer"
    UNKN_OEEPHidSvrVer = "OEEPHidSvrVer"
    UNKN_OxygenDisplay = "OxygenDisplay"
    UNKN_OxygenSwitch = "OxygenSwitch"
    UNKN_PctCle = "PctCle"
    UNKN_PctCleOnTm = "PctCleOnTm"
    UNKN_PctCleSetTm = "PctCleSetTm"
    UNKN_PctRe = "PctRe"
    UNKN_PM2P5 = "PM2P5"
    UNKN_PM2P5Sta = "PM2P5Sta"
    UNKN_PM2P5V = "PM2P5V"
    UNKN_PMVComfort = "PMVComfort"
    UNKN_PowReduceType = "PowReduceType"
    UNKN_Purify = "Purify"
    UNKN_RemWarnLig = "RemWarnLig"
    UNKN_ReplaceHEPA = "ReplaceHEPA"
    UNKN_ReportCtrl = "ReportCtrl"
    UNKN_ReportFreq = "ReportFreq"
    UNKN_ReportInterval = "ReportInterval"
    UNKN_RoomHigh = "RoomHigh"
    UNKN_RoomLen = "RoomLen"
    UNKN_RoomWid = "RoomWid"
    UNKN_SaveGuid = "SaveGuid"
    UNKN_Security = "Security"
    UNKN_SecurityMode = "SecurityMode"
    UNKN_Sfog = "Sfog"
    UNKN_ShutdownFault = "ShutdownFault"
    UNKN_Slp1H1 = "Slp1H1"
    UNKN_Slp1H2 = "Slp1H2"
    UNKN_Slp1H3 = "Slp1H3"
    UNKN_Slp1H4 = "Slp1H4"
    UNKN_Slp1H5 = "Slp1H5"
    UNKN_Slp1H6 = "Slp1H6"
    UNKN_Slp1H7 = "Slp1H7"
    UNKN_Slp1H8 = "Slp1H8"
    UNKN_Slp1L1 = "Slp1L1"
    UNKN_Slp1L2 = "Slp1L2"
    UNKN_Slp1L3 = "Slp1L3"
    UNKN_Slp1L4 = "Slp1L4"
    UNKN_Slp1L5 = "Slp1L5"
    UNKN_Slp1L6 = "Slp1L6"
    UNKN_Slp1L7 = "Slp1L7"
    UNKN_Slp1L8 = "Slp1L8"
    UNKN_SmartMod = "SmartMod"
    UNKN_SmartSlpMod = "SmartSlpMod"
    UNKN_SmartSlpModEx = "SmartSlpModEx"
    UNKN_SmartWind = "SmartWind"
    UNKN_Smod = "Smod"
    UNKN_SorErr = "SorErr"
    UNKN_Srst = "Srst"
    UNKN_SrstAF = "SrstAF"
    UNKN_SrstCF = "SrstCF"
    UNKN_SrstPF = "SrstPF"
    UNKN_SrstPP = "SrstPP"
    UNKN_SrstRF = "SrstRF"
    UNKN_StSlp1C = "StSlp1C"
    UNKN_StSlp1CInc = "StSlp1CInc"
    UNKN_StSlp1CSp = "StSlp1CSp"
    UNKN_StSlp1H = "StSlp1H"
    UNKN_StSlp1HInc = "StSlp1HInc"
    UNKN_StSlp1HSp = "StSlp1HSp"
    UNKN_StSlp2C = "StSlp2C"
    UNKN_StSlp2CInc = "StSlp2CInc"
    UNKN_StSlp2CSp = "StSlp2CSp"
    UNKN_StSlp2H = "StSlp2H"
    UNKN_StSlp2HInc = "StSlp2HInc"
    UNKN_StSlp2HSp = "StSlp2HSp"
    UNKN_StSlp3C = "StSlp3C"
    UNKN_StSlp3CInc = "StSlp3CInc"
    UNKN_StSlp3CSp = "StSlp3CSp"
    UNKN_StSlp3H = "StSlp3H"
    UNKN_StSlp3HInc = "StSlp3HInc"
    UNKN_StSlp3HSp = "StSlp3HSp"
    UNKN_StSlp4C = "StSlp4C"
    UNKN_StSlp4CInc = "StSlp4CInc"
    UNKN_StSlp4CSp = "StSlp4CSp"
    UNKN_StSlp4H = "StSlp4H"
    UNKN_StSlp4HInc = "StSlp4HInc"
    UNKN_StSlp4HSp = "StSlp4HSp"
    UNKN_StTmr = "StTmr"
    UNKN_SubhealthFault = "SubhealthFault"
    UNKN_Swash = "Swash"
    UNKN_Swat = "Swat"
    UNKN_SwhDIYGra1 = "SwhDIYGra1"
    UNKN_SwhFreAir = "SwhFreAir"
    UNKN_SwhSw = "SwhSw"
    UNKN_SwhWifi = "SwhWifi"
    UNKN_SwhWifiCo = "SwhWifiCo"
    UNKN_SwhWifiRe = "SwhWifiRe"
    UNKN_TemSor = "TemSor"
    UNKN_TemsSenOut = "TemsSenOut"
    UNKN_TmrLpTms = "TmrLpTms"
    UNKN_TmrOff = "TmrOff"
    UNKN_TmrOffHorLf = "TmrOffHorLf"
    UNKN_TmrOffMinLf = "TmrOffMinLf"
    UNKN_TmrOn = "TmrOn"
    UNKN_TmrOnHorLf = "TmrOnHorLf"
    UNKN_TmrOnMinLf = "TmrOnMinLf"
    UNKN_UDFanPort = "UDFanPort"
    UNKN_UniqueCode = "UniqueCode"
    UNKN_UnmanedOffTime = "UnmanedOffTime"
    UNKN_UnmanedSetting = "UnmanedSetting"
    UNKN_UnmanedShutDown = "UnmanedShutDown"
    UNKN_UvcControl = "UvcControl"
    UNKN_Video = "Video"
    UNKN_VitiGr = "VitiGr"
    UNKN_VOC = "VOC"
    UNKN_VocCtl = "VocCtl"
    UNKN_VocIdiom = "VocIdiom"
    UNKN_VocRole = "VocRole"
    UNKN_VocUpdateCol = "VocUpdateCol"
    UNKN_VocUpdateRes = "VocUpdateRes"
    UNKN_VocUpdateSta = "VocUpdateSta"
    UNKN_VocVerSta = "VocVerSta"
    UNKN_WatErr = "WatErr"
    UNKN_WatTmp = "WatTmp"
    UNKN_Werr = "Werr"
    UNKN_Wet = "Wet"
    UNKN_Widn = "Wind"
    UNKN_WisdomRisk = "WisdomRisk"
    UNKN_Wmod = "Wmod"
    UNKN_WschOff = "WschOff"
    UNKN_WschOffMin = "WschOffMin"
    UNKN_WschOn = "WschOn"
    UNKN_WschOnMin = "WschOnMin"
    UNKN_WsenNub = "WsenNub"
    UNKN_WsenTmpH = "WsenTmpH"
    UNKN_WsenTmpL = "WsenTmpL"
    UNKN_WsenTmpM = "WsenTmpM"
    UNKN_WsetTmp = "WsetTmp"
    UNKN_WstpH = "WstpH"
    UNKN_WstpSv = "WstpSv"
    UNKN_Wtmr1 = "Wtmr1"
    UNKN_Wtmr1Min = "Wtmr1Min"
    UNKN_Wtmr2 = "Wtmr2"
    UNKN_Wtmr2Min = "Wtmr2Min"
    UNKN_Wtmr3 = "Wtmr3"
    UNKN_Wtmr3Min = "Wtmr3Min"
    # # INVALID
    # INV_MafIdf = "MafIdf"
    # INV_DevId = "DevID"


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
    """Enumeration of sleep mode types."""

    disabled = 0
    normal = 1
    advanced = 2
    diy = 3


@unique
class HumidityControlMode(IntEnum):
    """Enumeration of the humidity control modes."""

    disabled = 15
    target_dry = 0
    continuous_dry = 1  # This is only available in dry operation mode
    smart_dry = 2  # This is only available in cool operation mode


class GreeCommand(StrEnum):
    """Enumeration of Gree commands."""

    GET_STATE = "status"
    BIND = "bind"
    SET_STATE = "cmd"
    SCAN = "scan"


class DeviceScanInfoResponse(BaseModel):
    """Response data for a Gree device returned in a UDP scan."""

    # Scan Responses format:
    # {"t":"dev","bc":"","catalog":"gree","series":"gree","model":"gree","lock":0,"vender":"1","mid":"60","name":"GR-Gcloud_60_0a_5ba3_EC","ver":"V3.2.M","mac":"9424b8fd5ba3","subCnt":6}
    # {'t': 'dev', 'cid': 'c03937b12280', 'bc': '00000000000000000000000000000000', 'brand': 'gree', 'catalog': 'gree', 'mac': 'c03937b12280', 'mid': '10001', 'model': 'gree', 'name': '', 'lock': 0, 'series': 'gree', 'vender': '1', 'ver': 'V3.4.M', 'ModelType': '32776', 'hid': '362001065279+U-WB05RT13V1.45.bin'}
    model_config = ConfigDict(extra="ignore")

    t: str
    cid: str
    mac: str
    bc: str | None = None
    brand: str | None = None
    catalog: str | None = None
    mid: str | None = None
    model: str | None = None
    name: str | None = None
    lock: bool | None = None
    series: str | None = None
    vender: str | None = None
    ver: str | None = None
    ModelType: str | None = None
    hid: str | None = None
    subCnt: int | None = None  # noqa: N815


@dataclass
class GreeDiscoveredDevice:
    """Representation of a discovered Gree device."""

    # Device Id
    mac: str
    mac_controller: str
    user_id: int = DEFAULT_DEVICE_USERID
    key: str | None = None
    # Local
    host: str | None = None
    port: int | None = None
    # Cloud
    username: str | None = None
    # Properties
    name: str = ""
    catalog: str = ""
    brand: str = "gree"
    model: str = "gree"
    model_type: str = ""
    vender: str = ""
    # Firmware
    mid: str = ""
    hid: str = ""
    ver: str = ""


class StatusResult(NamedTuple):
    """The result of a status request."""

    prop_values: dict[str, str]
    missin_props: list[str]


class BindingInfo(NamedTuple):
    """Combination of key and encryption version from a binding procedure."""

    encryption_key: str
    encryption_version: EncryptionVersion


async def gree_get_response(
    mac_controller: str,
    json_data: dict,
    cipher: CipherBase,
    transport: GreeBaseTransport,
) -> dict:
    """Send a request to the device and return the decoded response.

    Args:
        mac_controller: MAC of the controller device
        json_data: JSON payload to send
        cipher: Device cipher to encrypt and decrypt the JSON pack, if present
        transport: Transport to send the emssage throuhg

    Returns:
        Decrypted JSON response

    """

    try:
        data = await transport.request_json(mac_controller, json_data, cipher)
    except GreeConnectionError:
        raise
    except json.JSONDecodeError as err:
        raise GreeProtocolError("Invalid JSON response from device") from err
    except Exception as err:
        raise GreeProtocolError("Error in device response") from err

    return data


async def gree_get_response_pack(
    mac_controller: str,
    json_data: dict,
    cipher: CipherBase,
    transport: GreeBaseTransport,
) -> dict:
    """Send a request to the device and return the decoded response pack.

    Args:
        mac_controller: MAC of the controller device
        json_data: JSON payload to send
        cipher: Device cipher to encrypt and decrypt the JSON pack, if present
        transport: Transport to send the emssage throuhg

    Returns:
        Decrypted JSON pack response

    """

    data = await gree_get_response(mac_controller, json_data, cipher, transport)

    pack = data.get("pack", None)

    if pack is None:
        raise GreeProtocolError("Device response missing 'pack' field")

    # Do not modify the original data
    redacted = data.copy()
    if "key" in redacted["pack"] and redacted["pack"]["key"]:
        redacted["pack"] = redacted["pack"].copy()
        redacted["pack"]["key"] = redact_str(str(redacted["pack"]["key"]))

    _LOGGER.debug("[%s] Got data: %s", transport, redacted)

    return pack


def _create_bind_pack(mac_addr_controller: str, uid: int, cipher: CipherBase) -> dict:
    """Create a bind request pack.

    Args:
        mac_addr: The MAC address of the device to bind with
        uid: User ID for the device
        cipher: Device cipher to encrypt and decrypt the JSON pack, if present

    Returns:
        The created Bind pack

    """

    pack: dict = {}

    if cipher.version == EncryptionVersion.V1:
        pack = {"t": GreeCommand.BIND.value, "uid": uid, "mac": mac_addr_controller}
    elif cipher.version == EncryptionVersion.V2:
        pack = {
            "t": GreeCommand.BIND.value,
            "uid": uid,
            "mac": mac_addr_controller,
            "cid": mac_addr_controller,
        }

    _LOGGER.debug("Bind Pack: %s", pack)
    return pack


def _create_get_subdevices_pack(mac_addr_controller: str) -> dict:
    """Create a sub-device list request pack.

    Args:
        mac_addr_controller: The MAC address of the device that controls the sub devices

    Returns:
        The created get sub-devices pack

    """

    pack: dict = {"mac": mac_addr_controller, "i": 1}

    _LOGGER.debug("Sub Bind Pack: %s", pack)
    return pack


def _create_get_status_pack(mac_addr: str, props: list[str]) -> dict:
    """Create a status request pack.

    Args:
        mac_addr: MAC address of the device to get the status of
        props: List of property names to query

    Returns:
        The created get status pack

    """

    pack: dict = {"t": GreeCommand.GET_STATE.value, "mac": mac_addr, "cols": props}

    _LOGGER.debug("Status Pack: %s", pack)
    return pack


def _create_set_status_pack(mac_addr: str, props: Mapping[str, int]) -> dict:
    """Create a command pack to update device properties.

    Args:
        mac_addr: MAC address of the device to set the status of
        props: Dictionary of property names and values to set

    Returns:
        The created set status pack

    """

    props_ordered = _order_set_props(dict(props))

    pack: dict = {
        "t": GreeCommand.SET_STATE.value,
        "sub": mac_addr,
        "opt": list(props_ordered.keys()),
        "p": list(props_ordered.values()),
    }

    _LOGGER.debug("Set Pack: %s", pack)
    return pack


def _order_set_props(props: dict[str, int]) -> dict[str, int]:
    """Reorder the props to match device requirements.

    The order of the props is important and required for devices, especially if the transport does not support batching.

    Args:
        props: Dictionary of property names and values to order

    Returns:
        Ordered dictionary of property names and values

    """

    # CRITICAL: Send Mode FIRST, then Temperature, then others, then Power LAST
    # This order is required for commercial/parent-child devices

    remaining = props.copy()
    ordered: dict[str, int] = {}

    if GreeProp.BEEPER.value in remaining:
        ordered[GreeProp.BEEPER.value] = remaining.pop(GreeProp.BEEPER.value)
    if GreeProp.BEEPER_NEW.value in remaining:
        ordered[GreeProp.BEEPER_NEW.value] = remaining.pop(GreeProp.BEEPER_NEW.value)

    # Mode first
    if GreeProp.OP_MODE.value in remaining:
        ordered[GreeProp.OP_MODE.value] = remaining.pop(GreeProp.OP_MODE.value)

    # Temperature-related properties
    for prop in (
        GreeProp.TARGET_TEMPERATURE_UNIT.value,
        GreeProp.TARGET_TEMPERATURE_BIT.value,
        GreeProp.TARGET_TEMPERATURE.value,
    ):
        if prop in remaining:
            ordered[prop] = remaining.pop(prop)

    # Power goes last
    power = remaining.pop(GreeProp.POWER.value, None)

    # Everything else
    ordered.update(remaining)

    if power is not None:
        ordered[GreeProp.POWER.value] = power

    return ordered


def _create_payload(
    pack: dict,
    payload_type: str,
    i: int,
    mac_addr_controller: str,
    uid: int,
) -> dict:
    """Create a protocol payload containing a pack.

    Args:
        pack: The Pack of the payload
        payload_type: Type of pack payload
        i: sequential increment number
        mac_addr_controller: The MAC address of the device that controls the sub devices
        uid: User ID for the device

    Returns:
        The created full payload

    """

    payload: dict[str, Any] = {
        "cid": "app",
        "i": i,
        "t": payload_type,
        "pack": pack,
        "tcid": mac_addr_controller,
        "uid": uid,
    }

    _LOGGER.debug("Payload: %s", payload)
    return payload


async def gree_try_bind(
    mac_addr_controller: str,
    uid: int,
    version: EncryptionVersion | None,
    key: str | None,
    transport: GreeBaseTransport,
) -> BindingInfo:
    """Bind to a controller device and determine the correct encryption settings.

    Attempts binding using the provided encryption version and/or key when
    available. If binding fails, falls back to the default encryption
    versions.

    Args:
        mac_addr_controller: The MAC address of the device that controls the sub devices
        uid: User ID for the device
        version: Encryption version for the given transport (Optional)
        key: Encryption key for the device (Optional)
        transport: Transport used to communicate with the device

    Returns:
        The encryption key and version accepted by the device.

    """

    ret_key: str = ""
    error: GreeError | None = GreeBindingError("Binding failed")

    has_version = version is not None
    has_key = key is not None and bool(key.strip())
    redacted_key = redact_str(key)

    ciphers: list[CipherBase] = []

    if has_version:
        ciphers.append(get_cipher(version))
        if has_key:
            _LOGGER.info(
                "[%s] Trying to perform binding. Prefer provided version (%s) and key (%s)",
                transport,
                version,
                redacted_key,
            )
        else:
            _LOGGER.info(
                "[%s] Trying to perform binding. Prefer provided version (%s) and generic key ",
                transport,
                version,
            )
    elif has_key:
        _LOGGER.info(
            "[%s] Trying to perform binding. Prefering provided key (%s)",
            transport,
            redacted_key,
        )
    else:
        _LOGGER.info(
            "[%s] Trying to perform binding. Testing both versions with generic keys",
            transport,
        )

    # Fallback to both default ciphers
    ciphers.append(get_cipher(EncryptionVersion.V1))
    ciphers.append(get_cipher(EncryptionVersion.V2))

    for cipher in ciphers:
        _LOGGER.debug(
            "[%s] Requesting bind to device with encryption key v%d",
            transport,
            cipher.version,
        )

        pack = _create_bind_pack(mac_addr_controller, uid, cipher)
        # encrypted_pack, tag = gree_encrypt_pack(pack, cipher)
        json_payload = _create_payload(pack, "pack", 1, mac_addr_controller, uid)

        try:
            result = await gree_get_response_pack(
                mac_addr_controller, json_payload, cipher, transport
            )

        except GreeError as err:
            _LOGGER.exception(
                "[%s] Error in bind request using encryption key with version %d",
                transport,
                cipher.version,
            )

            # In case we are testing multiple ciphers, don't raise,
            # just save the error so we can continue testing the other ciphers
            error = err
            continue

        else:
            ret_key = result.get("key", "")
            ret_key_redacted = redact_str(ret_key)
            if ret_key.strip() == "":
                raise GreeBindingError(
                    "Binding failed: Received empty encryption key from device"
                )

            if has_key and ret_key != key:
                _LOGGER.warning(
                    "[%s] Binding successful with different key. Using retrieved key. Expected '%s', got '%s'",
                    transport,
                    redacted_key,
                    ret_key_redacted,
                )

            if has_version and cipher.version != version:
                _LOGGER.warning(
                    "[%s] Binding successful with different version. Using retrieved version. Expected '%s', got '%s'",
                    transport,
                    version,
                    cipher.version,
                )

            _LOGGER.info(
                "[%s] Fetched encryption key %s with version %d",
                transport,
                ret_key_redacted,
                cipher.version,
            )

            return BindingInfo(
                encryption_key=ret_key, encryption_version=cipher.version
            )

    raise GreeBindingError(
        f"Binding failed: Unable to obtain valid encryption version and key pair for {mac_addr_controller} at {transport}"
    ) from error


EMPTY_PACK_OVERHEAD = len(
    json.dumps(_create_get_status_pack("XXXXXXXXXXXX", [""])).encode()
)


async def gree_get_status(
    mac_addr_controller: str,
    mac_addr: str,
    uid: int,
    prop_names: list[str],
    cipher: CipherBase,
    transport: GreeBaseTransport,
) -> StatusResult:
    """Retrieve the current values of the requested device properties.

    The Gree protocol provides best-effort responses, meaning requested
    properties may be omitted or returned without corresponding values.
    This makes it impossible to know in a batch where they are.
    Callers should therefore only batch properties known to be supported.

    Args:
        mac_addr_controller: The MAC address of the device that controls the connection
        mac_addr: MAC address of the device to get the status of.
        uid: User ID for the device
        prop_names: List of property names to query
        cipher: Device cipher to encrypt and decrypt the JSON pack, if present
        transport: Transport used to communicate with the device

    Returns:
        Mapping of property names to values, along with a list of
        properties that were not returned by the device.

    """

    _LOGGER.debug("[%s] Getting status for device '%s'", transport, mac_addr)

    # Filter empty, none and white spaces
    prop_names = [p for p in prop_names if p is not None and p.strip()]

    # Use a MAX_PACK_SIZE pack as a limit for the full request
    # UDP seems to break at a 1024 bytes encrypted pack (~760 unencrypted prop list)
    # MQTT seems to break at a 1000 bytes encrypted pack (~670 unencrypted prop list)
    # Use a lesser value as a safe option (512)
    # Since the device only responds to requests under 1024 bytes
    # here we divide the props in batches so that the request does not pass the limit
    batches: list[list[str]] = []
    current: list[str] = []
    current_size = EMPTY_PACK_OVERHEAD

    for prop in prop_names:
        prop_size = len(json.dumps([prop]).encode())

        if current_size + prop_size < MAX_PACK_SIZE:
            current.append(prop)
            current_size += prop_size
        else:
            if current:
                batches.append(current)

            current = [prop]
            current_size = EMPTY_PACK_OVERHEAD + prop_size

    if current:
        batches.append(current)

    if len(batches) > 1:
        _LOGGER.debug(
            "[%s] The requested props are more that what is allowed in one request. Divided into %d requests",
            transport,
            len(batches),
        )

    status: dict[str, str] = {}
    missing: list[str] = []

    try:
        for batched_props in batches:
            pack = _create_get_status_pack(mac_addr, batched_props)
            json_payload = _create_payload(pack, "pack", 0, mac_addr_controller, uid)
            result = await gree_get_response_pack(
                mac_addr_controller, json_payload, cipher, transport
            )
            res = gree_process_status_pack(result, batched_props)
            status.update(res.prop_values)
            missing.extend(res.missin_props)

    except GreeConnectionError, GreeProtocolError:
        raise

    except Exception as err:
        raise GreeProtocolError(
            f"Error getting status of device '{mac_addr}' via {transport}"
        ) from err

    return StatusResult(prop_values=status, missin_props=missing)


def gree_process_status_pack(pack: dict, props: list[str] | None) -> StatusResult:
    """Process a status pack.

    Args:
        pack: The raw unencrypted pack from a status request
        props: List of property names that should be in the status response (Optional)

    Returns:
        Mapping of property names to values, along with a list of
        properties that were not returned by the device.

    """
    # Gree protocol provides best-effort responses
    # Meaning:
    # cols = what the device claims it is returning
    # dat = best-effort values, possibly incomplete
    # alignment between them is not guaranteed globally

    cols = pack.get("cols")
    dat = pack.get("dat")

    if cols is None or dat is None:
        raise GreeProtocolError("No data received while getting device status")

    if len(cols) != len(dat):
        if len(cols) == 1:
            # if there is a single prop without value, add to missing
            _LOGGER.warning("Device queried for invalid prop: %s", cols)
            return StatusResult(prop_values={}, missin_props=cols)

        raise GreeProtocolError(f"Malformed response: cols={len(cols)} dat={len(dat)}")

    status_values: dict[str, str] = {}
    returned_props: set[str] = set()

    for prop, value in zip(cols, dat, strict=True):
        returned_props.add(prop)
        status_values[prop] = value

    invalid_props = []
    if props:
        invalid_props = [p for p in props if p not in returned_props]
        if len(invalid_props) > 0:
            _LOGGER.warning("Device queried for invalid props: %s", invalid_props)

    _LOGGER.debug("Got status for device: %s", status_values)
    return StatusResult(prop_values=status_values, missin_props=invalid_props)


async def gree_set_status(
    mac_addr_controller: str,
    mac_addr: str,
    uid: int,
    prop_values: Mapping[str, int],
    cipher: CipherBase,
    transport: GreeBaseTransport,
) -> Mapping[str, int]:
    """Update one or more device properties.

    Args:
        mac_addr_controller: The MAC address of the device that controls the connection
        mac_addr: MAC address of the device to set the status of.
        uid: User ID for the device
        prop_values: Dictionary of property names and values to set
        cipher: Device cipher to encrypt and decrypt the JSON pack, if present
        transport: Transport used to communicate with the device

    Returns:
        The property values acknowledged by the device, with no guarantee of them being the changed ones.
        Sometimes the return have them, sometimes don't or they actually miss props that were set successfully.

    """
    _LOGGER.debug("[%s] Trying to set device status", transport)

    pack = _create_set_status_pack(mac_addr, prop_values)
    json_payload = _create_payload(pack, "pack", 0, mac_addr_controller, uid)

    try:
        result = await gree_get_response_pack(
            mac_addr_controller, json_payload, cipher, transport
        )

    except GreeConnectionError, GreeProtocolError:
        raise

    except Exception as err:
        raise GreeProtocolError("Error getting device status") from err

    if (result_code := result.get("r")) != 200:
        raise GreeProtocolError(
            f"Error setting device status, response code: {result_code}"
        )

    # Gree protocol doesn't guarantee a return of {[opt]:[p]}
    # Sometimes the response have them, sometimes don't or they actually miss set props
    # As such, don't error/raise if that is the case
    # the fields bellow are optional
    options_set: list[str] = result.get("opt", [])
    values_set_1 = list(map(int, result.get("p", [])))
    values_set_2 = list(map(int, result.get("val", [])))  # If present, must match [p]

    # In case the response has nothing, but didn't had a error code
    # Assume all was set and return all given props
    if len(options_set) == 0:
        return prop_values

    if len(values_set_2) > 0 and len(values_set_1) != len(values_set_2):
        raise GreeProtocolError(
            f"Options and values set mismatch {options_set} {values_set_1}"
        )

    updated_props = dict(zip(options_set, values_set_1, strict=True))
    if updated_props != prop_values:
        _LOGGER.debug(
            "[%s] Expected updated props %s but got %s",
            transport,
            prop_values,
            updated_props,
        )

    return updated_props


async def _gree_get_scan(
    mac: str, transport: GreeBaseTransport, cipher: CipherBase | None = None
) -> dict[str, str | dict | None]:
    """Retrieve device information from a scan response."""

    pack: dict = await gree_get_response_pack(
        mac,
        {"t": GreeCommand.SCAN.value},
        cipher or get_cipher(EncryptionVersion.V1),
        transport,
    )

    _LOGGER.debug("Got device info: %s", pack)

    info: dict[str, str | dict | None] = {}
    info["raw"] = pack
    info["firmware_version"], info["firmware_code"] = extract_fw_version(
        pack.get("hid", "")
    )
    info["mac"] = pack.get("mac", "")
    info["subdevices_count"] = pack.get("subCnt", 0)
    return info


def extract_fw_version(hid: str) -> tuple[str | None, str | None]:
    """Extract the firmware version and code from device information.

    Args:
        hid: Hid field from a device status

    Returns:
        str: Firmware version
        str: Firmware code

    """
    ver_match = re.search(r"V([\d.]+)\.bin", hid)
    fw_version = str(ver_match.group(1)) if ver_match else None

    id_match = re.match(r"(\d+)", hid)  # leading digits
    fw_code = str(id_match.group(1)) if id_match else None

    return fw_version, fw_code


async def _get_sub_devices_list(
    mac_addr_controller: str,
    uid: int,
    cipher: CipherBase,
    transport: GreeUdpTransport,
    parent_device: GreeDiscoveredDevice | None = None,
    expected: int | None = None,
) -> list[GreeDiscoveredDevice]:
    """Retrieve the list of sub-devices exposed by a main controller device.

    Args:
        mac_addr_controller: The MAC address of the device that controls the connection
        uid: User ID for the device
        cipher: Device cipher to encrypt and decrypt the JSON pack, if present
        transport: Transport used to communicate with the device

    Returns:
        List of sub-devices directly from the controller response

    """

    _LOGGER.debug(
        "Retrieving subdevices for '%s' using '%s'", mac_addr_controller, transport
    )

    discovered_subdevices: list[GreeDiscoveredDevice] = []
    try:
        pack = _create_get_subdevices_pack(mac_addr_controller)

        json_payload = _create_payload(
            pack,
            "subList",
            1,
            mac_addr_controller,
            uid,
        )

        response = await gree_get_response_pack(
            mac_addr_controller, json_payload, cipher, transport
        )

    except Exception as err:
        raise GreeProtocolError(
            f"Error fetching sub-device list for '{mac_addr_controller}'"
        ) from err

    else:
        # Response in format:
        # {"t":"subList","i":0,"c":6,"r":200,"list":[{"mac":"09c4a41d000000","mid":"6049"},...]}
        sub_devs = response.get("list", [])
        if expected and (response.get("c") != expected or len(sub_devs) != expected):
            _LOGGER.warning(
                "[%s] Expected %d sub-devices and found %d",
                mac_addr_controller,
                expected,
                response.get("c"),
            )

        for sub_dev in sub_devs:
            new_dev: GreeDiscoveredDevice
            if parent_device:
                new_dev = replace(
                    parent_device,
                    mac=sub_dev.get("mac"),
                    mid=sub_dev.get("mid"),
                )
            else:
                new_dev = GreeDiscoveredDevice(
                    mac=sub_dev.get("mac"),
                    mac_controller=mac_addr_controller,
                    host=transport.ip_addr,
                    port=transport.port,
                    mid=sub_dev.get("mid"),
                )
            discovered_subdevices.append(new_dev)

        return discovered_subdevices


async def gree_discover_devices_local(
    broadcast_addresses: list[str], timeout: int, user_id: int
) -> list[GreeDiscoveredDevice]:
    """Discover Gree devices on the network.

    Args:
        broadcast_addresses: List of broadcast addresses to search
        timeout: Timeout (s) to wait for device responses
        user_id: User ID for the request

    Returns:
        List of the discovered devices

    """

    discovered_devices: list[GreeDiscoveredDevice] = []

    responses = await async_udp_broadcast_request(
        broadcast_addresses,
        DEFAULT_DEVICE_PORT,
        {"t": "scan"},
        timeout,
        get_cipher(EncryptionVersion.V1),
    )

    for address, response in responses.items():
        if response is not None:
            pack = response.get("pack")
            if pack is not None and pack.get("t") == "dev":
                device = DeviceScanInfoResponse.model_validate(pack)

                if not device.mac:
                    _LOGGER.debug("No MAC address in response from %s", address)
                    continue

                mac, mac_controller = gree_extract_macs(device.mac)

                discovered_device = GreeDiscoveredDevice(
                    mac=mac,
                    mac_controller=mac_controller,
                    host=address,
                    port=DEFAULT_DEVICE_PORT,
                    name=device.name or "",
                    catalog=device.catalog or "",
                    brand=device.brand or "gree",
                    model=device.model or "gree",
                    model_type=device.ModelType or "",
                    vender=device.vender or "",
                    mid=device.mid or "",
                    hid=device.hid or "",
                    ver=device.ver or "",
                )
                discovered_devices.append(discovered_device)

                if device.subCnt and device.subCnt > 0:
                    # TODO: Ingest subdevices, need debugging. Is the device above also added, or only sub_devices?
                    transport = GreeUdpTransport(address, DEFAULT_DEVICE_PORT)
                    sub_devices = await _get_sub_devices_list(
                        mac_controller,
                        user_id,
                        get_cipher(EncryptionVersion.V1),
                        transport,
                        discovered_device,
                        device.subCnt,
                    )
                    discovered_devices.extend(sub_devices)

    _LOGGER.info("Found total of %d local devices", len(discovered_devices))
    return discovered_devices


async def gree_discover_devices_cloud(
    cloud_api: GreeCloudApi,
) -> list[GreeDiscoveredDevice]:
    """Discover Gree devices on the Gree API.

    Args:
        cloud_api: The cloud API endpoint to get the devices from

    Returns:
        List of the discovered devices

    """
    discovered_devices: list[GreeDiscoveredDevice] = []

    responses = await cloud_api.get_all_devices()

    for dev in responses:
        mac, mac_controller = gree_extract_macs(dev.mac)
        discovered_devices.append(
            GreeDiscoveredDevice(
                mac=mac,
                mac_controller=mac_controller,
                user_id=cloud_api.user_id or DEFAULT_DEVICE_USERID,
                key=dev.key,
                username=cloud_api.username,
                name=dev.name,
                catalog=dev.catalog,
                brand=dev.brand,
                model=dev.prodModel,
                model_type=dev.subdivCode,
                vender=dev.vender,
                mid=dev.mid,
                hid=dev.hid,
                ver=dev.ver,
            )
        )
    return discovered_devices


async def gree_discover_devices(
    cloud_api: GreeCloudApi | None,
    broadcast_addresses: list[str] | None,
    timeout: int = 3,
) -> list[GreeDiscoveredDevice]:
    """Discover Gree Devices.

    Args:
        cloud_api: The cloud API endpoint to get the devices from (Optional)
        broadcast_addresses: List of broadcast addresses to search (Optional)
        timeout: Timeout (s) to wait for device responses

    Returns:
        De-duplicated list of discovered devices.

    """
    cloud_devices: list[GreeDiscoveredDevice] = []
    local_devices: list[GreeDiscoveredDevice] = []

    if cloud_api:
        cloud_devices = await gree_discover_devices_cloud(cloud_api)
        for dev in cloud_devices:
            _LOGGER.debug(repr(dev))

    if broadcast_addresses:
        local_devices = await gree_discover_devices_local(
            broadcast_addresses,
            timeout,
            cloud_api.user_id if cloud_api and cloud_api.user_id else 0,
        )

        for dev in local_devices:
            _LOGGER.debug(repr(dev))

    if len(cloud_devices) > 0 or len(local_devices) > 0:
        return _merge_discovered_devices(local_devices, cloud_devices)

    return []


def _merge_discovered_devices(
    local_devices: list[GreeDiscoveredDevice],
    cloud_devices: list[GreeDiscoveredDevice],
) -> list[GreeDiscoveredDevice]:
    """Merge local and cloud discovered devices in a single concise list."""
    local_map = {d.mac: d for d in local_devices}
    cloud_map = {d.mac: d for d in cloud_devices}

    merged = []

    for mac in sorted(local_map.keys() | cloud_map.keys()):
        local = local_map.get(mac)
        cloud = cloud_map.get(mac)

        # Exists only locally
        if cloud is None and local:
            merged.append(local)
            continue

        # Exists only in cloud
        if local is None and cloud:
            merged.append(cloud)
            continue

        # Start with cloud values
        merged_device = GreeDiscoveredDevice(**vars(cloud))

        # Override with non-empty local values
        # So that local info overrides cloud, especially for MAC
        for field in fields(GreeDiscoveredDevice):
            value = getattr(local, field.name)

            if value is None:
                continue

            if isinstance(value, str) and value == "":
                continue

            setattr(merged_device, field.name, value)

        merged.append(merged_device)

    _LOGGER.debug("Merged devices: %d", len(merged))

    return merged
