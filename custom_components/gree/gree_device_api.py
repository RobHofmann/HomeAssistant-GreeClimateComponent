"""Gree device API logic for Home Assistant integration."""

# Standard library imports
import base64
import logging
import socket

# Third-party imports
try:
    import simplejson
except ImportError:
    import json as simplejson
from Crypto.Cipher import AES

from .const import *
from .old_helpers import TempOffsetResolver

_LOGGER = logging.getLogger(__name__)

GCM_IV = b"\x54\x40\x78\x44\x49\x67\x5a\x51\x6c\x5e\x63\x13"
GCM_ADD = b"qualcomm-test"
GENERIC_GREE_DEVICE_KEY = "a3K8Bx%2r8Y7#xDh"
GENERIC_GREE_DEVICE_KEY_GCM = "{yxAHAY_Lm6pbC/<"

AC_OPTIONS_ALL = [
    "Pow",
    "Mod",
    "SetTem",
    "WdSpd",
    "Air",
    "Blo",
    "Health",
    "SwhSlp",
    "Lig",
    "SwingLfRig",
    "SwUpDn",
    "Quiet",
    "Tur",
    "StHt",
    "TemUn",
    "HeatCoolType",
    "TemRec",
    "SvSt",
    "SlpMod",
    "TemSen",
    "AntiDirectBlow",
    "LigSen",
]

AC_OPTIONS_MAPPING = {
    # power state of the device
    "Pow": {0: "off", 1: "on"},
    # mode of operation
    "Mod": {
        0: "auto",
        1: "cool",
        2: "dry",
        3: "fan",
        4: "heat",
    },
    # fan speed
    "WdSpd": {
        0: "auto",
        1: "low",
        2: "medium-low",  # not available on 3-speed units
        3: "medium",
        4: "medium-high",  # not available on 3-speed units
        5: "high",
    },
    # controls the state of the fresh air valve (not available on all units)
    "Air": {0: "off", 1: "on"},
    # "Blow" or "X-Fan", this function keeps the fan running for a while after shutting down. Only usable in Dry and Cool mode
    "Blo": {0: "off", 1: "on"},
    # controls Health ("Cold plasma") mode, only for devices equipped with "anion generator", which absorbs dust and kills bacteria
    "Health": {0: "off", 1: "on"},
    # sleep mode, which gradually changes the temperature in Cool, Heat and Dry mode
    "SwhSlp": {0: "off", 1: "on"},
    "SlpMod": {0: "off", 1: "on"},
    # turns all indicators and the display on the unit on or off
    "Lig": {0: "off", 1: "on"},
    # controls the swing mode of the horizontal air blades (available on limited number of devices)
    "SwingLfRig": {
        0: "default",
        1: "swing_full",
        2: "fixed_leftmost",
        3: "fixed_middle_left",
        4: "fixed_middle",
        5: "fixed_middle_right",
        6: "fixed_rightmost",
    },
    # controls the swing mode of the vertical air blades
    "SwUpDn": {
        0: "default",
        1: "swing_full",
        2: "fixed_upmost",
        3: "fixed_middle_up",
        4: "fixed_middle",
        5: "fixed_middle_low",
        6: "fixed_lowest",
        7: "swing_downmost",
        8: "swing_middle_low",
        9: "swing_middle",
        10: "swing_middle_up",
        11: "swing_upmost",
    },
    # controls the Quiet mode which slows down the fan to its most quiet speed. Not available in Dry and Fan mode.
    "Quiet": {0: "off", 1: "on"},
    # sets fan speed to the maximum. Fan speed cannot be changed while active and only available in Dry and Cool mode
    "Tur": {0: "off", 1: "on"},
    # maintain the room temperature steadily at 8°C and prevent the room from freezing by heating operation when nobody is at home for long in severe winter
    "StHt": {0: "off", 1: "on"},
    # used to distinguish between Fahrenheit values
    "TemRec": {0: "low", 1: "high"},
    # energy saving mode
    "SvSt": {0: "off", 1: "on"},
    # defines the unit of temperature
    "TemUn": {0: "celcius", 1: "fahrenheit"},
    # unknown function
    "AntiDirectBlow": {0: "off", 1: "on"},
    # controls if the light sensor is used (available on limited number of devices)
    "LigSen": {0: "off", 1: "on"},
}


def Pad(s: str):
    """Pads a string so its length becomes a multiple of 16. For PKCS#7 padding."""
    aesBlockSize = 16
    requiredPaddingSize = aesBlockSize - len(s) % aesBlockSize
    return s + requiredPaddingSize * chr(requiredPaddingSize)


def FetchResult(ip_addr, port, timeout, json_data, cipher, encryption_version=1):
    """Sends a payload JSON data to the device and reads the response pack."""

    _LOGGER.debug(
        "Fetching data from %s with requested payload: %s", ip_addr, json_data
    )

    clientSock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    clientSock.settimeout(timeout)
    clientSock.sendto(bytes(json_data, "utf-8"), (ip_addr, port))

    data, _ = clientSock.recvfrom(64000)
    receivedJson = simplejson.loads(data)
    clientSock.close()

    pack = receivedJson["pack"]
    base64decodedPack = base64.b64decode(pack)
    decryptedPack = cipher.decrypt(base64decodedPack)

    if encryption_version == 2:
        tag = receivedJson["tag"]
        cipher.verify(base64.b64decode(tag))

    decodedPack = decryptedPack.decode("utf-8")
    replacedPack = decodedPack.replace("\x0f", "").replace(
        decodedPack[decodedPack.rindex("}") + 1 :], ""
    )
    loadedJsonPack = simplejson.loads(replacedPack)

    _LOGGER.debug(f"Got data from {ip_addr} with: {loadedJsonPack}")
    return loadedJsonPack


def GetCipher(key: str, encryption_version: int):
    # _LOGGER.debug(f"Version: {encryption_version}, Key: {key}, Key Length: {len(key)}")
    if encryption_version == 1:
        cipher = AES.new(key.encode("utf8"), AES.MODE_ECB)
        return cipher
    elif encryption_version == 2:
        cipher = AES.new(key.encode("utf8"), AES.MODE_GCM, nonce=GCM_IV)
        cipher.update(assoc_data=GCM_ADD)
        return cipher


def GetDefaultCipher(encryption_version: int):
    if encryption_version == 1:
        cipher = GetCipher(GENERIC_GREE_DEVICE_KEY, encryption_version)
        return cipher
    elif encryption_version == 2:
        cipher = GetCipher(GENERIC_GREE_DEVICE_KEY_GCM, encryption_version)
        return cipher
    else:
        _LOGGER.error(f"Unsupported encryption version: {encryption_version}")
        return None


def CreateEncryptedPack(data: str, cipher, encryption_version: int) -> tuple[str, str]:
    if encryption_version == 1:
        encrypted_data = cipher.encrypt(Pad(data).encode("utf8"))
        return (
            base64.b64encode(encrypted_data).decode("utf-8"),
            "",
        )
    elif encryption_version == 2:
        encrypted_data, tag = cipher.encrypt_and_digest(data.encode("utf8"))
        return (
            base64.b64encode(encrypted_data).decode("utf-8"),
            base64.b64encode(tag).decode("utf-8"),
        )
    else:
        return ("", "")


def CreateBindPack(mac_addr: str, uid: int, encryption_version: int) -> str:
    pack = ""
    if encryption_version == 1:
        pack = simplejson.dumps({"mac": mac_addr, "t": "bind", "uid": uid})
    elif encryption_version == 2:
        pack = simplejson.dumps(
            {"cid": mac_addr, "mac": mac_addr, "t": "bind", "uid": uid}
        )

    _LOGGER.debug(f"Bind Pack: {pack}")
    return pack


def CreateStatusPak(mac_addr: str) -> str:
    pack = simplejson.dumps({"cols": AC_OPTIONS_ALL, "mac": mac_addr, "t": "status"})
    _LOGGER.debug(f"Status Pack: {pack}")
    return pack


def CreatePayload(
    pack: str,
    i_command: int,
    mac_addr: str,
    uid: int,
    encryption_version: int,
    tag: str,
):
    payload: str = ""
    if encryption_version == 1:
        payload = simplejson.dumps(
            {
                "cid": "app",
                "i": i_command,
                "pack": pack,
                "t": "pack",
                "tcid": mac_addr,
                "uid": uid,
            }
        )
    elif encryption_version == 2:
        payload = simplejson.dumps(
            {
                "cid": "app",
                "i": i_command,
                "pack": pack,
                "t": "pack",
                "tcid": mac_addr,
                "uid": uid,
                "tag": tag,
            }
        )

    _LOGGER.debug(f"Payload: {payload}")
    return payload


def GetFahrenheitValueToSend(fahrenheit: int) -> tuple[int, int]:
    TemSet = round((fahrenheit - 32.0) * 5.0 / 9.0)
    TemRec = (int)((((fahrenheit - 32.0) * 5.0 / 9.0) - TemSet) > 0)
    return (TemSet, TemRec)


class GreeDeviceAPI:
    def __init__(
        self,
        ip_addr: str,
        mac_addr: str,
        port: int = DEFAULT_PORT,
        timeout: int = DEFAULT_TIMEOUT,
        encryption_version: int = 1,
        encryption_key: str = "",
        uid: int = 0,
        temp_offset=TEMSEN_OFFSET,
    ):
        _LOGGER.info(
            f"Initialize the GREE Device API for: {mac_addr} ({ip_addr}:{port})"
        )
        _LOGGER.debug(f"Version: {encryption_version}, Key: {encryption_key}")

        self.ip_addr: str = ip_addr
        self.port: int = port
        self.mac_addr: str = mac_addr
        self.timeout: int = timeout
        self.encryption_version: int = encryption_version
        self.encryption_key: str = encryption_key
        self.uid: int = uid

        if encryption_version < 1 or encryption_version > 2:
            _LOGGER.error("Unsupported encryption version, defaulting to 1")
            self.encryption_version = 1

        if not encryption_key.strip():
            _LOGGER.info("No encryption key provided")
            self.GetDeviceKey()

        self.temp_processor = TempOffsetResolver(offset=temp_offset)

        self.GetDeviceStatus()

    def GetDeviceKey(self) -> str:
        _LOGGER.info("Trying to retrieve device encryption key")

        self.encryption_key = ""

        pack, tag = CreateEncryptedPack(
            CreateBindPack(self.mac_addr, self.uid, self.encryption_version),
            GetDefaultCipher(self.encryption_version),
            self.encryption_version,
        )
        jsonPayloadToSend = CreatePayload(
            pack, 1, self.mac_addr, self.uid, self.encryption_version, tag
        )

        try:
            key = FetchResult(
                self.ip_addr,
                self.port,
                self.timeout,
                jsonPayloadToSend,
                GetDefaultCipher(self.encryption_version),
                self.encryption_version,
            )["key"]
        except Exception:
            _LOGGER.exception("Error getting device encryption key")
        else:
            _LOGGER.info("Fetched device encryption key with success")
            _LOGGER.debug(f"Fetched encryption key: {key}")
            self.encryption_key = key

        return self.encryption_key

    def GetDeviceStatus(self) -> dict[str, int]:
        _LOGGER.debug("Trying to get device status")

        pack, tag = CreateEncryptedPack(
            CreateStatusPak(self.mac_addr),
            GetCipher(self.encryption_key, self.encryption_version),
            self.encryption_version,
        )
        jsonPayloadToSend = CreatePayload(
            pack, 0, self.mac_addr, self.uid, self.encryption_version, tag
        )

        self.status_values: dict[str, int] = {}

        try:
            result = FetchResult(
                self.ip_addr,
                self.port,
                self.timeout,
                jsonPayloadToSend,
                GetCipher(self.encryption_key, self.encryption_version),
                self.encryption_version,
            )
            cols = list(map(str, result["cols"]))
            values = list(map(int, result["dat"]))
            status_values = dict(zip(cols, values))
        except Exception:
            _LOGGER.error("Error getting device status")
        else:
            _LOGGER.debug(f"Fetched device status: {status_values}")
            self.device_status = status_values

        # Update variables
        self.has_temp_sensor = (
            "TemSen" in self.device_status and self.device_status["TemSen"] != 0
        )
        if self.has_temp_sensor and self.temp_processor is None:
            self.temp_processor(self.device_status["TemSen"])

        self.temperature_unit = AC_OPTIONS_MAPPING["TemUn"][self.device_status["TemUn"]]

        return self.device_status
