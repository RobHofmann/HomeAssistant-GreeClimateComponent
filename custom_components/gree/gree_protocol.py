"""
Gree protocol/network logic for Home Assistant integration.
"""

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

_LOGGER = logging.getLogger(__name__)

GCM_IV = b"\x54\x40\x78\x44\x49\x67\x5a\x51\x6c\x5e\x63\x13"
GCM_ADD = b"qualcomm-test"
GENERIC_GREE_DEVICE_KEY = "a3K8Bx%2r8Y7#xDh"
GENERIC_GREE_DEVICE_KEY_GCM = b"{yxAHAY_Lm6pbC/<"


def Pad(s):
    aesBlockSize = 16
    return s + (aesBlockSize - len(s) % aesBlockSize) * chr(aesBlockSize - len(s) % aesBlockSize)


def FetchResult(cipher, ip_addr, port, timeout, json_data, encryption_version=1):
    _LOGGER.debug("Fetching(%s, %s, %s, %s)" % (ip_addr, port, timeout, json_data))
    clientSock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    clientSock.settimeout(timeout)
    clientSock.sendto(bytes(json_data, "utf-8"), (ip_addr, port))
    data, addr = clientSock.recvfrom(64000)
    receivedJson = simplejson.loads(data)
    clientSock.close()
    pack = receivedJson["pack"]
    base64decodedPack = base64.b64decode(pack)
    decryptedPack = cipher.decrypt(base64decodedPack)
    if encryption_version == 2:
        tag = receivedJson["tag"]
        cipher.verify(base64.b64decode(tag))
    decodedPack = decryptedPack.decode("utf-8")
    replacedPack = decodedPack.replace("\x0f", "").replace(decodedPack[decodedPack.rindex("}") + 1 :], "")
    loadedJsonPack = simplejson.loads(replacedPack)
    return loadedJsonPack


def GetDeviceKey(mac_addr, ip_addr, port, timeout):
    _LOGGER.info("Retrieving HVAC encryption key")
    cipher = AES.new(GENERIC_GREE_DEVICE_KEY.encode("utf8"), AES.MODE_ECB)
    pack = base64.b64encode(cipher.encrypt(Pad('{"mac":"' + str(mac_addr) + '","t":"bind","uid":0}').encode("utf8"))).decode("utf-8")
    jsonPayloadToSend = '{"cid": "app","i": 1,"pack": "' + pack + '","t":"pack","tcid":"' + str(mac_addr) + '","uid": 0}'
    try:
        key = FetchResult(cipher, ip_addr, port, timeout, jsonPayloadToSend)["key"].encode("utf8")
    except Exception:
        _LOGGER.info("Error getting device encryption key!")
        return None
    else:
        _LOGGER.info("Fetched device encryption key: %s" % str(key))
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


def GetDeviceKeyGCM(mac_addr, ip_addr, port, timeout):
    _LOGGER.info("Retrieving HVAC encryption key (GCM)")
    plaintext = '{"cid":"' + str(mac_addr) + '", "mac":"' + str(mac_addr) + '","t":"bind","uid":0}'
    pack, tag = EncryptGCM(GENERIC_GREE_DEVICE_KEY_GCM, plaintext)
    jsonPayloadToSend = '{"cid": "app","i": 1,"pack": "' + pack + '","t":"pack","tcid":"' + str(mac_addr) + '","uid": 0, "tag" : "' + tag + '"}'
    try:
        key = FetchResult(GetGCMCipher(GENERIC_GREE_DEVICE_KEY_GCM), ip_addr, port, timeout, jsonPayloadToSend, encryption_version=2)["key"].encode("utf8")
    except Exception:
        _LOGGER.info("Error getting device encryption key!")
        return None
    else:
        _LOGGER.info("Fetched device encryption key: %s" % str(key))
        return key
