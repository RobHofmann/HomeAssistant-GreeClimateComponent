"""Tests for a zone controller: a ducted unit and its zones behind one WiFi module.

A zone controller is a gateway like a VRF gateway, but its sub-units are not
indoor units. Sub-unit `00` is the ducted unit, which numbers its modes in its
own way and has turbo as a fan speed. The other sub-units are zones, with an
on/off state and a target temperature. See docs/protocol.md.
"""

# pylint: disable=redefined-outer-name
# A test takes a fixture as an argument with the same name. That is the
# pytest pattern, not shadowing.

from collections.abc import AsyncIterator

from aiogree.api import (
    DeviceType,
    FanSpeed,
    GreeProp,
    OperationMode,
    SubListForm,
    TemperatureUnits,
)
from aiogree.device import GreeDevice
from aiogree.errors import GreeTurboUnavailable
from aiogree.transport_udp import GreeUdpTransport
import pytest

from .conftest import DISCOVERY_PORT, DiscoverOne, RecordingHandler
from .fakes.device import FakeGreeDevice
from .fakes.vrf import FakeVrfGateway
from .fakes.zone import ZONE_CONTROLLER_MAC, FakeZoneController


@pytest.fixture
async def controller() -> AsyncIterator[FakeZoneController]:
    """Start a fake zone controller with four zones."""
    fake = FakeZoneController()
    await fake.start()
    try:
        yield fake
    finally:
        fake.close()


async def bind_unit(
    gateway: FakeGreeDevice, suffix: str
) -> tuple[GreeDevice, GreeUdpTransport]:
    """Bind the sub-unit with this MAC suffix behind the gateway."""
    transport = GreeUdpTransport(gateway.host, gateway.port, max_retries=1, timeout=0.3)
    device = GreeDevice(name=f"Unit {suffix}", mac_addr=f"{gateway.mac}{suffix}")
    await device.bind_with_transport(
        local_controller_mac=gateway.mac, local_transport=transport
    )
    return device, transport


@pytest.fixture
async def ac_unit(controller: FakeZoneController) -> AsyncIterator[GreeDevice]:
    """Bind the ducted unit of the zone controller."""
    device, transport = await bind_unit(controller, "00")
    try:
        yield device
    finally:
        await transport.disconnect()


@pytest.fixture
async def zone(controller: FakeZoneController) -> AsyncIterator[GreeDevice]:
    """Bind zone 1 of the zone controller."""
    device, transport = await bind_unit(controller, "01")
    try:
        yield device
    finally:
        await transport.disconnect()


#
# Discovery
#


async def test_discovery_names_the_ducted_unit_and_the_zones(
    loopback_ip: str, discover_one: DiscoverOne, gree_logs: RecordingHandler
) -> None:
    """Every unit says "zone". Discovery names them from the model id and MAC."""
    controller = FakeZoneController()
    await controller.start(loopback_ip, DISCOVERY_PORT)
    try:
        found = await discover_one(controller.host, timeout=1)
    finally:
        controller.close()

    assert [(d.name, d.mac) for d in found] == [
        ("AC unit", f"{ZONE_CONTROLLER_MAC}00"),
        ("Zone 1", f"{ZONE_CONTROLLER_MAC}01"),
        ("Zone 2", f"{ZONE_CONTROLLER_MAC}02"),
        ("Zone 3", f"{ZONE_CONTROLLER_MAC}03"),
        ("Zone 4", f"{ZONE_CONTROLLER_MAC}04"),
    ]
    assert {d.mac_controller_local for d in found} == {ZONE_CONTROLLER_MAC}
    # The two subList forms get no answer, which the transport warns about.
    # Only the warnings about the sub-device list itself would be a problem.
    assert not any("sub-devices" in line for line in gree_logs.warnings())


async def test_discovery_names_come_from_the_controller_name_and_the_suffix(
    loopback_ip: str, discover_one: DiscoverOne
) -> None:
    """The model ids in the sub-device list are not used, only the name and the MAC."""

    class OtherIds(FakeZoneController):
        def sub_devices(self, form: SubListForm) -> list[dict[str, str]]:
            return [{**unit, "mid": "1234"} for unit in super().sub_devices(form)]

    controller = OtherIds()
    await controller.start(loopback_ip, DISCOVERY_PORT)
    try:
        found = await discover_one(controller.host, timeout=1)
    finally:
        controller.close()

    assert [d.name for d in found] == [
        "AC unit",
        "Zone 1",
        "Zone 2",
        "Zone 3",
        "Zone 4",
    ]


#
# The ducted unit
#


async def test_the_ducted_unit_is_recognised(ac_unit: GreeDevice) -> None:
    """The name in the info columns and the 00 suffix make it the ducted unit.

    It answers StTem too, always with 0, so the columns alone cannot tell it
    from a zone.
    """
    assert ac_unit.device_type is DeviceType.ZONE_CONTROLLER
    assert ac_unit.supports_property(GreeProp.ZONE_TARGET_TEMPERATURE)


async def test_the_device_type_is_in_the_diagnostics(
    ac_unit: GreeDevice, zone: GreeDevice
) -> None:
    """The type helps when a user sends diagnostics."""
    assert ac_unit.gather_diagnostics()["info"]["device_type"] == "zone_controller"
    assert zone.gather_diagnostics()["info"]["device_type"] == "zone"


@pytest.mark.parametrize(
    ("raw", "mode"),
    [
        (1, OperationMode.cool),
        (2, OperationMode.heat),
        (3, OperationMode.dry),
        (4, OperationMode.fan),
        (5, OperationMode.auto),
    ],
)
async def test_the_ducted_unit_reads_its_own_mode_numbers(
    controller: FakeZoneController, ac_unit: GreeDevice, raw: int, mode: OperationMode
) -> None:
    """Mode 4 is Fan, not Heat, and mode 5 (Auto) does not raise."""
    controller.units[controller.ac_unit]["Mod"] = raw

    await ac_unit.fetch_device_status()

    assert ac_unit.operation_mode is mode


async def test_the_ducted_unit_is_sent_its_own_mode_numbers(
    controller: FakeZoneController, ac_unit: GreeDevice
) -> None:
    """Heat goes out as 2, and the zones follow the ducted unit."""
    ac_unit.set_operation_mode(OperationMode.heat)

    await ac_unit.push_device_status()

    assert controller.units[controller.ac_unit]["Mod"] == 2
    assert controller.units[controller.zone_macs[0]]["Mod"] == 2
    assert ac_unit.operation_mode is OperationMode.heat


async def test_turbo_is_a_fan_speed(
    controller: FakeZoneController, ac_unit: GreeDevice
) -> None:
    """There is no turbo column. Turbo is fan speed 6."""
    controller.units[controller.ac_unit]["Mod"] = 1
    await ac_unit.fetch_device_status()
    assert ac_unit.supports_property(GreeProp.FEAT_TURBO_MODE)

    ac_unit.set_feature_turbo(True)
    await ac_unit.push_device_status()

    assert controller.units[controller.ac_unit]["WdSpd"] == 6
    assert ac_unit.feature_turbo is True
    assert ac_unit.fan_speed is FanSpeed.high

    ac_unit.set_feature_turbo(False)
    await ac_unit.push_device_status()

    assert controller.units[controller.ac_unit]["WdSpd"] == FanSpeed.high.value
    assert ac_unit.feature_turbo is False


async def test_turbo_is_refused_outside_cool_and_heat(ac_unit: GreeDevice) -> None:
    """The fake starts in Fan mode, where the panel offers no turbo either."""
    assert ac_unit.operation_mode is OperationMode.fan

    with pytest.raises(GreeTurboUnavailable):
        ac_unit.set_feature_turbo(True)


async def test_leaving_cool_ends_turbo(
    controller: FakeZoneController, ac_unit: GreeDevice
) -> None:
    """A mode without turbo gets the highest normal fan speed instead."""
    controller.units[controller.ac_unit].update({"Mod": 1, "WdSpd": 6})
    await ac_unit.fetch_device_status()

    ac_unit.set_operation_mode(OperationMode.fan)
    await ac_unit.push_device_status()

    assert controller.units[controller.ac_unit]["Mod"] == 4
    assert controller.units[controller.ac_unit]["WdSpd"] == FanSpeed.high.value


#
# Zones
#


async def test_a_zone_is_recognised_and_polls_its_target_temperature(
    controller: FakeZoneController, zone: GreeDevice
) -> None:
    """A zone asks for StTem and reads it as degrees Celsius minus 16."""
    assert zone.device_type is DeviceType.ZONE
    assert zone.supports_property(GreeProp.ZONE_TARGET_TEMPERATURE)
    assert zone.target_temperature == 18

    controller.units[controller.zone_macs[0]]["StTem"] = 5
    await zone.fetch_device_status()

    assert zone.target_temperature == 21


async def test_a_zone_target_temperature_is_sent_minus_16(
    controller: FakeZoneController, zone: GreeDevice
) -> None:
    """19 degrees goes out as 3, without SetTem, and values outside 16 to 30 are clamped."""
    controller.reset_record()
    zone.set_target_temperature(19)
    await zone.push_device_status()

    assert controller.units[controller.zone_macs[0]]["StTem"] == 3
    sent = {
        column
        for pack in controller.packs
        if pack.get("t") == "cmd"
        for column in pack["opt"]
    }
    assert "StTem" in sent
    assert not sent & {"SetTem", "TemRec"}

    zone.set_target_temperature(35)
    await zone.push_device_status()

    assert controller.units[controller.zone_macs[0]]["StTem"] == 14


#
# Fahrenheit. The values are the ones the wall panel showed.
#


def set_unit(controller: FakeZoneController, unit: TemperatureUnits) -> None:
    """Change the unit on the wall panel. Every unit of the controller follows."""
    for values in controller.units.values():
        values["TemUnit"] = unit.value


async def test_a_zone_in_fahrenheit_reads_its_bit_like_tem_rec(
    controller: FakeZoneController, zone: GreeDevice
) -> None:
    """StTem plus 16 and StFahFlg give the same Fahrenheit table as SetTem and TemRec."""
    set_unit(controller, TemperatureUnits.F)
    values = controller.units[controller.zone_macs[0]]
    seen = []
    for st_tem, bit in ((2, 0), (3, 0), (3, 1), (5, 1)):
        values.update({"StTem": st_tem, "StFahFlg": bit})
        await zone.fetch_device_status()
        seen.append(zone.target_temperature)

    assert zone.target_temperature_unit is TemperatureUnits.F
    assert seen == [64, 66, 67, 70]


async def test_a_zone_in_fahrenheit_is_sent_with_its_bit(
    controller: FakeZoneController, zone: GreeDevice
) -> None:
    """70 goes out as StTem 5 with StFahFlg 1, 66 as 3 with 0."""
    set_unit(controller, TemperatureUnits.F)
    await zone.fetch_device_status()
    values = controller.units[controller.zone_macs[0]]

    zone.set_target_temperature(70)
    await zone.push_device_status()
    assert (values["StTem"], values["StFahFlg"]) == (5, 1)

    zone.set_target_temperature(66)
    await zone.push_device_status()
    assert (values["StTem"], values["StFahFlg"]) == (3, 0)


async def test_a_celsius_target_clears_the_bit(
    controller: FakeZoneController, zone: GreeDevice
) -> None:
    """The controller keeps an old bit when only StTem comes, so it is always sent."""
    values = controller.units[controller.zone_macs[0]]
    values["StFahFlg"] = 1
    await zone.fetch_device_status()

    zone.set_target_temperature(22)
    await zone.push_device_status()

    assert (values["StTem"], values["StFahFlg"]) == (6, 0)


async def test_the_unit_is_set_on_the_ducted_unit_and_the_zones_follow(
    controller: FakeZoneController, ac_unit: GreeDevice, zone: GreeDevice
) -> None:
    """TemUnit, not TemUn, written to the ducted unit. The zones read it at the next poll."""
    assert ac_unit.supports_property(GreeProp.ZONE_TEMPERATURE_UNIT)
    assert not ac_unit.supports_property(GreeProp.TARGET_TEMPERATURE_UNIT)

    ac_unit.set_target_temperature_unit(TemperatureUnits.F)
    await ac_unit.push_device_status()
    await zone.fetch_device_status()

    assert {values["TemUnit"] for values in controller.units.values()} == {1}
    assert zone.target_temperature_unit is TemperatureUnits.F
    assert zone.target_temperature == 64


async def test_a_zone_is_opened_and_closed_with_its_power(
    controller: FakeZoneController, zone: GreeDevice
) -> None:
    """A zone damper is the Pow column of the zone."""
    zone.set_power_mode(False)
    await zone.push_device_status()

    assert controller.units[controller.zone_macs[0]]["Pow"] == 0
    assert controller.units[controller.ac_unit]["Pow"] == 1


#
# Other devices are not affected
#


ZONE_COLUMNS = {"StTem", "StFahFlg", "TemUnit"}


async def test_a_normal_unit_asks_for_the_zone_columns_only_once() -> None:
    """The first poll drops what a unit does not answer. After it, the same columns as before."""
    unit = FakeGreeDevice(unsupported_props=ZONE_COLUMNS)
    await unit.start()
    transport = GreeUdpTransport(unit.host, unit.port, max_retries=1, timeout=0.3)
    try:
        device = GreeDevice(name="Zolderkamer", mac_addr=unit.mac)
        await device.bind_with_transport(
            local_controller_mac=unit.mac, local_transport=transport
        )
        first = {col for pack in unit.packs for col in pack.get("cols", [])}
        unit.reset_record()
        await device.fetch_device_status()
    finally:
        await transport.disconnect()
        unit.close()

    later = {col for pack in unit.packs for col in pack.get("cols", [])}
    assert first >= ZONE_COLUMNS
    assert not later & ZONE_COLUMNS
    assert device.device_type is DeviceType.AC_UNIT


@pytest.mark.parametrize(
    ("unsupported", "unit"),
    [(set(), TemperatureUnits.C), ({"TemUn"}, TemperatureUnits.F)],
    ids=["TemUn wins", "only TemUnit"],
)
async def test_the_unit_column_is_the_one_the_device_answers(
    unsupported: set[str], unit: TemperatureUnits
) -> None:
    """TemUn when the device answers it, as every unit did before. TemUnit only without it."""
    fake = FakeGreeDevice(unsupported_props=unsupported)
    fake.values.update({"TemUn": 0, "TemUnit": 1})
    await fake.start()
    transport = GreeUdpTransport(fake.host, fake.port, max_retries=1, timeout=0.3)
    try:
        device = GreeDevice(name="Zolderkamer", mac_addr=fake.mac)
        await device.bind_with_transport(
            local_controller_mac=fake.mac, local_transport=transport
        )
    finally:
        await transport.disconnect()
        fake.close()

    assert device.target_temperature_unit is unit


async def test_a_vrf_indoor_unit_keeps_the_normal_mode_numbers() -> None:
    """A VRF gateway has another name, so mode 4 still means Heat there."""
    gateway = FakeVrfGateway()
    gateway.values.update({"Mod": 4, "name": gateway.name})
    await gateway.start()
    try:
        device, transport = await bind_unit(gateway, "01")
        await transport.disconnect()
    finally:
        gateway.close()

    assert device.device_type is DeviceType.VRF_UNIT
    assert device.operation_mode is OperationMode.heat
