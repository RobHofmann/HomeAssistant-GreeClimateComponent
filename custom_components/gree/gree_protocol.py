"""
Gree protocol/network logic for Home Assistant integration.
"""

# Standard library imports
import asyncio
import base64
import logging
import socket

# Third-party imports
try:
    import simplejson
except ImportError:
    import json as simplejson
from Crypto.Cipher import AES

# Home Assistant imports
from homeassistant.const import CONF_HOST, CONF_PORT

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


async def FetchResult(cipher, ip_addr, port, json_data, encryption_version=1):
    """Send a request to a Gree device and fetch the result, with retries and timeouts."""

    _LOGGER.debug(f"Fetching device at: {ip_addr}:{port}, data sent: {json_data})")

    timeout = 2
    max_retries = 8

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

    _LOGGER.debug(f"test_connection: host={ip_addr}, port={port}, timeout=10, encryption_version={encryption_version}, encryption_key={encryption_key}")

    try:
        if encryption_version == 1:
            key = await GetDeviceKey(encryption_key, ip_addr, port)
        else:
            key = await GetDeviceKeyGCM(encryption_key, ip_addr, port)
        _LOGGER.debug(f"test_connection: Got device key: {key}")
        return key is not None
    except Exception as e:
        _LOGGER.error(f"Gree device at {ip_addr} is unreachable: {type(e).__name__}: {e}", exc_info=True)
        return False


async def GetDeviceKey(mac_addr, ip_addr, port):
    _LOGGER.debug("Retrieving HVAC encryption key")
    cipher = AES.new(GENERIC_GREE_DEVICE_KEY.encode("utf8"), AES.MODE_ECB)
    pack = base64.b64encode(cipher.encrypt(Pad('{"mac":"' + str(mac_addr) + '","t":"bind","uid":0}').encode("utf8"))).decode("utf-8")
    jsonPayloadToSend = '{"cid": "app","i": 1,"pack": "' + pack + '","t":"pack","tcid":"' + str(mac_addr) + '","uid": 0}'
    try:
        result = await FetchResult(cipher, ip_addr, port, jsonPayloadToSend)
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


async def GetDeviceKeyGCM(mac_addr, ip_addr, port):
    _LOGGER.debug("Retrieving HVAC encryption key (GCM)")
    plaintext = '{"cid":"' + str(mac_addr) + '", "mac":"' + str(mac_addr) + '","t":"bind","uid":0}'
    pack, tag = EncryptGCM(GENERIC_GREE_DEVICE_KEY_GCM, plaintext)
    jsonPayloadToSend = '{"cid": "app","i": 1,"pack": "' + pack + '","t":"pack","tcid":"' + str(mac_addr) + '","uid": 0, "tag" : "' + tag + '"}'
    try:
        result = await FetchResult(GetGCMCipher(GENERIC_GREE_DEVICE_KEY_GCM), ip_addr, port, jsonPayloadToSend, encryption_version=2)
        _LOGGER.debug(f"GetDeviceKeyGCM: FetchResult: {result}")
        key = result["key"].encode("utf8")
    except Exception:
        _LOGGER.debug("Error getting device encryption key!")
        return None
    else:
        _LOGGER.debug(f"Fetched device encryption key: {str(key)}")
        return key
