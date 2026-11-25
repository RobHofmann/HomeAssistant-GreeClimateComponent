"""Tests for `_controller_label`, the model and name of a VRF controller device.

Without a bound sub-unit the controller info is Undefined. From Home Assistant
2026.12 on, Undefined is a sentinel object and not a type, so the helper must
compare by identity. These tests run on the minimum version, so one of them
swaps in a sentinel of the 2026.12 shape.
"""

# pylint: disable=protected-access
# The helpers under test are private to helpers.py. They are tested directly
# because the setup path that calls them needs a VRF gateway.

import pytest
from typing_extensions import Sentinel

from custom_components.gree_custom import helpers
from custom_components.gree_custom.const import (
    VRF_CONTROLLER_MODEL,
    VRF_CONTROLLER_TRANSLATION_KEY,
    ZONE_CONTROLLER_MODEL,
    ZONE_CONTROLLER_TRANSLATION_KEY,
)

CONTROLLER_MAC = "c03937a1beef"

ControllerInfo = helpers._ControllerInfo  # noqa: SLF001
controller_label = helpers._controller_label  # noqa: SLF001


def _undefined_info() -> ControllerInfo:
    """Return the controller info as it is without a bound sub-unit."""
    undefined = helpers.Undefined
    return ControllerInfo(undefined, undefined, undefined, undefined)


def test_a_known_controller_gets_its_own_label() -> None:
    """A bound sub-unit tells the kind of controller."""
    info = ControllerInfo(
        "1.0", "abc", ZONE_CONTROLLER_MODEL, ZONE_CONTROLLER_TRANSLATION_KEY
    )

    assert controller_label(info, CONTROLLER_MAC, exists=True) == {
        "model": ZONE_CONTROLLER_MODEL,
        "translation_key": ZONE_CONTROLLER_TRANSLATION_KEY,
        "translation_placeholders": {"mac": "1beef"},
    }


def test_an_existing_controller_without_info_keeps_its_label() -> None:
    """Nothing is returned, so the registry keeps the model and name it has."""
    assert controller_label(_undefined_info(), CONTROLLER_MAC, True) == {}


def test_a_new_controller_without_info_gets_the_vrf_label() -> None:
    """A new device needs a name, so it gets the VRF label."""
    assert controller_label(_undefined_info(), CONTROLLER_MAC, False) == {
        "model": VRF_CONTROLLER_MODEL,
        "translation_key": VRF_CONTROLLER_TRANSLATION_KEY,
        "translation_placeholders": {"mac": "1beef"},
    }


@pytest.mark.parametrize("exists", [True, False])
def test_the_label_works_with_a_sentinel_that_is_not_a_type(
    monkeypatch: pytest.MonkeyPatch, exists: bool
) -> None:
    """Home Assistant 2026.12 makes Undefined a sentinel object.

    isinstance() with that object raises TypeError, so this fails if the
    helper goes back to a type check.
    """
    sentinel = Sentinel("Undefined")
    assert not isinstance(sentinel, type)
    monkeypatch.setattr(helpers, "Undefined", sentinel)

    label = controller_label(_undefined_info(), CONTROLLER_MAC, exists)

    assert label == (
        {}
        if exists
        else {
            "model": VRF_CONTROLLER_MODEL,
            "translation_key": VRF_CONTROLLER_TRANSLATION_KEY,
            "translation_placeholders": {"mac": "1beef"},
        }
    )
