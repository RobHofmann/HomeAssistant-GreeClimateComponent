"""Contains the API to interface with the Gree device."""

import asyncio
import base64
from enum import Enum, IntEnum, unique
import json
import logging
import re
import socket
import time
from typing import Any

import asyncio_dgram
from attr import dataclass
from Crypto.Cipher import AES

_LOGGER = logging.getLogger(__name__)

GCM_IV = b"\x54\x40\x78\x44\x49\x67\x5a\x51\x6c\x5e\x63\x13"
GCM_ADD = b"qualcomm-test"

GREE_GENERIC_DEVICE_KEY = "a3K8Bx%2r8Y7#xDh"
GREE_GENERIC_DEVICE_KEY_GCM = "{yxAHAY_Lm6pbC/<"

MIN_TEMP_C = 16
MAX_TEMP_C = 30

MIN_TEMP_F = 61
MAX_TEMP_F = 86

DEFAULT_DEVICE_UID = 0
DEFAULT_DEVICE_PORT = 7000
DEFAULT_CONNECTION_MAX_ATTEMPTS = 5
DEFAULT_CONNECTION_TIMEOUT = 10


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


@unique
class EncryptionVersion(IntEnum):
    """Available encryption versions for the device."""

    V1 = 1
    V2 = 2


@unique
class TemperatureUnits(IntEnum):
    """Enumeration of temperature units."""

    C = 0
    F = 1


@unique
class OperationMode(IntEnum):
    """Enumeration of HVAC modes."""

    Auto = 0
    Cool = 1
    Dry = 2
    Fan = 3
    Heat = 4


@unique
class FanSpeed(IntEnum):
    """Enumeration of fan speeds."""

    Auto = 0
    Low = 1
    MediumLow = 2
    Medium = 3
    MediumHigh = 4
    High = 5


@unique
class HorizontalSwingMode(IntEnum):
    """Enumeration of horizontal swing modes."""

    Default = 0
    FullSwing = 1
    Left = 2
    LeftCenter = 3
    Center = 4
    RightCenter = 5
    Right = 6


@unique
class VerticalSwingMode(IntEnum):
    """Enumeration of vertical swing modes."""

    Default = 0
    FullSwing = 1
    FixedUpper = 2
    FixedUpperMiddle = 3
    FixedMiddle = 4
    FixedLowerMiddle = 5
    FixedLower = 6
    SwingUpper = 7
    SwingUpperMiddle = 8
    SwingMiddle = 9
    SwingLowerMiddle = 10
    SwingLower = 11


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


propkey_to_enum = {prop.value: prop for prop in GreeProp}


def pad(s: str):
    """Pads a string so its length becomes a multiple of 16. For PKCS#7 padding."""
    aesBlockSize = 16
    requiredPaddingSize = aesBlockSize - len(s) % aesBlockSize
    return s + requiredPaddingSize * chr(requiredPaddingSize)


def udp_broadcast_request(
    addresses: list[str], port: int, json_data: str, timeout: int
):
    """Sends a UDP message to the bradcast address and returns the responses."""
    # Create UDP socket manually so we can enable broadcast
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(timeout)
    sock.bind(("", 0))

    responses: dict = {}

    # Default broadcast addresses to try
    default_broadcast_addresses = [
        "255.255.255.255",  # Limited broadcast
        "192.168.255.255",  # /16 broadcast for 192.168.x.x networks
        "10.255.255.255",  # /8 broadcast for 10.x.x.x networks
        "172.31.255.255",  # /12 broadcast for 172.16-31.x.x networks
    ]
    addresses.extend(default_broadcast_addresses)

    # Remove duplicates
    broadcast_addresses = list(dict.fromkeys(addresses))

    try:
        for broadcast_addr in broadcast_addresses:
            try:
                _LOGGER.debug("Sending broadcast to %s", broadcast_addr)
                sock.sendto(json_data.encode("utf-8"), (broadcast_addr, port))
            except Exception:
                _LOGGER.exception("Failed to send to %s", broadcast_addr)

        # Send broadcast
        _LOGGER.debug("Sent broadcast packets, waiting for replies... ")

        start_time: float = time.time()
        while time.time() - start_time < timeout:
            try:
                response, addr = sock.recvfrom(1024)

                try:
                    response = response.decode(errors="ignore")
                except Exception:
                    _LOGGER.exception("Could not parse response from %s", addr)
                else:
                    responses[addr[0]] = response
            except TimeoutError:
                break
    except Exception:
        _LOGGER.exception("Error sending broadcast packet")
    finally:
        sock.close()

    _LOGGER.debug(
        "Got %d responses in %d seconds: %s", len(responses), timeout, responses
    )
    return responses


async def udp_request_async(
    ip_addr: str,
    port: int,
    json_data: str,
    max_retries: int,
    timeout: int,
) -> str:
    """Send a payload JSON data to the device and reads the response (async)."""
    # _LOGGER.info(
    #     "%s:%d max_r=%d t=%d json:\n%s", ip_addr, port, max_retries, timeout, json_data
    # )

    for attempt in range(max_retries):
        stream: asyncio_dgram.DatagramClient | None = None
        try:
            stream = await asyncio_dgram.connect((ip_addr, port))
            await stream.send(json_data.encode("utf-8"))
            received_json, _ = await asyncio.wait_for(stream.recv(), timeout)
            return received_json.decode("utf-8")
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning(
                "Error communicating with %s. Attempt %d/%d | %s",
                ip_addr,
                attempt + 1,
                max_retries,
                repr(err),
            )
            # raise ValueError(f"Error communicating with {ip_addr}", ip_addr) from err
        finally:
            if stream:
                try:
                    stream.close()
                except Exception as cerr:  # noqa: BLE001
                    _LOGGER.warning(
                        "Error communicating with %s. Attempt %d/%d | %s",
                        ip_addr,
                        attempt + 1,
                        max_retries,
                        repr(cerr),
                    )

        # Apply backoff before retrying
        if attempt < max_retries - 1:
            backoff = 0.5 + attempt * 0.3  # 0.5s, 0.8s, 1.1s, ...
            await asyncio.sleep(backoff)

    raise ValueError(
        f"Failed to communicate with device '{ip_addr}:{port}' after {max_retries} attempts"
    )


async def udp_request_blocking(
    ip_addr: str, port: int, json_data: str, max_retries: int, timeout: int
) -> str:
    """Send a payload JSON data to the device and reads the response (blocking)."""
    _LOGGER.debug("Fetching(%s, %s, %s, %s)", ip_addr, port, timeout, json_data)

    for attempt in range(max_retries):
        clientSock = None

        try:
            clientSock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            clientSock.settimeout(timeout)

            clientSock.sendto(bytes(json_data, "utf-8"), (ip_addr, port))

            data, _ = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None, clientSock.recvfrom, 64000
                ),
                timeout=timeout,
            )

            return data.decode("utf-8")

        except Exception:  # noqa: BLE001
            _LOGGER.warning(
                "Error communicating with %s. Attempt %d/%d",
                ip_addr,
                attempt + 1,
                max_retries,
            )

        finally:
            if clientSock:
                try:
                    clientSock.close()
                except Exception:  # noqa: BLE001
                    _LOGGER.error("Error closing socket to %s", ip_addr)

        if attempt < max_retries - 1:
            await asyncio.sleep(
                0.5 * (attempt * 0.3)
            )  # 0.5s, 0.8s, 1.1s, 1.4s, 1.7s, 2.0s, 2.3s

    raise ValueError(
        f"Failed to communicate with device '{ip_addr}' after multiple attempts"
    )


async def fetch_result(
    ip_addr: str,
    port: int,
    json_data: str,
    cipher,
    encryption_version: EncryptionVersion,
    max_connection_attempts: int,
    timeout: int,
):
    """Send a payload JSON data to the device and reads the response (async)."""

    _LOGGER.debug("Fetching data from %s", ip_addr)

    received_json: str = ""

    try:
        received_json = await udp_request_async(
            ip_addr, port, json_data, max_connection_attempts, timeout
        )
    except Exception as err:
        raise ValueError(f"Error communicating with {ip_addr}: {err}") from err

    # try:
    #     received_json = await udp_request_blocking(ip_addr, port, json_data)
    # except Exception as err:
    #     raise ValueError(f"Error communicating with {ip_addr}", ip_addr) from err

    data = get_gree_response_data(received_json, cipher, encryption_version)

    _LOGGER.debug("Got data from %s: %s", ip_addr, data)

    return data


def get_gree_response_data(
    received_json: str,
    cipher,
    encryption_version: EncryptionVersion,
):
    """Decodes a response from a gree device."""
    data = json.loads(received_json)

    encodedPack = data.get("pack")
    if encodedPack:
        pack = base64.b64decode(encodedPack)
        decryptedPack = cipher.decrypt(pack)
        _LOGGER.debug("Decoding pack: %s", decryptedPack)
        pack = decryptedPack.decode("utf-8")
        replacedPack = pack.replace("\x0f", "").replace(
            pack[pack.rindex("}") + 1 :], ""
        )
        data["pack"] = json.loads(replacedPack)

    if encryption_version == EncryptionVersion.V2:
        tag = data["tag"]
        _LOGGER.debug("Verifying tag: %s", tag)
        cipher.verify(base64.b64decode(tag))

    return data


async def get_result_pack(
    ip_addr: str,
    port: int,
    json_data: str,
    cipher,
    encryption_version: EncryptionVersion,
    max_connection_attempts: int,
    timeout: int,
):
    """Get the result pack from the device (async)."""

    data = await fetch_result(
        ip_addr,
        port,
        json_data,
        cipher,
        encryption_version,
        max_connection_attempts,
        timeout,
    )

    if data is not None and data["pack"] is not None:
        return data["pack"]

    raise ValueError("No pack received from device")


def get_cipher(key: str, encryption_version: EncryptionVersion):
    """Get AES cipher object based on encryption version."""

    if encryption_version == EncryptionVersion.V1:
        return AES.new(key.encode("utf8"), AES.MODE_ECB)

    if encryption_version == EncryptionVersion.V2:
        return AES.new(key.encode("utf8"), AES.MODE_GCM, nonce=GCM_IV).update(
            assoc_data=GCM_ADD
        )

    _LOGGER.error("Unsupported encryption version: %d", encryption_version)
    return None


def gree_get_default_cipher(encryption_version: EncryptionVersion):
    """Get AES cipher object based on encryption version using default keys."""

    if encryption_version == EncryptionVersion.V1:
        return get_cipher(GREE_GENERIC_DEVICE_KEY, encryption_version)

    if encryption_version == EncryptionVersion.V2:
        return get_cipher(GREE_GENERIC_DEVICE_KEY_GCM, encryption_version)

    _LOGGER.error("Unsupported encryption version: %d", encryption_version)
    return None


def gree_create_encrypted_pack(
    data: str,
    cipher,
    encryption_version: EncryptionVersion,
) -> tuple[str, str]:
    """Create an encrypted pack to send to the device."""

    if cipher is None:
        raise ValueError("Cipher must not be None")

    if encryption_version == EncryptionVersion.V1:
        encrypted_data = cipher.encrypt(pad(data).encode("utf-8"))
        return (
            base64.b64encode(encrypted_data).decode("utf-8"),
            "",
        )

    if encryption_version == EncryptionVersion.V2:
        encrypted_data, tag = cipher.encrypt_and_digest(data.encode("utf-8"))
        return (
            base64.b64encode(encrypted_data).decode("utf-8"),
            base64.b64encode(tag).decode("utf-8"),
        )

    raise ValueError(f"Unsupported encryption version: {encryption_version}")


def gree_create_bind_pack(
    mac_addr: str, uid: int, encryption_version: EncryptionVersion
) -> str:
    """Create a bind pack to send to the device."""

    pack: str = ""

    if encryption_version == EncryptionVersion.V1:
        pack = json.dumps({"mac": mac_addr, "t": "bind", "uid": uid})
    elif encryption_version == EncryptionVersion.V2:
        pack = json.dumps({"cid": mac_addr, "mac": mac_addr, "t": "bind", "uid": uid})

    _LOGGER.debug("Bind Pack: %s", pack)
    return pack


def gree_create_sub_bind_pack(mac_addr: str) -> str:
    """Create a bind pack to send to the device."""

    pack: str = json.dumps({"mac": mac_addr, "i": 1})

    _LOGGER.debug("Sub Bind Pack: %s", pack)
    return pack


def gree_create_status_pack(mac_addr: str, props: list[str]) -> str:
    """Create a status pack to send to the device."""

    pack: str = json.dumps({"cols": props, "mac": mac_addr, "t": "status"})

    _LOGGER.debug("Status Pack: %s", pack)
    return pack


def gree_create_set_pack(mac_addr: str, props: dict[GreeProp, int]) -> str:
    """Create a set pack to send to the device."""

    pack: str = json.dumps(
        {
            "opt": [prop.value for prop in props],
            "p": list(props.values()),
            "t": "cmd",
            "sub": mac_addr,
        }
    )

    _LOGGER.debug("Status Pack: %s", pack)
    return pack


def gree_create_payload(
    pack: str,
    payload_type: str,
    i_command: GreeCommand,
    mac_addr: str,
    uid: int,
    encryption_version: EncryptionVersion,
    tag: str,
) -> str:
    """Create the full payload to send to the device."""

    base_payload: dict[str, Any] = {
        "cid": "app",
        "i": i_command.value,
        "pack": pack,
        "t": payload_type,
        "tcid": mac_addr,
        "uid": uid,
    }

    if encryption_version == EncryptionVersion.V2 and tag is not None:
        base_payload["tag"] = tag

    # _LOGGER.debug("Payload: %s", payload)
    return json.dumps(base_payload)


async def gree_get_device_key(
    ip_addr: str,
    mac_addr: str,
    port: int,
    uid: int,
    encryption_version: EncryptionVersion | None,
    max_connection_attempts: int,
    timeout: int,
) -> tuple[str, EncryptionVersion]:
    """Get the device key by sending a bind request to the device using a generic key (async)."""

    key = ""
    error: Exception = ValueError("Unknown error getting device encryption key")

    for enc_version in (
        [EncryptionVersion.V1, EncryptionVersion.V2]
        if encryption_version is None
        else [encryption_version]
    ):
        _LOGGER.info("Trying to retrieve device encryption key v%d", enc_version)
        pack, tag = gree_create_encrypted_pack(
            gree_create_bind_pack(mac_addr, uid, enc_version),
            gree_get_default_cipher(enc_version),
            enc_version,
        )
        jsonPayloadToSend = gree_create_payload(
            pack, "pack", GreeCommand.BIND, mac_addr, uid, enc_version, tag
        )

        try:
            result = await get_result_pack(
                ip_addr,
                port,
                jsonPayloadToSend,
                gree_get_default_cipher(enc_version),
                enc_version,
                max_connection_attempts,
                timeout,
            )
            key = result.get("key", "")
        except Exception as err:  # noqa: BLE001
            error = err
            _LOGGER.error(
                "Error getting device encryption key with version %d:\n%s",
                enc_version,
                err,
            )
            # raise ValueError("Error getting device encryption key") from err
            continue

        if key.strip() == "":
            error = ValueError("Received empty encryption key from device")
            continue

        _LOGGER.info(
            "Fetched device encryption key with version %d with success", enc_version
        )
        _LOGGER.debug("Fetched encryption key: %s", key)

        return key, enc_version

    raise ValueError("Error getting device encryption key") from error


async def gree_get_status(
    ip_addr: str,
    mac_addr: str,
    mac_addr_sub: str,
    port: int,
    uid: int,
    encryption_key: str,
    encryption_version: EncryptionVersion,
    props: list[GreeProp],
    max_connection_attempts: int,
    timeout: int,
) -> dict[GreeProp, int]:
    """Get the status of the device by sending a status request to the device (async)."""

    _LOGGER.debug("Trying to get device status")

    status_values: dict[GreeProp, int] = {}

    pack, tag = gree_create_encrypted_pack(
        gree_create_status_pack(mac_addr_sub, [prop.value for prop in props]),
        get_cipher(encryption_key, encryption_version),
        encryption_version,
    )
    jsonPayloadToSend = gree_create_payload(
        pack, "pack", GreeCommand.STATUS, mac_addr, uid, encryption_version, tag
    )

    try:
        result = await get_result_pack(
            ip_addr,
            port,
            jsonPayloadToSend,
            get_cipher(encryption_key, encryption_version),
            encryption_version,
            max_connection_attempts,
            timeout,
        )
    except Exception as err:
        raise ValueError("Error getting device status") from err

    if result["cols"] is None or result["dat"] is None:
        raise ValueError("Error getting device status, no data received")

    cols = [propkey_to_enum[c] for c in result["cols"] if c in propkey_to_enum]
    values = list(map(int, result["dat"]))
    status_values = dict(zip(cols, values, strict=True))

    _LOGGER.debug("Device status values: %s", status_values)
    return status_values


async def gree_set_status(
    ip_addr: str,
    mac_addr: str,
    mac_addr_sub: str,
    port: int,
    uid: int,
    encryption_key: str,
    encryption_version: EncryptionVersion,
    props: dict[GreeProp, int],
    max_connection_attempts: int,
    timeout: int,
) -> dict[GreeProp, int]:
    """Set the status of the device by sending a status request to the device (async)."""

    _LOGGER.debug("Trying to set device status")

    set_pack = gree_create_set_pack(mac_addr_sub, props)
    pack, tag = gree_create_encrypted_pack(
        set_pack,
        get_cipher(encryption_key, encryption_version),
        encryption_version,
    )

    jsonPayloadToSend = gree_create_payload(
        pack, "pack", GreeCommand.STATUS, mac_addr, uid, encryption_version, tag
    )

    try:
        result = await get_result_pack(
            ip_addr,
            port,
            jsonPayloadToSend,
            get_cipher(encryption_key, encryption_version),
            encryption_version,
            max_connection_attempts,
            timeout,
        )
    except Exception as err:
        raise ValueError("Error getting device status") from err

    if result["r"] is None or result["r"] != 200:
        raise ValueError(f"Error setting device status, response code: {result['r']}")

    options_set = [propkey_to_enum[c] for c in result["opt"] if c in propkey_to_enum]
    if options_set is None or len(options_set) == 0:
        raise ValueError("No options were set, something went wrong")

    values_set_1 = result.get("p", None)
    values_set_2 = result.get("val", None)  # this one is optional

    if values_set_1 is None:
        raise ValueError("No values were set, something went wrong")
    values_set_1 = list(map(int, values_set_1))

    if values_set_2 is not None:
        values_set_2 = list(map(int, values_set_2))
        if len(values_set_1) != len(values_set_2):
            raise ValueError(
                f"Wrong option values received: {values_set_1} {values_set_2}"
            )

    if len(values_set_1) != len(options_set):
        raise ValueError(
            f"Options and values set mismatch {options_set} {values_set_1}"
        )

    updated_props = dict(zip(options_set, values_set_1, strict=True))
    if updated_props != props:
        _LOGGER.warning("Expected updated props %s but got %s", props, updated_props)

    return updated_props


async def gree_get_device_info(
    ip_addr: str,
    max_connection_attempts: int,
    timeout: int,
) -> dict[str, str | None]:
    """Tries to retrive the device info."""
    try:
        data: dict = await get_result_pack(
            ip_addr,
            DEFAULT_DEVICE_PORT,
            json.dumps({"t": "scan"}),
            gree_get_default_cipher(EncryptionVersion.V1),
            EncryptionVersion.V1,
            max_connection_attempts,
            timeout,
        )
    except Exception as err:
        _LOGGER.exception("Error retrieving basic device info")
        raise ValueError("Error retrieving basic device info") from err
    else:
        _LOGGER.debug(data)
        info: dict[str, str | None] = {}
        info["firmware_version"], info["firmware_code"] = extract_version(data)
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

    responses = udp_broadcast_request(
        broadcast_addresses, DEFAULT_DEVICE_PORT, json.dumps({"t": "scan"}), timeout
    )

    for address, response in responses.items():
        data = get_gree_response_data(
            response,
            gree_get_default_cipher(EncryptionVersion.V1),
            EncryptionVersion.V1,
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
                    )

                    # If VRF, the mac is of the main device and we have to query it for the sub devices
                    # Sub-devices will be created with a mac of sub@main
                    # check if the device has sub-devices
                    sub_count = pack.get("subCnt", 0)

                    if sub_count == 0:  # Is normal HVAC
                        discovered_devices.append(discovered_device)
                        _LOGGER.debug("Discovered device: %s", discovered_device)
                    else:  # Is VRF with multiple sub devices
                        _LOGGER.debug(
                            "Trying to fetching sub-devices for '%s' (subCount=%d)",
                            mac_addr,
                            sub_count,
                        )
                        try:
                            discovered_sub_devices = await get_sub_devices_list(
                                discovered_device.mac,
                                discovered_device.host,
                                discovered_device.uid,
                                max_connection_attempts=2,
                                timeout=timeout,
                            )

                            for sub_device in discovered_sub_devices:
                                sub_mac = sub_device.get("mac", "")
                                if sub_mac:
                                    discovered_sub_device = GreeDiscoveredDevice(
                                        name=f"{discovered_device.name}@{sub_mac[:4]}"
                                        or f"Gree {mac_addr[-4:]}",
                                        host=discovered_device.host,
                                        mac=f"{sub_mac}@{discovered_device.mac}",
                                        port=discovered_device.port,
                                        brand=discovered_device.brand,
                                        model=sub_device.get("mid", discovered_device),
                                        uid=discovered_device.uid,
                                    )
                                    discovered_devices.append(discovered_sub_device)
                                    _LOGGER.debug(
                                        "Discovered sub-device: %s", discovered_device
                                    )
                        except Exception:
                            _LOGGER.exception("Failed to fetch sub-devices")

    return discovered_devices


async def get_sub_devices_list(
    mac_addr: str, ip_addr: str, uid: int, max_connection_attempts: int, timeout: int
) -> list:
    """Fetch the list of sub-devices for a Gree device."""
    try:
        _, version = await gree_get_device_key(
            ip_addr,
            mac_addr,
            DEFAULT_DEVICE_PORT,
            uid,
            None,
            max_connection_attempts,
            timeout,
        )

        pack, tag = gree_create_encrypted_pack(
            gree_create_sub_bind_pack(mac_addr),
            gree_get_default_cipher(version),
            version,
        )

        jsonPayloadToSend = gree_create_payload(
            pack,
            "subList",
            GreeCommand.BIND,
            mac_addr,
            uid,
            version,
            tag,
        )

        result = await get_result_pack(
            ip_addr,
            DEFAULT_DEVICE_PORT,
            jsonPayloadToSend,
            gree_get_default_cipher(version),
            version,
            max_connection_attempts,
            timeout,
        )

        return result.get("list", [])

    except Exception as err:
        raise ValueError(f"Error fetching sub-device list for '{mac_addr}'") from err
