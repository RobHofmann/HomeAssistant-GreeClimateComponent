"""Tests for the pure payload builders and helpers.

No socket, no event loop. These are the parts every request is built from, so
a change here reaches every device.
"""

from aiogree.api import (
    _create_bind_pack,
    _create_get_status_pack,
    _create_payload,
    _create_set_status_pack,
)
from aiogree.cipher import EncryptionVersion, get_cipher
from aiogree.helpers import chunked, gree_extract_macs, redact_str
import pytest

MAC = "f4911e3f1ac8"


def test_bind_pack_v1() -> None:
    """V1 binds with the MAC only."""
    pack = _create_bind_pack(MAC, 0, get_cipher(EncryptionVersion.V1))

    assert pack == {"t": "bind", "uid": 0, "mac": MAC}


def test_bind_pack_v2_adds_the_cid() -> None:
    """V2 needs the MAC twice, once as cid."""
    pack = _create_bind_pack(MAC, 7, get_cipher(EncryptionVersion.V2))

    assert pack == {"t": "bind", "uid": 7, "mac": MAC, "cid": MAC}


def test_get_status_pack() -> None:
    """A status request carries the columns it wants."""
    pack = _create_get_status_pack(MAC, ["Pow", "Mod"])

    assert pack == {"t": "status", "mac": MAC, "cols": ["Pow", "Mod"]}


def test_set_status_pack_splits_names_and_values() -> None:
    """A command carries names in 'opt' and values in 'p', in the same order."""
    pack = _create_set_status_pack(MAC, {"Lig": 1})

    assert pack == {"t": "cmd", "sub": MAC, "opt": ["Lig"], "p": [1]}


def test_set_status_pack_orders_mode_first_and_power_last() -> None:
    """Commercial units need mode, then temperature, then the rest, then power."""
    pack = _create_set_status_pack(
        MAC,
        {
            "Pow": 1,
            "Lig": 1,
            "SetTem": 21,
            "Mod": 4,
            "TemUn": 0,
            "TemRec": 0,
            "Buzzer_ON_OFF": 1,
        },
    )

    assert pack["opt"] == [
        "Mod",
        "TemUn",
        "TemRec",
        "SetTem",
        "Lig",
        "Pow",
        "Buzzer_ON_OFF",
    ]
    assert pack["p"] == [4, 0, 0, 21, 1, 1, 1]


def test_payload_wraps_a_pack() -> None:
    """The envelope says who the pack is for."""
    payload = _create_payload({"t": "bind"}, "pack", 1, MAC, 0)

    assert payload == {
        "cid": "app",
        "i": 1,
        "t": "pack",
        "pack": {"t": "bind"},
        "tcid": MAC,
        "uid": 0,
    }


@pytest.mark.parametrize(
    ("raw", "expected_mac", "expected_controller"),
    [
        # A normal unit: both MACs are the same.
        ("f4911e3f1ac8", "f4911e3f1ac8", "f4911e3f1ac8"),
        ("F4911E3F1AC8", "f4911e3f1ac8", "f4911e3f1ac8"),
        ("f4:91:1e:3f:1a:c8", "f4911e3f1ac8", "f4911e3f1ac8"),
        ("F4-91-1E-3F-1A-C8", "f4911e3f1ac8", "f4911e3f1ac8"),
        ("  f4911e3f1ac8  ", "f4911e3f1ac8", "f4911e3f1ac8"),
        # A VRF unit from discovery: 14 characters ending in "00".
        ("9424b8fd5ba300", "9424b8fd5ba300", "9424b8fd5ba3"),
        ("9424B8FD5BA300", "9424b8fd5ba300", "9424b8fd5ba3"),
        # An imported config: sub MAC, then the controller MAC.
        ("9424b8fd5ba301@9424b8fd5ba3", "9424b8fd5ba301", "9424b8fd5ba3"),
        ("9424B8FD5BA301@9424B8FD5BA3", "9424b8fd5ba301", "9424b8fd5ba3"),
    ],
)
def test_extract_macs(raw: str, expected_mac: str, expected_controller: str) -> None:
    """Talking to a device needs the device MAC and the controller MAC."""
    assert gree_extract_macs(raw) == (expected_mac, expected_controller)


def test_extract_macs_leaves_a_long_mac_that_does_not_end_in_zeroes() -> None:
    """Only the "00" ending marks a VRF sub-device, so nothing else is split."""
    assert gree_extract_macs("9424b8fd5ba301") == (
        "9424b8fd5ba301",
        "9424b8fd5ba301",
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("V1sT9p0aQ3zXcR7m", "V1sT9[redacted]"),
        ("", "[no_key]"),
        ("   ", "[no_key]"),
        (None, "[no_key]"),
    ],
)
def test_redact_str(value: str | None, expected: str) -> None:
    """A key never reaches a log line whole."""
    assert redact_str(value) == expected


def test_chunked_splits_and_keeps_the_rest() -> None:
    """The last chunk is whatever is left."""
    assert list(chunked(range(7), 3)) == [[0, 1, 2], [3, 4, 5], [6]]


def test_chunked_on_an_empty_iterable() -> None:
    """Nothing in, nothing out."""
    assert not list(chunked([], 3))
