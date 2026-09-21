"""Tests for the cipher layer.

These use fixed vectors on purpose. The fake device shares the component's
cipher, so a bug in there could cancel itself out in every other test file. A
recorded byte string cannot cancel itself out.
"""

import base64

from aiogree.cipher import (
    GCM_ADD,
    GCM_IV,
    GREE_GENERIC_DEVICE_KEY_ECB,
    GREE_GENERIC_DEVICE_KEY_GCM,
    CipherV1,
    CipherV2,
    EncryptionVersion,
    get_cipher,
)
from aiogree.errors import GreeError
import pytest

# A 16 character key that is not a real device key.
KNOWN_KEY = "0123456789abcdef"
KNOWN_PLAINTEXT = '{"t":"status","mac":"f4911e3f1ac8","cols":["Pow"]}'

# Recorded once with the cryptography library, AES-128-ECB with PKCS7 padding.
KNOWN_V1_CIPHERTEXT = "FpOYBS8AEeklmEYStgCWuseiQONapus4P2AVQRHQC1V0LLq9o6zhZRtI83BnX2rY2egG25oDL4XgMoDqgSfZKQ=="

# Recorded once with AES-128-GCM, the protocol's fixed IV and its fixed
# additional data.
KNOWN_V2_CIPHERTEXT = (
    "i3fKw/EEZf5wEbrPdpe/74zwHJNK6h57vF6PJMRL5k4nMzOtJl2tM9qX3jhp7vCMfNQ="
)
KNOWN_V2_TAG = "aVZV1ESZvzNSXEItbtUK4Q=="


def test_v1_round_trip() -> None:
    """V1 gives back what it was given."""
    cipher = CipherV1(KNOWN_KEY)

    encrypted, tag = cipher.encrypt(KNOWN_PLAINTEXT)

    assert tag is None
    assert cipher.decrypt(encrypted, None) == KNOWN_PLAINTEXT


def test_v2_round_trip_checks_the_tag() -> None:
    """V2 gives back what it was given, and it returns a tag."""
    cipher = CipherV2(KNOWN_KEY)

    encrypted, tag = cipher.encrypt(KNOWN_PLAINTEXT)

    assert tag
    assert cipher.decrypt(encrypted, tag) == KNOWN_PLAINTEXT


def test_v1_matches_a_recorded_vector() -> None:
    """V1 with a known key and known text gives a fixed string."""
    encrypted, _ = CipherV1(KNOWN_KEY).encrypt(KNOWN_PLAINTEXT)

    assert encrypted == KNOWN_V1_CIPHERTEXT


def test_v1_decrypts_a_recorded_vector() -> None:
    """V1 reads back the recorded string."""
    assert CipherV1(KNOWN_KEY).decrypt(KNOWN_V1_CIPHERTEXT, None) == KNOWN_PLAINTEXT


def test_v2_matches_a_recorded_vector() -> None:
    """V2 with a known key and known text gives a fixed string and tag."""
    encrypted, tag = CipherV2(KNOWN_KEY).encrypt(KNOWN_PLAINTEXT)

    assert encrypted == KNOWN_V2_CIPHERTEXT
    assert tag == KNOWN_V2_TAG


def test_v2_tag_mismatch_raises() -> None:
    """A wrong tag raises, it does not return garbage."""
    cipher = CipherV2(KNOWN_KEY)
    encrypted, _ = cipher.encrypt(KNOWN_PLAINTEXT)
    wrong_tag = base64.b64encode(b"\x00" * 16).decode()

    with pytest.raises(GreeError):
        cipher.decrypt(encrypted, wrong_tag)


def test_v2_without_a_tag_raises() -> None:
    """V2 cannot check a pack without a tag, so it refuses."""
    cipher = CipherV2(KNOWN_KEY)
    encrypted, _ = cipher.encrypt(KNOWN_PLAINTEXT)

    with pytest.raises(GreeError):
        cipher.decrypt(encrypted, None)


def test_get_cipher_without_a_version_raises() -> None:
    """There is no default version. Asking for one is a programming error."""
    with pytest.raises(ValueError, match="Unsupported encryption version"):
        get_cipher(None)


def test_get_cipher_v1_without_a_key_uses_the_generic_key() -> None:
    """A device that is not bound yet only answers the generic key."""
    assert get_cipher(EncryptionVersion.V1).key == GREE_GENERIC_DEVICE_KEY_ECB


def test_get_cipher_v2_without_a_key_uses_the_generic_key() -> None:
    """V2 has its own generic key."""
    assert get_cipher(EncryptionVersion.V2).key == GREE_GENERIC_DEVICE_KEY_GCM


@pytest.mark.parametrize(
    "garbage",
    [
        "\x00\x00\x00",
        "   ",
        "\x11\x22\x33\x44",
    ],
)
def test_trailing_garbage_after_the_closing_brace_is_trimmed(garbage: str) -> None:
    """Real units pad their replies with junk. The JSON still has to parse."""
    cipher = CipherV1(KNOWN_KEY)
    encrypted, _ = cipher.encrypt(KNOWN_PLAINTEXT + garbage)

    assert cipher.decrypt(encrypted, None) == KNOWN_PLAINTEXT


def test_a_payload_without_a_closing_brace_raises() -> None:
    """Without a closing brace there is no JSON to keep."""
    cipher = CipherV1(KNOWN_KEY)
    encrypted, _ = cipher.encrypt("not json at all")

    with pytest.raises(GreeError):
        cipher.decrypt(encrypted, None)


def test_the_protocol_constants_did_not_change() -> None:
    """These values are baked into every device. Changing one breaks all of them."""
    assert GCM_IV == b"\x54\x40\x78\x44\x49\x67\x5a\x51\x6c\x5e\x63\x13"
    assert GCM_ADD == b"qualcomm-test"
    assert GREE_GENERIC_DEVICE_KEY_ECB == "a3K8Bx%2r8Y7#xDh"
    assert GREE_GENERIC_DEVICE_KEY_GCM == "{yxAHAY_Lm6pbC/<"
