"""Encapsulates device encryption."""

from abc import ABC, abstractmethod
import base64
from enum import IntEnum, unique
import logging

from Crypto.Cipher import AES
from Crypto.Cipher._mode_ecb import EcbMode
from Crypto.Cipher._mode_gcm import GcmMode
from Crypto.Util.Padding import pad, unpad

from .errors import GreeError

_LOGGER = logging.getLogger(__name__)

# GREE PROTOCOL: Fixed parameters obtained by reverse-engineering the Gree protocol spec
GCM_IV = b"\x54\x40\x78\x44\x49\x67\x5a\x51\x6c\x5e\x63\x13"
GCM_ADD = b"qualcomm-test"
GREE_GENERIC_DEVICE_KEY_ECB = "a3K8Bx%2r8Y7#xDh"
GREE_GENERIC_DEVICE_KEY_GCM = "{yxAHAY_Lm6pbC/<"

AES_BLOCK_SIZE = 16


@unique
class EncryptionVersion(IntEnum):
    """Available encryption versions for the device."""

    V1 = 1
    V2 = 2


class CipherBase(ABC):
    """Base class for the encryption module."""

    def __init__(self, key: str) -> None:
        """Initialize the class."""
        self.key = key

    @property
    @abstractmethod
    def version(self) -> EncryptionVersion:
        """The encryption version of this cypher."""

    @property
    def key(self) -> str:
        """The encryption key."""
        return self._key.decode()

    @key.setter
    def key(self, value: str) -> None:
        self._key = value.encode()

    @abstractmethod
    def encrypt(self, data: str) -> tuple[str, str | None]:
        """Encrypts the data. Returns the encrypted data and an optional tag."""

    @abstractmethod
    def decrypt(self, data: str, tag: str | None) -> str:
        """Decrypts the data. Optionally checks integrity if tag is provided."""


class CipherV1(CipherBase):
    """Implements the V1 (AES-ECB) type encryption used by Gree."""

    def __init__(self, key: str | None) -> None:
        """Initialize V1 Encryption."""
        super().__init__(key or GREE_GENERIC_DEVICE_KEY_ECB)

    def _create_cipher(self) -> EcbMode:
        return AES.new(self._key, AES.MODE_ECB)

    @property
    def version(self) -> EncryptionVersion:
        """The encryption version of this cypher."""
        return EncryptionVersion.V1

    def encrypt(self, data: str) -> tuple[str, str | None]:
        """Encrypt data with V1."""
        _LOGGER.debug("Encrypting data (V1): %s", data)

        cipher = self._create_cipher()
        padded = pad(data.encode("utf-8"), AES_BLOCK_SIZE)

        encrypted = cipher.encrypt(padded)
        encoded = base64.b64encode(encrypted).decode("utf-8")

        _LOGGER.debug("Encrypted data (V1): %s", encoded)

        return encoded, None

    def decrypt(self, data: str, tag: str | None = None) -> str:
        """Decrypt data with V1."""
        _LOGGER.debug("Decrypting data (V1): %s", data)

        cipher = self._create_cipher()

        decoded = base64.b64decode(data)
        decrypted = cipher.decrypt(decoded)

        try:
            plaintext = unpad(decrypted, AES_BLOCK_SIZE).decode()
        except ValueError:
            # GREE PROTOCOL: Fallback for some devices sending malformed padding
            plaintext = decrypted.decode(errors="ignore")

        _LOGGER.debug("Decrypted data successfully (V1)")

        return _trim_json_payload(plaintext)


class CipherV2(CipherBase):
    """Implements the V2 (AES-GCM) type encryption used by Gree."""

    def __init__(self, key: str | None) -> None:
        """Initialize V2 Encryption."""
        super().__init__(key or GREE_GENERIC_DEVICE_KEY_GCM)

    def _create_cipher(self) -> GcmMode:
        cipher = AES.new(self._key, AES.MODE_GCM, nonce=GCM_IV)
        cipher.update(GCM_ADD)
        return cipher

    @property
    def version(self) -> EncryptionVersion:
        """The encryption version of this cypher."""
        return EncryptionVersion.V2

    def encrypt(self, data: str) -> tuple[str, str]:
        """Encrypt data with V2 and return the data with a tag."""
        _LOGGER.debug("Encrypting data (V2): %s", data)

        cipher = self._create_cipher()

        encrypted, tag = cipher.encrypt_and_digest(data.encode("utf-8"))

        encoded = base64.b64encode(encrypted).decode("utf-8")
        tag_encoded = base64.b64encode(tag).decode("utf-8")

        _LOGGER.debug("Encrypted data (V2): %s, tag='%s'", encoded, tag_encoded)
        return encoded, tag_encoded

    def decrypt(self, data: str, tag: str) -> str:
        """Decrypt data with V2 and verify the data with the tag."""
        _LOGGER.debug("Decrypting data (V2): %s, tag=%s", data, tag)

        if not tag:
            raise GreeError("Decrypting data (V2) failed: tag is needed")

        cipher = self._create_cipher()

        decoded = base64.b64decode(data)
        decoded_tag = base64.b64decode(tag)

        decrypted = cipher.decrypt_and_verify(decoded, decoded_tag)
        plaintext = decrypted.decode("utf-8")

        _LOGGER.debug("Decrypted data successfully (V2)")
        return _trim_json_payload(plaintext)


def _trim_json_payload(data: str) -> str:
    """Trims JSON garbage.

    Some devices append garbage after JSON payload.
    This safely trims everything after the final '}'.
    """

    end = data.rfind("}")

    if end == -1:
        raise GreeError("Malformed JSON payload without closing character")

    if end + 1 < len(data):
        _LOGGER.debug("Trimmed JSON payload garbage: %s", data[end + 1 :])

    return data[: end + 1]


def get_cipher(
    encryption_version: EncryptionVersion, key: str | None = None
) -> CipherBase:
    """Get AES cipher object based on encryption version using default keys."""

    match encryption_version:
        case EncryptionVersion.V1:
            return CipherV1(key)
        case EncryptionVersion.V2:
            return CipherV2(key)
        case _:
            raise ValueError(f"Unsupported encryption version: {encryption_version}")
