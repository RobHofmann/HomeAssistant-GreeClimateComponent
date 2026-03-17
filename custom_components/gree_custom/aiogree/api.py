"""Contains the API to interface with the Gree device."""

from enum import Enum, IntEnum, unique
import json
import logging
import re
from typing import Any

from attr import dataclass

from .cipher import CipherBase, EncryptionVersion, get_cipher
from .const import DEFAULT_DEVICE_PORT
from .errors import GreeBindingError, GreeError, GreeProtocolError
from .transport import GreeTransport, async_udp_broadcast_request

_LOGGER = logging.getLogger(__name__)


class GreeProp(Enum):
    """Enumeration of Gree device properties."""

    # HVAC CONTROLS
    # power state of the device
    POWER = "Pow"
    # mode of operation
    OP_MODE = "Mod"
    # fan speed mode
    FAN_SPEED = "WdSpd"
    # target temperature
    TARGET_TEMPERATURE = "SetTem"
    # used to distinguish between Fahrenheit values
    TARGET_TEMPERATURE_BIT = "TemRec"
    # defines the unit of temperature for the target temperature
    TARGET_TEMPERATURE_UNIT = "TemUn"
    # the swing mode of the horizontal air blades (available on limited number of devices)
    SWING_HORIZONTAL = "SwingLfRig"
    # the swing mode of the vertical air blades
    SWING_VERTICAL = "SwUpDn"
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
    # sleep mode, which gradually changes the temperature in Cool, Heat and Dry mode
    FEAT_SLEEP_MODE_SWING = "SwhSlp"
    FEAT_SLEEP_MODE = "SlpMod"
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

    # OTHER
    _UNKNOWN_HEAT_COOL_TYPE = "HeatCoolType"
    # If set to 0 the unit will beep on every command
    BEEPER = "Buzzer_ON_OFF"
    # If set to 1 the unit will beep on every command (available on newer firmwares)
    BEEPER_NEW = "BuzzerCtrl"


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


propkey_to_enum = {prop.value: prop for prop in GreeProp}


async def get_result_pack(
    json_data: dict, cipher: CipherBase, transport: GreeTransport
) -> dict:
    """Get the result pack from the device (async)."""

    try:
        recv_json = await transport.request_json(json_data)
    except json.JSONDecodeError as err:
        raise GreeProtocolError("Invalid JSON response from device") from err

    data = get_gree_response_data(recv_json, cipher)

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

            _LOGGER.debug("Fetched encryption key: %s[omitted]", ret_key[:5])

            return ret_key, cipher.version

    raise GreeBindingError(
        f"Binding failed: Unable to obtain valid encryption version and key pair for {mac_addr} at {transport.ip_addr}"
    ) from error


async def gree_get_status(
    mac_addr: str,
    mac_addr_sub: str,
    uid: int,
    props: list[GreeProp],
    cipher: CipherBase,
    transport: GreeTransport,
) -> tuple[dict[GreeProp, int], list[GreeProp]]:
    """Get the status of the device by sending a status request to the device (async). Also returns the props not present."""

    _LOGGER.debug("Trying to get device status")

    status_values_raw: dict[GreeProp, int | None] = {}

    pack = gree_create_status_pack(mac_addr_sub, [prop.value for prop in props])
    encrypted_pack, tag = gree_encrypt_pack(pack, cipher)
    json_payload = gree_create_payload(
        encrypted_pack, "pack", GreeCommand.STATUS, mac_addr, uid, tag
    )

    try:
        result = await get_result_pack(json_payload, cipher, transport)

    except GreeProtocolError:
        raise

    except Exception as err:
        raise GreeProtocolError("Error getting device status") from err

    if result["cols"] is None or result["dat"] is None:
        raise GreeProtocolError("No data received while getting device status")

    cols = [propkey_to_enum[c] for c in result["cols"] if c in propkey_to_enum]
    values = [int(x) if x != "" else None for x in result["dat"]]
    status_values_raw = dict(zip(cols, values, strict=True))

    status_values = {k: v for k, v in status_values_raw.items() if v is not None}
    _LOGGER.debug("Device status values: %s", status_values)

    return status_values, [p for p in props if p not in status_values]


async def gree_set_status(
    mac_addr: str,
    mac_addr_sub: str,
    uid: int,
    props: dict[GreeProp, int],
    cipher: CipherBase,
    transport: GreeTransport,
) -> dict[GreeProp, int]:
    """Set the status of the device by sending a status request to the device (async)."""

    _LOGGER.debug("Trying to set device status")

    pack = gree_create_set_pack(mac_addr_sub, props)
    encrypted_pack, tag = gree_encrypt_pack(pack, cipher)
    json_payload = gree_create_payload(
        encrypted_pack, "pack", GreeCommand.STATUS, mac_addr, uid, tag
    )

    try:
        result = await get_result_pack(json_payload, cipher, transport)

    except GreeProtocolError:
        raise

    except Exception as err:
        raise GreeProtocolError("Error getting device status") from err

    if result["r"] is None or result["r"] != 200:
        raise GreeProtocolError(
            f"Error setting device status, response code: {result['r']}"
        )

    options_set = [propkey_to_enum[c] for c in result["opt"] if c in propkey_to_enum]
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


async def gree_get_device_info(transport: GreeTransport) -> dict[str, str | None]:
    """Tries to retrive the device info."""

    data: dict = await get_result_pack(
        {"t": "scan"},
        get_cipher(EncryptionVersion.V1),
        transport,
    )

    _LOGGER.debug("Got device info: %s", data)

    info: dict[str, str | None] = {}
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
