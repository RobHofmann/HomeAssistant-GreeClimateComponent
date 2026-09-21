"""Tests for the helpers: temperature math, humidity math and pack wrapping.

Pure functions, no socket. The temperature encoding is the part users notice
first when it is wrong, so every branch of it is covered here.
"""

from aiogree.cipher import EncryptionVersion, get_cipher
from aiogree.const import (
    MAX_HUM_COOL_P,
    MAX_TEMP_C,
    MAX_TEMP_F,
    MIN_HUM_COOL_P,
    MIN_HUM_DRY_P,
    MIN_TEMP_C,
    MIN_TEMP_F,
)
from aiogree.errors import GreeError
from aiogree.helpers import (
    TempOffsetResolver,
    gree_decrypt_pack,
    gree_encrypt_pack,
    gree_get_target_humidity_p,
    gree_get_target_humidity_prop_from_p,
    gree_get_target_temp_props_from_c,
    gree_get_target_temp_props_from_f,
    gree_get_target_temperature_c,
    gree_get_target_temperature_f,
)
import pytest

from .conftest import RecordingHandler


@pytest.mark.parametrize(
    ("celsius", "set_tem", "tem_rec"),
    [
        (21.0, 21, 0),
        (21.5, 21, 1),
        (16.0, 16, 0),
        (30.0, 30, 0),
        # 21.3 is not a half step, so it rounds to the nearest one.
        (21.3, 21, 1),
        (21.2, 21, 0),
    ],
)
def test_celsius_to_props(celsius: float, set_tem: int, tem_rec: int) -> None:
    """SetTem holds the whole degrees and TemRec holds the half degree."""
    assert gree_get_target_temp_props_from_c(celsius) == (set_tem, tem_rec)


@pytest.mark.parametrize(
    ("celsius", "expected"),
    [(MAX_TEMP_C + 5, MAX_TEMP_C), (MIN_TEMP_C - 5, MIN_TEMP_C)],
)
def test_celsius_is_clamped_to_the_device_range(celsius: float, expected: int) -> None:
    """A value outside the range is clamped, with a warning."""
    assert gree_get_target_temp_props_from_c(celsius)[0] == expected


@pytest.mark.parametrize(
    ("set_tem", "tem_rec", "expected"),
    [(21, 0, 21.0), (21, 1, 21.5), (16, 0, 16.0)],
)
def test_props_to_celsius(set_tem: int, tem_rec: int, expected: float) -> None:
    """The two props go back to one temperature."""
    assert gree_get_target_temperature_c(set_tem, tem_rec) == expected


@pytest.mark.parametrize("fahrenheit", [61, 65, 70, 75, 80, 86])
def test_fahrenheit_survives_a_round_trip(fahrenheit: int) -> None:
    """Fahrenheit is stored as Celsius plus a bit, and has to come back whole."""
    set_tem, tem_rec = gree_get_target_temp_props_from_f(fahrenheit)

    assert gree_get_target_temperature_f(set_tem, tem_rec) == fahrenheit


@pytest.mark.parametrize(
    ("fahrenheit", "expected"),
    [(MAX_TEMP_F + 10, MAX_TEMP_F), (MIN_TEMP_F - 10, MIN_TEMP_F)],
)
def test_fahrenheit_is_clamped_to_the_device_range(
    fahrenheit: int, expected: int
) -> None:
    """A value outside the range is clamped before it is encoded."""
    set_tem, tem_rec = gree_get_target_temp_props_from_f(fahrenheit)

    assert gree_get_target_temperature_f(set_tem, tem_rec) == expected


@pytest.mark.parametrize(
    ("percentage", "expected_prop"),
    [(40, 5), (45, 6), (80, 13)],
)
def test_humidity_percentage_to_prop(percentage: int, expected_prop: int) -> None:
    """The device stores humidity in steps of 5 percent, starting at 15."""
    assert (
        gree_get_target_humidity_prop_from_p(percentage, MIN_HUM_COOL_P, MAX_HUM_COOL_P)
        == expected_prop
    )


def test_humidity_prop_to_percentage() -> None:
    """And back again."""
    assert gree_get_target_humidity_p(6) == 45


def test_humidity_is_rounded_to_a_multiple_of_five(
    gree_logs: RecordingHandler,
) -> None:
    """43 percent is not a step the device knows, so it becomes 45."""
    value = gree_get_target_humidity_prop_from_p(43, MIN_HUM_COOL_P, MAX_HUM_COOL_P)

    assert gree_get_target_humidity_p(value) == 45
    assert any("multiple of 5" in line for line in gree_logs.warnings())


@pytest.mark.parametrize(
    ("percentage", "expected"),
    [(95, MAX_HUM_COOL_P), (10, MIN_HUM_COOL_P)],
)
def test_humidity_is_clamped(percentage: int, expected: int) -> None:
    """Outside the range for the mode, the value is clamped."""
    value = gree_get_target_humidity_prop_from_p(
        percentage, MIN_HUM_COOL_P, MAX_HUM_COOL_P
    )

    assert gree_get_target_humidity_p(value) == expected


def test_humidity_range_differs_per_mode() -> None:
    """Dry mode starts lower than Cool mode."""
    value = gree_get_target_humidity_prop_from_p(30, MIN_HUM_DRY_P, MAX_HUM_COOL_P)

    assert gree_get_target_humidity_p(value) == MIN_HUM_DRY_P


def test_temp_offset_resolver_sees_a_plain_sensor() -> None:
    """A room temperature that is plausible as it is needs no correction."""
    resolver = TempOffsetResolver()

    assert resolver.evaluate(21) == 21


def test_temp_offset_resolver_sees_an_offset_sensor() -> None:
    """61 degrees indoors is not real, so this sensor reports Celsius plus 40."""
    resolver = TempOffsetResolver()

    assert resolver.evaluate(61) == 21


def test_temp_offset_resolver_can_change_its_mind() -> None:
    """It keeps the lowest and highest value seen, so late data still counts."""
    resolver = TempOffsetResolver()
    resolver.evaluate(25)

    assert resolver.evaluate(65) == 25


def test_encrypt_pack_needs_a_cipher() -> None:
    """A payload must never go out unencrypted by accident."""
    with pytest.raises(GreeError, match="Cipher must not be None"):
        gree_encrypt_pack({"pack": {"t": "scan"}}, None)  # type: ignore[arg-type]


def test_decrypt_pack_needs_a_cipher() -> None:
    """Same on the way back."""
    with pytest.raises(GreeError, match="Cipher must not be None"):
        gree_decrypt_pack({"pack": "abc"}, None)  # type: ignore[arg-type]


def test_a_payload_without_a_pack_is_left_alone() -> None:
    """A scan request has no pack, so there is nothing to encrypt."""
    cipher = get_cipher(EncryptionVersion.V1)

    assert gree_encrypt_pack({"t": "scan"}, cipher) == {"t": "scan"}
    assert gree_decrypt_pack({"t": "scan"}, cipher) == {"t": "scan"}


def test_a_pack_over_the_size_limit_is_warned_about(
    gree_logs: RecordingHandler,
) -> None:
    """Over about 512 bytes the device stops answering, so this has to be loud."""
    cipher = get_cipher(EncryptionVersion.V1)
    payload = {"pack": {"t": "status", "cols": [f"Column{i:03d}" for i in range(60)]}}

    gree_encrypt_pack(payload, cipher)

    assert any("Pack length is over" in line for line in gree_logs.warnings())


def test_a_pack_survives_encrypt_and_decrypt() -> None:
    """The pack comes back as the same dict."""
    cipher = get_cipher(EncryptionVersion.V2, "0123456789abcdef")
    original = {"t": "status", "mac": "f4911e3f1ac8", "cols": ["Pow"]}

    encrypted = gree_encrypt_pack({"pack": dict(original)}, cipher)

    assert isinstance(encrypted["pack"], str)
    assert "tag" in encrypted
    assert gree_decrypt_pack(encrypted, cipher)["pack"] == original
