"""Tests for `get_device_by_identifier`, the device registry lookup by owner.

Home Assistant 2026.8 added `async_get_device_by_identifier`. Older versions,
down to the 2026.3 floor of this repo, only have `async_get_device`. The
helper uses the new call when it is there, and otherwise the old call with an
owner check. The first branch runs against the real registry of the Home
Assistant in the test. The second needs an older registry, so a small stand-in
without the new method serves the rows of the real one.
"""

# pylint: disable=redefined-outer-name
# A test takes a fixture as an argument with the same name. That is the
# pytest pattern, not shadowing.

from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.gree_custom.const import DOMAIN
from custom_components.gree_custom.helpers import get_device_by_identifier
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

MAC = "c03937a10001"
IDENTIFIER = (DOMAIN, MAC)


class OldRegistry:
    """A device registry as Home Assistant before 2026.8 has it.

    It has `async_get_device` and no `async_get_device_by_identifier`. The
    rows come from the real registry.
    """

    def __init__(self, registry: dr.DeviceRegistry, entry_ids: list[str]) -> None:
        """Serve the devices of these entries."""
        self._registry = registry
        self._entry_ids = entry_ids

    def async_get_device(self, identifiers: set[tuple[str, str]]) -> Any:
        """Return the first device with one of the identifiers."""
        for entry_id in self._entry_ids:
            for device in dr.async_entries_for_config_entry(self._registry, entry_id):
                if identifiers & device.identifiers:
                    return device
        return None


@pytest.fixture
def entries(hass: HomeAssistant) -> tuple[MockConfigEntry, MockConfigEntry]:
    """Two entries. The first one owns the device."""
    owner = MockConfigEntry(domain=DOMAIN, unique_id="owner")
    other = MockConfigEntry(domain=DOMAIN, unique_id="other")
    owner.add_to_hass(hass)
    other.add_to_hass(hass)

    dr.async_get(hass).async_get_or_create(
        config_entry_id=owner.entry_id, identifiers={IDENTIFIER}
    )
    return owner, other


async def test_the_new_lookup_finds_the_device_of_its_owner(
    hass: HomeAssistant, entries: tuple[MockConfigEntry, MockConfigEntry]
) -> None:
    """The Home Assistant of this test has the new call, so it is used."""
    owner, other = entries
    registry = dr.async_get(hass)
    assert hasattr(registry, "async_get_device_by_identifier")

    device = get_device_by_identifier(registry, IDENTIFIER, owner.entry_id)
    assert device is not None
    assert IDENTIFIER in device.identifiers

    assert get_device_by_identifier(registry, IDENTIFIER, other.entry_id) is None
    assert (
        get_device_by_identifier(registry, (DOMAIN, "000000000000"), owner.entry_id)
        is None
    )


async def test_the_old_lookup_checks_the_owner(
    hass: HomeAssistant, entries: tuple[MockConfigEntry, MockConfigEntry]
) -> None:
    """Without the new call, a device of another entry gives None."""
    owner, other = entries
    registry = OldRegistry(dr.async_get(hass), [owner.entry_id, other.entry_id])
    assert not hasattr(registry, "async_get_device_by_identifier")

    device = get_device_by_identifier(registry, IDENTIFIER, owner.entry_id)  # type: ignore[arg-type]
    assert device is not None
    assert device in dr.async_entries_for_config_entry(
        dr.async_get(hass), owner.entry_id
    )

    assert (
        get_device_by_identifier(registry, IDENTIFIER, other.entry_id)  # type: ignore[arg-type]
        is None
    )
    assert (
        get_device_by_identifier(registry, (DOMAIN, "000000000000"), owner.entry_id)  # type: ignore[arg-type]
        is None
    )
