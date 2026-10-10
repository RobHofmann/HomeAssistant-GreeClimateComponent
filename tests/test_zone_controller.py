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

from aiogree.api import DeviceType, FanSpeed, GreeProp, OperationMode
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


#
# The ducted unit
#


async def test_the_ducted_unit_is_recognised(ac_unit: GreeDevice) -> None:
    """The name in the info columns and the 00 suffix make it the ducted unit."""
    assert ac_unit.device_type is DeviceType.ZONE_CONTROLLER
    assert not ac_unit.supports_property(GreeProp.ZONE_TARGET_TEMPERATURE)


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
    assert zone.zone_target_temperature == 18

    controller.units[controller.zone_macs[0]]["StTem"] = 5
    await zone.fetch_device_status()

    assert zone.zone_target_temperature == 21


async def test_a_zone_target_temperature_is_sent_minus_16(
    controller: FakeZoneController, zone: GreeDevice
) -> None:
    """19 degrees goes out as 3, and values outside 16 to 30 are clamped."""
    zone.set_zone_target_temperature(19)
    await zone.push_device_status()

    assert controller.units[controller.zone_macs[0]]["StTem"] == 3

    zone.set_zone_target_temperature(35)
    await zone.push_device_status()

    assert controller.units[controller.zone_macs[0]]["StTem"] == 14


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


async def test_a_normal_unit_never_asks_for_the_zone_column() -> None:
    """Only zones poll StTem. A standalone unit sends the same columns as before."""
    unit = FakeGreeDevice()
    await unit.start()
    transport = GreeUdpTransport(unit.host, unit.port, max_retries=1, timeout=0.3)
    try:
        device = GreeDevice(name="Zolderkamer", mac_addr=unit.mac)
        await device.bind_with_transport(
            local_controller_mac=unit.mac, local_transport=transport
        )
        await device.fetch_device_status()
    finally:
        await transport.disconnect()
        unit.close()

    asked = {col for pack in unit.packs for col in pack.get("cols", [])}
    assert GreeProp.ZONE_TARGET_TEMPERATURE.value not in asked
    assert device.device_type is DeviceType.AC_UNIT


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
