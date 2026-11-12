"""Tests for `get_device_by_identifier`, the device registry lookup by owner.

The helper calls `async_get_device_by_identifier`, which only returns a device
of the given config entry.
"""

# pylint: disable=redefined-outer-name
# A test takes a fixture as an argument with the same name. That is the
# pytest pattern, not shadowing.

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.gree_custom.const import DOMAIN
from custom_components.gree_custom.helpers import get_device_by_identifier
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

MAC = "c03937a10001"
IDENTIFIER = (DOMAIN, MAC)


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


async def test_the_lookup_finds_the_device_of_its_owner(
    hass: HomeAssistant, entries: tuple[MockConfigEntry, MockConfigEntry]
) -> None:
    """A device of another entry, or an unknown identifier, gives None."""
    owner, other = entries
    registry = dr.async_get(hass)

    device = get_device_by_identifier(registry, IDENTIFIER, owner.entry_id)
    assert device is not None
    assert IDENTIFIER in device.identifiers

    assert get_device_by_identifier(registry, IDENTIFIER, other.entry_id) is None
    assert (
        get_device_by_identifier(registry, (DOMAIN, "000000000000"), owner.entry_id)
        is None
    )
