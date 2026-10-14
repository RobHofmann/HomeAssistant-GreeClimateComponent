"""Tests for the target temperature remembered per mode.

The wall panel of a zone controller recalls the target temperature of every
zone per mode when the mode is changed on the panel. A mode change over WiFi
does not, so `SetpointMemory` does it. See docs/protocol.md.
"""

# pylint: disable=redefined-outer-name
# A test takes a fixture as an argument with the same name. That is the
# pytest pattern, not shadowing.

from collections.abc import AsyncIterator

from aiogree.api import GreeProp, OperationMode
from aiogree.device import GreeDevice
from aiogree.setpoint_memory import SetpointMemory
from aiogree.transport_udp import GreeUdpTransport
import pytest

from .fakes.zone import FakeZoneController

HEAT = 2
COOL = 1


@pytest.fixture
async def controller() -> AsyncIterator[FakeZoneController]:
    """Start a fake zone controller with four zones."""
    fake = FakeZoneController()
    await fake.start()
    try:
        yield fake
    finally:
        fake.close()


@pytest.fixture
async def transport(
    controller: FakeZoneController,
) -> AsyncIterator[GreeUdpTransport]:
    """One transport for all units of the controller, as Home Assistant does."""
    shared = GreeUdpTransport(
        controller.host, controller.port, max_retries=1, timeout=0.3
    )
    try:
        yield shared
    finally:
        await shared.disconnect()


async def bind(
    controller: FakeZoneController, transport: GreeUdpTransport, mac: str
) -> GreeDevice:
    """Bind one sub-unit of the controller."""
    device = GreeDevice(name=mac[-2:], mac_addr=mac)
    await device.bind_with_transport(
        local_controller_mac=controller.mac, local_transport=transport
    )
    return device


@pytest.fixture
async def zones(
    controller: FakeZoneController, transport: GreeUdpTransport
) -> list[GreeDevice]:
    """Bind the four zones."""
    return [await bind(controller, transport, mac) for mac in controller.zone_macs]


def panel_mode(
    controller: FakeZoneController, mode: int, temperatures: list[int]
) -> None:
    """Change the mode on the wall panel. The panel sets its stored temperatures."""
    for unit in controller.units.values():
        unit["Mod"] = mode
    for zone_mac, temperature in zip(controller.zone_macs, temperatures, strict=True):
        controller.units[zone_mac]["StTem"] = temperature - 16


def set_on_panel(controller: FakeZoneController, temperatures: list[int]) -> None:
    """Change the target temperatures on the wall panel, in the current mode."""
    for zone_mac, temperature in zip(controller.zone_macs, temperatures, strict=True):
        controller.units[zone_mac]["StTem"] = temperature - 16


async def poll(memory: SetpointMemory, devices: list[GreeDevice]) -> None:
    """One poll of every device, as the coordinators do."""
    for device in devices:
        await device.fetch_device_status()
        memory.learn(device)


def remembered(
    memory: SetpointMemory, zones: list[GreeDevice], mode: OperationMode
) -> list[int | None]:
    """Return what the memory has for each zone in one mode, in degrees Celsius."""
    out: list[int | None] = []
    for zone in zones:
        raw = memory.stored(zone.mac_address, mode).get(GreeProp.TARGET_TEMPERATURE_2)
        out.append(None if raw is None else raw + 16)
    return out


def temperatures(controller: FakeZoneController) -> list[int]:
    """Return the target temperatures the controller has now."""
    return [controller.units[z]["StTem"] + 16 for z in controller.zone_macs]


async def test_a_value_is_stored_once_the_mode_is_seen_twice(
    zones: list[GreeDevice],
) -> None:
    """The first poll after start only notes the mode."""
    changes: list[int] = []
    memory = SetpointMemory(on_change=lambda: changes.append(1))

    await poll(memory, zones)
    assert memory.data == {}

    await poll(memory, zones)
    assert remembered(memory, zones, OperationMode.fan) == [18, 18, 18, 18]
    assert changes


async def test_the_raw_columns_are_stored_per_device(
    controller: FakeZoneController, zones: list[GreeDevice]
) -> None:
    """Keyed by device and mode, with the raw column, so no unit conversion is needed."""
    memory = SetpointMemory()
    await poll(memory, zones)
    await poll(memory, zones)

    assert memory.data[controller.zone_macs[0]] == {"fan": {"StTem": 2, "StFahFlg": 0}}


async def test_a_unit_without_target_temperature_columns_is_ignored(
    controller: FakeZoneController, transport: GreeUdpTransport
) -> None:
    """The ducted unit has no target temperature, so there is nothing to remember."""
    ac_unit = await bind(controller, transport, controller.ac_unit)
    memory = SetpointMemory()

    await poll(memory, [ac_unit])
    await poll(memory, [ac_unit])

    assert memory.data == {}


async def test_a_mode_change_on_the_panel_is_stored_under_the_new_mode(
    controller: FakeZoneController, zones: list[GreeDevice]
) -> None:
    """The poll that first sees the new mode stores nothing, the next one does."""
    memory = SetpointMemory()
    set_on_panel(controller, [19, 20, 18, 20])
    await poll(memory, zones)
    await poll(memory, zones)

    panel_mode(controller, HEAT, [19, 18, 17, 20])
    await poll(memory, zones)

    assert remembered(memory, zones, OperationMode.heat) == [None] * 4

    await poll(memory, zones)

    assert remembered(memory, zones, OperationMode.heat) == [19, 18, 17, 20]
    assert remembered(memory, zones, OperationMode.fan) == [19, 20, 18, 20]


async def test_recall_sends_the_stored_values_of_the_new_mode(
    controller: FakeZoneController, zones: list[GreeDevice]
) -> None:
    """A mode change over WiFi keeps the old values. Recall puts the stored ones back."""
    memory = SetpointMemory(
        {
            controller.zone_macs[0]: {"heat": {"StTem": 3, "StFahFlg": 0}},
            controller.zone_macs[2]: {"heat": {"StTem": 1, "StFahFlg": 0}},
        }
    )
    await poll(memory, zones)

    changed = await memory.recall(zones, OperationMode.heat)

    assert temperatures(controller) == [19, 18, 17, 18]
    assert [zone.mac_address for zone in changed] == [
        controller.zone_macs[0],
        controller.zone_macs[2],
    ]


async def test_recall_of_a_mode_without_values_changes_nothing(
    controller: FakeZoneController, zones: list[GreeDevice]
) -> None:
    """Nothing is known about Dry yet, so the zones keep what they have."""
    memory = SetpointMemory()
    await poll(memory, zones)
    controller.reset_record()

    changed = await memory.recall(zones, OperationMode.dry)

    assert changed == []
    assert not any(pack.get("t") == "cmd" for pack in controller.packs)


async def test_a_fahrenheit_target_comes_back_with_its_bit(
    controller: FakeZoneController, zones: list[GreeDevice]
) -> None:
    """67 F is StTem 3 with StFahFlg 1. Without the bit, recall would give 66 F."""
    for values in controller.units.values():
        values["TemUnit"] = 1
    first = controller.units[controller.zone_macs[0]]
    first.update({"StTem": 3, "StFahFlg": 1})
    memory = SetpointMemory()
    await poll(memory, zones)
    await poll(memory, zones)

    panel_mode(controller, HEAT, [19, 18, 18, 18])
    first["StFahFlg"] = 0
    await poll(memory, zones)
    await memory.recall(zones, OperationMode.fan)

    assert (first["StTem"], first["StFahFlg"]) == (3, 1)
    assert zones[0].target_temperature == 67


async def test_snapshot_keeps_a_panel_change_made_since_the_last_poll(
    controller: FakeZoneController, zones: list[GreeDevice]
) -> None:
    """The value changed on the panel just before the switch is not lost."""
    memory = SetpointMemory()
    await poll(memory, zones)
    await poll(memory, zones)

    set_on_panel(controller, [22, 18, 18, 18])
    await memory.snapshot(zones, OperationMode.fan)

    assert remembered(memory, zones, OperationMode.fan) == [22, 18, 18, 18]


async def test_snapshot_does_not_store_values_of_another_mode(
    controller: FakeZoneController, zones: list[GreeDevice]
) -> None:
    """If the mode already changed on the panel, the values are not the old mode's."""
    memory = SetpointMemory()
    panel_mode(controller, COOL, [24, 24, 24, 24])

    await memory.snapshot(zones, OperationMode.fan)

    assert remembered(memory, zones, OperationMode.fan) == [None] * 4
