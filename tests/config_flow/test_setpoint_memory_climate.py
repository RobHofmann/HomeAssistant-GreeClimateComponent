"""The target temperature per mode, through the climate entity of a real Home Assistant.

The memory itself is tested in tests/test_setpoint_memory.py. This checks that
the coordinators feed it from their reads, what a mode change does with it, for
a standalone unit and for the zones of a zone controller, and that the climate
entity keeps it over a reload and a restart.
"""

import pytest

from custom_components.gree_custom.coordinator import GreeCoordinator
from custom_components.gree_custom.setpoint_memory import SetpointMemory
from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    MAJOR_VERSION,
    MINOR_VERSION,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, restore_state
from tests.config_flow.conftest import MAC_A, GreeEnv, add_entry
from tests.fakes.device import FakeGreeDevice
from tests.fakes.zone import FakeZoneController

# The climate entity uses the native temperature API of Home Assistant 2026.11
# (#570). The test plugin is still pinned to 2026.10, where the entity cannot
# be created, so this runs once the pin moves to 2026.11.
pytestmark = pytest.mark.skipif(
    (MAJOR_VERSION, MINOR_VERSION) < (2026, 11),
    reason="the climate entity needs Home Assistant 2026.11",
)

COOL_24 = {"temperature": 24.0, "unit": "C"}
HEAT_20 = {"temperature": 20.0, "unit": "C"}


async def add_unit(
    hass: HomeAssistant, gree: GreeEnv
) -> tuple[FakeGreeDevice, ConfigEntry, GreeCoordinator]:
    """Add a standalone unit that is in Cool at 24 degrees."""
    fake = gree.devices[MAC_A]
    fake.values.update({"Pow": 1, "Mod": 1, "SetTem": 24, "TemRec": 0, "TemUn": 0})
    host = await gree.start_udp(fake)
    entry = await add_entry(hass, ["local"], [MAC_A], [host])
    return fake, entry, next(iter(entry.runtime_data.values()))


async def poll(hass: HomeAssistant, coordinator: GreeCoordinator) -> None:
    """One poll, as the update interval does."""
    await coordinator.async_refresh()
    await hass.async_block_till_done()


async def learn_heat_and_cool(
    hass: HomeAssistant, fake: FakeGreeDevice, coordinator: GreeCoordinator
) -> None:
    """Heat 20 and then Cool 24, as set with the remote, each seen on two polls."""
    fake.values.update({"Mod": 4, "SetTem": 20})
    await poll(hass, coordinator)
    await poll(hass, coordinator)
    fake.values.update({"Mod": 1, "SetTem": 24})
    await poll(hass, coordinator)
    await poll(hass, coordinator)


def memory_of(entry: ConfigEntry) -> SetpointMemory:
    """Return the setpoint memory of the unit of the entry."""
    memory = next(iter(entry.runtime_data.values())).setpoint_memory
    assert memory is not None
    return memory


def climate_of(hass: HomeAssistant, entry: ConfigEntry) -> str:
    """Return the entity id of the climate entity of the entry."""
    return next(
        e.entity_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        if e.domain == CLIMATE_DOMAIN
    )


async def test_a_change_on_the_device_is_learned_from_the_polls(
    hass: HomeAssistant, gree: GreeEnv
) -> None:
    """A mode set with the remote is stored on the second poll that sees it."""
    fake, _, coordinator = await add_unit(hass, gree)
    memory = coordinator.setpoint_memory
    assert memory is not None

    fake.values.update({"Mod": 4, "SetTem": 20})
    await poll(hass, coordinator)
    # Updates of the entities are not reads
    coordinator.async_update_listeners()
    coordinator.async_update_listeners()
    assert "heat" not in memory.data.get(MAC_A, {})

    await poll(hass, coordinator)
    assert memory.data[MAC_A]["heat"] == HEAT_20

    # Changed with the remote, in the same mode
    fake.values["SetTem"] = 21
    await poll(hass, coordinator)
    assert memory.data[MAC_A]["heat"] == {"temperature": 21.0, "unit": "C"}


async def test_set_temperature_with_a_mode_keeps_the_given_temperature(
    hass: HomeAssistant, gree: GreeEnv
) -> None:
    """A temperature given with the mode wins over the remembered one."""
    fake, entry, coordinator = await add_unit(hass, gree)
    await learn_heat_and_cool(hass, fake, coordinator)

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_temperature",
        {
            ATTR_ENTITY_ID: climate_of(hass, entry),
            ATTR_TEMPERATURE: 22,
            "hvac_mode": "heat",
        },
        blocking=True,
    )

    assert (fake.values["Mod"], fake.values["SetTem"]) == (4, 22)
    assert memory_of(entry).data[MAC_A]["cool"] == COOL_24


async def test_the_memory_is_kept_over_a_reload_and_a_restart(
    hass: HomeAssistant, gree: GreeEnv
) -> None:
    """The climate entity keeps it in its restore state."""
    fake, entry, coordinator = await add_unit(hass, gree)
    await learn_heat_and_cool(hass, fake, coordinator)
    learned = {MAC_A: {"cool": COOL_24, "heat": HEAT_20}}
    assert memory_of(entry).data == learned

    # The entity that is removed hands its data to the new one
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert memory_of(entry).data == learned

    # Saved to storage on a stop, and loaded from it on the next start
    restored = restore_state.async_get(hass)
    await restored.async_dump_states()
    assert await hass.config_entries.async_unload(entry.entry_id)
    await restored.async_load()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert memory_of(entry).data == learned

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_hvac_mode",
        {ATTR_ENTITY_ID: climate_of(hass, entry), "hvac_mode": "heat"},
        blocking=True,
    )
    assert (fake.values["Mod"], fake.values["SetTem"]) == (4, 20)


async def test_a_mode_change_sets_the_zones_as_the_wall_panel_does(
    hass: HomeAssistant, gree: GreeEnv
) -> None:
    """The zones learn into the memory of the ducted unit, whose mode change sets them."""
    controller = FakeZoneController()
    gree.devices["zone_controller"] = controller
    host = await gree.start_udp(controller)
    entry = await add_entry(
        hass, ["local"], [controller.ac_unit, *controller.zone_macs], [host]
    )
    coordinators = list(entry.runtime_data.values())
    first = controller.units[controller.zone_macs[0]]

    async def poll_all() -> None:
        for coordinator in coordinators:
            await poll(hass, coordinator)

    # Fan with every zone at 18, then Heat with the first zone at 21, on the panel
    await poll_all()
    await poll_all()
    for unit in controller.units.values():
        unit["Mod"] = 2
    first["StTem"] = 21 - 16
    await poll_all()
    await poll_all()

    for hvac_mode, expected in (("fan_only", 18), ("heat", 21)):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            "set_hvac_mode",
            {ATTR_ENTITY_ID: climate_of(hass, entry), "hvac_mode": hvac_mode},
            blocking=True,
        )
        assert first["StTem"] + 16 == expected, hvac_mode
