"""
Gree protocol/network logic for Home Assistant integration.
"""

# Standard library imports
import asyncio
import base64
import logging
import socket
import time

# Third-party imports
try:
    import simplejson
except ImportError:
    import json as simplejson
from Crypto.Cipher import AES

# Home Assistant imports
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_MAC
from homeassistant.components.network import async_get_ipv4_broadcast_addresses

# Local imports
from .const import (
    CONF_ENCRYPTION_VERSION,
    CONF_ENCRYPTION_KEY,
)

_LOGGER = logging.getLogger(__name__)

GCM_IV = b"\x54\x40\x78\x44\x49\x67\x5a\x51\x6c\x5e\x63\x13"
GCM_ADD = b"qualcomm-test"
GENERIC_GREE_DEVICE_KEY = "a3K8Bx%2r8Y7#xDh"
GENERIC_GREE_DEVICE_KEY_GCM = b"{yxAHAY_Lm6pbC/<"


async def FetchResult(cipher, ip_addr, port, json_data, encryption_version=1, max_retries=8):
    """Send a request to a Gree device and fetch the result, with retries and timeouts."""

    _LOGGER.debug(f"Fetching device at: {ip_addr}:{port}, data sent: {json_data})")

    timeout = 2

    for attempt in range(max_retries):
        clientSock = None
        try:
            clientSock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            clientSock.settimeout(timeout)

            # Send data to device
            clientSock.sendto(bytes(json_data, "utf-8"), (ip_addr, port))

            # Receive response with event loop yielding
            data, _ = await asyncio.wait_for(asyncio.get_event_loop().run_in_executor(None, clientSock.recvfrom, 64000), timeout=timeout)

            # Parse and decrypt response
            received_json = simplejson.loads(data)
            pack = received_json["pack"]
            decoded_pack = base64.b64decode(pack)
            decrypted_pack = cipher.decrypt(decoded_pack)

            if encryption_version == 2:
                tag = received_json["tag"]
                cipher.verify(base64.b64decode(tag))

            # Clean up response data
            decoded_text = decrypted_pack.decode("utf-8")
            # Remove null bytes and trailing data after last }
            clean_text = decoded_text.replace("\x0f", "")
            last_brace = clean_text.rindex("}")
            clean_text = clean_text[: last_brace + 1]

            result = simplejson.loads(clean_text)

            _LOGGER.debug(f"Successfully received response on attempt {attempt + 1}")
            return result

        except Exception as e:
            if attempt == max_retries - 1:
                error_msg = f"{type(e).__name__}: {str(e)}" if str(e) else f"{type(e).__name__}"
                _LOGGER.error(f"All {max_retries} attempts failed for {ip_addr}:{port}. Error: {error_msg}")
                raise

        finally:
            if clientSock:
                try:
                    clientSock.close()
                except Exception as e:
                    _LOGGER.debug(f"Error closing socket: {str(e)}")

        # Progressive backoff before retry
        if attempt < max_retries - 1:
            await asyncio.sleep(0.5 + (attempt * 0.3))  # 0.5s, 0.8s, 1.1s, 1.4s, 1.7s, 2.0s, 2.3s


def Pad(s):
    aesBlockSize = 16
    return s + (aesBlockSize - len(s) % aesBlockSize) * chr(aesBlockSize - len(s) % aesBlockSize)


async def test_connection(config):
    """Test connection to a Gree device."""

    ip_addr = config[CONF_HOST]
    port = config[CONF_PORT]
    encryption_version = config[CONF_ENCRYPTION_VERSION]
    encryption_key = config[CONF_ENCRYPTION_KEY]

    mac_addr = config.get(CONF_MAC).encode().replace(b":", b"").decode("utf-8").lower()
    if "@" in mac_addr:
        mac_addr = mac_addr.split("@", 1)[1]

    _LOGGER.debug(f"test_connection: host={ip_addr}, port={port}, mac={mac_addr}, encryption_version={encryption_version}, encryption_key={encryption_key}")

    try:
        if encryption_version == 1:
            key = await GetDeviceKey(mac_addr, ip_addr, port)
        else:
            key = await GetDeviceKeyGCM(mac_addr, ip_addr, port)
        _LOGGER.debug(f"test_connection: Got device key: {key}")
        return key is not None
    except Exception as e:
        _LOGGER.error(f"Gree device at {ip_addr} is unreachable: {type(e).__name__}: {e}", exc_info=True)
        return False


async def GetDeviceKey(mac_addr, ip_addr, port, max_retries=8):
    _LOGGER.debug("Retrieving HVAC encryption key")
    cipher = AES.new(GENERIC_GREE_DEVICE_KEY.encode("utf8"), AES.MODE_ECB)
    pack = base64.b64encode(cipher.encrypt(Pad(f'{{"mac":"{mac_addr}","t":"bind","uid":0}}').encode("utf8"))).decode("utf-8")
    jsonPayloadToSend = f'{{"cid": "app","i": 1,"pack": "{pack}","t":"pack","tcid":"{mac_addr}","uid": 0}}'
    try:
        result = await FetchResult(cipher, ip_addr, port, jsonPayloadToSend, max_retries=max_retries)
        _LOGGER.debug(f"GetDeviceKey: FetchResult: {result}")
        key = result["key"].encode("utf8")
    except Exception:
        _LOGGER.debug("Error getting device encryption key!")
        return None
    else:
        _LOGGER.debug(f"Fetched device encryption key: {str(key)}")
        return key


def GetGCMCipher(key):
    cipher = AES.new(key, AES.MODE_GCM, nonce=GCM_IV)
    cipher.update(GCM_ADD)
    return cipher


def EncryptGCM(key, plaintext):
    cipher = GetGCMCipher(key)
    encrypted_data, tag = cipher.encrypt_and_digest(plaintext.encode("utf8"))
    pack = base64.b64encode(encrypted_data).decode("utf-8")
    tag = base64.b64encode(tag).decode("utf-8")
    return (pack, tag)


async def GetDeviceKeyGCM(mac_addr, ip_addr, port, max_retries=8):
    _LOGGER.debug("Retrieving HVAC encryption key (GCM)")
    plaintext = f'{{"cid":"{mac_addr}", "mac":"{mac_addr}","t":"bind","uid":0}}'
    pack, tag = EncryptGCM(GENERIC_GREE_DEVICE_KEY_GCM, plaintext)
    jsonPayloadToSend = f'{{"cid": "app","i": 1,"pack": "{pack}","t":"pack","tcid":"{mac_addr}","uid": 0, "tag" : "{tag}"}}'
    try:
        result = await FetchResult(GetGCMCipher(GENERIC_GREE_DEVICE_KEY_GCM), ip_addr, port, jsonPayloadToSend, encryption_version=2, max_retries=max_retries)
        _LOGGER.debug(f"GetDeviceKeyGCM: FetchResult: {result}")
        key = result["key"].encode("utf8")
    except Exception:
        _LOGGER.debug("Error getting device encryption key!")
        return None
    else:
        _LOGGER.debug(f"Fetched device encryption key: {str(key)}")
        return key


async def discover_gree_devices(hass, timeout=5):
    """Discover Gree devices on the local network using UDP broadcast."""
    _LOGGER.debug("Starting Gree device discovery...")

    BROADCAST_PORT = 7000
    DISCOVERY_MESSAGE = b'{"t":"scan"}'

    # Set up UDP socket for broadcast
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(timeout)
    sock.bind(("", 0))

    devices = []

    try:
        # Default broadcast addresses to try
        broadcast_addresses = [
            "255.255.255.255",  # Limited broadcast
            "192.168.255.255",  # /16 broadcast for 192.168.x.x networks
            "10.255.255.255",  # /8 broadcast for 10.x.x.x networks
            "172.31.255.255",  # /12 broadcast for 172.16-31.x.x networks
        ]

        # Get broadcast addresses from Home Assistant's network helper
        try:
            ha_broadcast_addresses = await async_get_ipv4_broadcast_addresses(hass)
            ha_broadcast_strings = [str(addr) for addr in ha_broadcast_addresses]
            broadcast_addresses.extend(ha_broadcast_strings)
            _LOGGER.debug(f"Found broadcast addresses from HA: {ha_broadcast_strings}")
        except Exception as e:
            _LOGGER.debug(f"Could not get HA broadcast addresses: {e}")

        # Remove duplicates
        broadcast_addresses = list(dict.fromkeys(broadcast_addresses))

        # Send to all broadcast addresses
        for broadcast_addr in broadcast_addresses:
            try:
                _LOGGER.debug(f"Sending discovery to {broadcast_addr}")
                sock.sendto(DISCOVERY_MESSAGE, (broadcast_addr, BROADCAST_PORT))
            except Exception as e:
                _LOGGER.debug(f"Failed to send to {broadcast_addr}: {e}")

        _LOGGER.debug("Sent discovery packets, waiting for replies...")

        start = time.time()
        while time.time() - start < timeout:
            try:
                data, addr = sock.recvfrom(1024)
                try:
                    # Try to parse as JSON and decrypt if possible
                    response = simplejson.loads(data.decode(errors="ignore"))
                    if "pack" in response:
                        pack = response["pack"]
                        decoded_pack = base64.b64decode(pack)

                        # Discovery responses typically use level 1 encryption (ECB mode)
                        # But we need to test which encryption the device actually uses for communication
                        pack_json = None

                        try:
                            cipher = AES.new(GENERIC_GREE_DEVICE_KEY.encode("utf-8"), AES.MODE_ECB)
                            decrypted_pack = cipher.decrypt(decoded_pack)
                            # Remove null bytes and trailing data after last }
                            decoded_text = decrypted_pack.decode("utf-8", errors="ignore").replace("\x0f", "")
                            last_brace = decoded_text.rfind("}")
                            if last_brace != -1:
                                clean_text = decoded_text[: last_brace + 1]
                            else:
                                clean_text = decoded_text
                            pack_json = simplejson.loads(clean_text)
                            _LOGGER.debug(f"Decrypted discovery response from {addr}")
                        except Exception as e:
                            _LOGGER.debug(f"Could not decrypt discovery response from {addr}: {e}")
                            continue

                        # If we successfully decrypted and got device info
                        if pack_json and pack_json.get("t") == "dev":
                            mac_addr = pack_json.get("mac", "")
                            if not mac_addr:
                                _LOGGER.debug(f"No MAC address in response from {addr}")
                                continue

                            # Just collect basic device info for now - encryption detection happens later
                            device_info = {
                                "name": pack_json.get("name", "") or f"Gree {mac_addr[-4:]}",
                                "host": addr[0],
                                "port": BROADCAST_PORT,
                                "mac": mac_addr,
                                "brand": pack_json.get("brand", "gree"),
                                "model": pack_json.get("model", "gree"),
                                "version": pack_json.get("ver", ""),
                            }
                            devices.append(device_info)
                            _LOGGER.debug(f"Discovered Gree device: {device_info}")
                        else:
                            _LOGGER.debug(f"Invalid or missing device info from {addr}")
                    else:
                        _LOGGER.debug(f"Received response without pack from {addr}: {response}")
                except Exception as e:
                    _LOGGER.debug(f"Could not parse response from {addr}: {e}")
            except socket.timeout:
                break
    finally:
        sock.close()

    _LOGGER.debug(f"Discovery completed, found {len(devices)} devices")
    return devices


async def detect_device_encryption(mac_addr, ip_addr, port):
    """Test which encryption version a device uses for communication."""
    _LOGGER.debug(f"Detecting encryption version for device {mac_addr} at {ip_addr}:{port}")

    # Test encryption version 1 first
    try:
        _LOGGER.debug(f"Testing encryption version 1 for device {mac_addr}")
        key = await GetDeviceKey(mac_addr, ip_addr, port, max_retries=1)
        if key:
            _LOGGER.debug(f"Device {mac_addr} uses encryption version 1")
            return 1
    except Exception as e:
        _LOGGER.debug(f"Encryption version 1 failed for device {mac_addr}: {e}")

    # Test encryption version 2
    try:
        _LOGGER.debug(f"Testing encryption version 2 for device {mac_addr}")
        key = await GetDeviceKeyGCM(mac_addr, ip_addr, port, max_retries=1)
        if key:
            _LOGGER.debug(f"Device {mac_addr} uses encryption version 2")
            return 2
    except Exception as e:
        _LOGGER.debug(f"Encryption version 2 failed for device {mac_addr}: {e}")

    _LOGGER.error(f"Could not determine encryption version for device {mac_addr}")
    return None
