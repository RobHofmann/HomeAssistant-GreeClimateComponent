"""Encapsulates device encryption."""

import base64
import logging

from Crypto.Cipher import AES

_LOGGER = logging.getLogger(__name__)

GCM_IV = b"\x54\x40\x78\x44\x49\x67\x5a\x51\x6c\x5e\x63\x13"
GCM_ADD = b"qualcomm-test"

GREE_GENERIC_DEVICE_KEY = "a3K8Bx%2r8Y7#xDh"
GREE_GENERIC_DEVICE_KEY_GCM = "{yxAHAY_Lm6pbC/<"


class CipherBase:
    """Base class for the encryprion module."""

    def __init__(self, key: str) -> None:
        """Initialize the class."""
        self.key = key

    @property
    def key(self) -> str:
        """The encryprion key."""
        return self._key.decode()

    @key.setter
    def key(self, value: str) -> None:
        self._key = value.encode()

    def encrypt(self, data: str) -> tuple[str, str | None]:
        """Encrypts the data. Returns the encrypted data and an optional tag."""
        raise NotImplementedError

    def decrypt(self, data: str, tag: str | None) -> str:
        """Decrypts the data. Optionally checks integrity if tag is provided."""
        raise NotImplementedError


class CipherV1(CipherBase):
    """Implements the V1 type encryption used by Gree."""

    def __init__(self, key: str = GREE_GENERIC_DEVICE_KEY) -> None:
        """Initialize V1 Encryption."""
        super().__init__(key)

    def __create_cipher(self) -> AES:
        return AES.new(self._key, AES.MODE_ECB)

    def __pad(self, s) -> str:
        aesBlockSize = 16
        requiredPaddingSize = aesBlockSize - len(s) % aesBlockSize
        return s + requiredPaddingSize * chr(requiredPaddingSize)

    def encrypt(self, data: str) -> tuple[str, str | None]:
        """Encrypt data with V1."""
        _LOGGER.debug("Encrypting data: %s", data)
        cipher = self.__create_cipher()
        padded = self.__pad(data).encode("utf-8")
        encrypted = cipher.encrypt(padded)
        encoded = base64.b64encode(encrypted).decode("utf-8")
        _LOGGER.debug("Encrypted data: %s", encoded)
        return encoded, None

    def decrypt(self, data: str, tag: None) -> str:
        """Decrypt data with V1."""
        _LOGGER.debug("Decrypting data: %s", data)
        cipher = self.__create_cipher()
        decoded = base64.b64decode(data)
        decrypted = cipher.decrypt(decoded).decode("utf-8")
        t = decrypted.replace("\x0f", "").replace(
            decrypted[decrypted.rindex("}") + 1 :], ""
        )
        _LOGGER.debug("Decrypted data: %s", t)
        return t


class CipherV2(CipherBase):
    """Implements the V2 type encryption used by Gree."""

    def __init__(self, key: str = GREE_GENERIC_DEVICE_KEY_GCM) -> None:
        """Initialize V2 Encryption."""
        super().__init__(key)

    def __create_cipher(self) -> AES:
        cipher = AES.new(self._key, AES.MODE_GCM, nonce=GCM_IV)
        cipher.update(GCM_ADD)
        return cipher

    def encrypt(self, data: str) -> tuple[str, str]:
        """Encrypt data with V2 and return the data with a tag."""
        _LOGGER.debug("Encrypting data: %s", data)
        cipher = self.__create_cipher()
        encrypted, tag = cipher.encrypt_and_digest(data.encode("utf-8"))
        encoded = base64.b64encode(encrypted).decode("utf-8")
        tag = base64.b64encode(tag).decode("utf-8")
        _LOGGER.debug("Encrypted data: %s", encoded)
        _LOGGER.debug("Cipher digest: %s", tag)
        return encoded, tag

    def decrypt(self, data: str, tag: str) -> str:
        """Decrypt data with V2 and verify the data with the tag."""
        _LOGGER.debug("Decrypting data: %s", data)
        cipher = self.__create_cipher()
        decoded = base64.b64decode(data)
        decrypted = cipher.decrypt(decoded).decode("utf-8")
        t = decrypted.replace("\x0f", "").replace(
            decrypted[decrypted.rindex("}") + 1 :], ""
        )

        _LOGGER.debug("Verifying tag: %s", tag)
        cipher.verify(base64.b64decode(tag))

        _LOGGER.debug("Decrypted data successfully")
        return t
