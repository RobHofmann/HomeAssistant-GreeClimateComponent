"""The target temperature per mode, through the climate entity of a real Home Assistant.

The memory itself is tested in tests/test_setpoint_memory.py. This checks what a
service call does with it.
"""

import pytest

from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    MAJOR_VERSION,
    MINOR_VERSION,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from tests.config_flow.conftest import MAC_A, GreeEnv, add_entry

# The climate entity uses the native temperature API of Home Assistant 2026.11
# (#570). The test plugin is still pinned to 2026.10, where the entity cannot
# be created, so this runs once the pin moves to 2026.11.
pytestmark = pytest.mark.skipif(
    (MAJOR_VERSION, MINOR_VERSION) < (2026, 11),
    reason="the climate entity needs Home Assistant 2026.11",
)


async def test_set_temperature_with_a_mode_keeps_the_given_temperature(
    hass: HomeAssistant, gree: GreeEnv
) -> None:
    """A temperature given with the mode wins over the remembered one."""
    fake = gree.devices[MAC_A]
    fake.values.update({"Pow": 1, "Mod": 1, "SetTem": 24, "TemRec": 0, "TemUn": 0})
    host = await gree.start_udp(fake)
    entry = await add_entry(hass, ["local"], [MAC_A], [host])
    coordinator = next(iter(entry.runtime_data.values()))
    memory = coordinator.setpoint_memory
    assert memory is not None

    async def poll() -> None:
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    # Heat 20 and Cool 24, as set with the remote
    fake.values.update({"Mod": 4, "SetTem": 20})
    await poll()
    await poll()
    fake.values.update({"Mod": 1, "SetTem": 24})
    await poll()
    await poll()

    climate = next(
        e.entity_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        if e.domain == CLIMATE_DOMAIN
    )
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_temperature",
        {ATTR_ENTITY_ID: climate, ATTR_TEMPERATURE: 22, "hvac_mode": "heat"},
        blocking=True,
    )

    assert (fake.values["Mod"], fake.values["SetTem"]) == (4, 22)
    assert memory.data[MAC_A]["cool"]["SetTem"] == 24
