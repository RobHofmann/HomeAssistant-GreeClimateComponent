"""Tests for `GreeDevice`, the object Home Assistant talks to.

Two kinds of test live here. The first drives the real bind and poll cycle
against a fake device over UDP. The second checks the rules between features:
sleep, turbo, energy saving, smart heat and humidity control all switch each
other off, and several of them are only allowed in one operation mode. Those
rules are what a user runs into, and they are pure state logic once a device
is bound.
"""

# pylint: disable=redefined-outer-name
# A test takes a fixture as an argument with the same name. That is the
# pytest pattern, not shadowing.

from collections.abc import AsyncIterator
from typing import Any

from aiogree import device_api_client, transport_mqtt
from aiogree.api import (
    FanSpeed,
    GreeProp,
    HorizontalSwingMode,
    HumidityControlMode,
    InfoProp,
    OperationMode,
    SleepMode,
    TemperatureUnits,
    VerticalSwingMode,
)
from aiogree.cloud_api import CLOUD_SERVERS, GreeRegion
from aiogree.device import GreeDevice
from aiogree.errors import (
    GreeBindingError,
    GreeConnectionError,
    GreeContinuousDryUnavailable,
    GreeEnergySavingUnavailable,
    GreeHumidityControlTargetUnavailable,
    GreeHumidityControlUnavailable,
    GreeProtocolError,
    GreeSleepUnavailable,
    GreeSmartDryUnavailable,
    GreeSmartHeatUnavailable,
    GreeTurboUnavailable,
)
from aiogree.transport_mqtt import GreeMqttTransport
from aiogree.transport_udp import GreeUdpTransport
import pytest

from .conftest import RecordingHandler
from .fakes.cloud import FakeGreeCloud
from .fakes.device import DEFAULT_MAC, DEFAULT_SESSION_KEY, FakeGreeDevice
from .fakes.mqtt import FakeMqttClient

# A unit that reports something for every property, so nothing is pruned by
# accident. The values are plausible ones from a real poll.
LIVE_VALUES: dict[str, Any] = {
    GreeProp.POWER.value: 1,
    GreeProp.OP_MODE.value: OperationMode.cool.value,
    GreeProp.FAN_SPEED.value: FanSpeed.auto.value,
    GreeProp.TARGET_TEMPERATURE.value: 21,
    GreeProp.TARGET_TEMPERATURE_BIT.value: 0,
    GreeProp.TARGET_TEMPERATURE_UNIT.value: TemperatureUnits.C.value,
    GreeProp.SENSOR_INDOOR_TEMPERATURE_3.value: 61,
    GreeProp.SENSOR_OUTSIDE_TEMPERATURE_1.value: 52,
    GreeProp.SENSOR_HUMIDITY_1.value: 55,
    GreeProp.FEATURE_HUMIDITY_CONTROL.value: HumidityControlMode.disabled.value,
    GreeProp.FEATURE_HUMIDITY_TARGET.value: 6,
    InfoProp.HID.value: "362001065279+U-CS532Z(LT)V3.75.bin",
    InfoProp.PROTOCOL_VERSION.value: "V1.2.1",
    InfoProp.DEVICE_NAME.value: "Zolderkamer",
    InfoProp.MODEL_TYPE.value: 32768,
    InfoProp.VENDER.value: 1,
}


@pytest.fixture
async def unit() -> AsyncIterator[FakeGreeDevice]:
    """Start a fake unit that reports a full state."""
    fake = FakeGreeDevice()
    fake.values.update(LIVE_VALUES)
    await fake.start()
    try:
        yield fake
    finally:
        fake.close()


async def bind(unit: FakeGreeDevice) -> tuple[GreeDevice, GreeUdpTransport]:
    """Bind a device to a transport that points at the fake unit."""
    transport = GreeUdpTransport(unit.host, unit.port, max_retries=1, timeout=0.3)
    device = GreeDevice(name="Zolderkamer", mac_addr=unit.mac)
    await device.bind_with_transport(
        local_controller_mac=unit.mac, local_transport=transport
    )
    return device, transport


@pytest.fixture
async def bound(unit: FakeGreeDevice) -> AsyncIterator[GreeDevice]:
    """Bind a device and run its info fetch and first poll."""
    device, transport = await bind(unit)
    try:
        yield device
    finally:
        await transport.disconnect()


#
# Bind and poll
#


async def test_bind_fetches_info_and_status(
    unit: FakeGreeDevice, bound: GreeDevice
) -> None:
    """A finished bind leaves the device available and knowing its firmware."""
    assert bound.is_bound
    assert bound.available
    assert bound.encryption_key == DEFAULT_SESSION_KEY
    assert bound.mac_address == unit.mac
    assert bound.unique_id == unit.mac
    assert bound.firmware_version == "3.75 (Protocol: 1.2.1)"
    assert bound.firmware_code == "362001065279 (UDP)"
    assert bound.power_mode is True


async def test_bind_without_a_transport_is_refused() -> None:
    """There is nothing to talk over."""
    device = GreeDevice(name="Zolderkamer", mac_addr=DEFAULT_MAC)

    with pytest.raises(GreeBindingError, match="No transport provided"):
        await device.bind_with_transport()


async def test_bind_without_a_controller_mac_is_refused(
    unit: FakeGreeDevice, gree_logs: RecordingHandler
) -> None:
    """A transport with no controller MAC cannot be used, so no attempt is left."""
    transport = GreeUdpTransport(unit.host, unit.port, max_retries=1, timeout=0.3)
    device = GreeDevice(name="Zolderkamer", mac_addr=unit.mac)

    try:
        with pytest.raises(GreeBindingError):
            await device.bind_with_transport(local_transport=transport)
    finally:
        await transport.disconnect()

    assert any(
        "No controller MAC provided for local transport" in line
        for line in gree_logs.messages()
    )


async def test_bind_fails_when_the_unit_never_answers(unit: FakeGreeDevice) -> None:
    """The error from the last attempt is what the caller gets."""
    unit.answer_bind = False
    transport = GreeUdpTransport(unit.host, unit.port, max_retries=1, timeout=0.3)
    device = GreeDevice(name="Zolderkamer", mac_addr=unit.mac)

    try:
        with pytest.raises(GreeBindingError):
            await device.bind_with_transport(
                local_controller_mac=unit.mac, local_transport=transport
            )
    finally:
        await transport.disconnect()

    assert not device.is_bound


async def test_a_unit_that_answers_an_empty_status_is_not_pruned(
    unit: FakeGreeDevice,
) -> None:
    """An empty status is a failed request, not proof that nothing is supported.

    Pruning on it would leave the device with nothing to poll for good, so the
    bind fails instead and Home Assistant retries later.
    """
    unit.max_columns = 0
    transport = GreeUdpTransport(unit.host, unit.port, max_retries=1, timeout=0.3)
    device = GreeDevice(name="Zolderkamer", mac_addr=unit.mac)

    try:
        with pytest.raises(GreeProtocolError, match="returned no status values"):
            await device.bind_with_transport(
                local_controller_mac=unit.mac, local_transport=transport
            )
    finally:
        await transport.disconnect()


async def test_a_property_the_unit_does_not_answer_is_dropped(
    unit: FakeGreeDevice,
) -> None:
    """What the unit leaves out of its first status is never asked for again."""
    unit.unsupported_props = {GreeProp.FEAT_TURBO_MODE.value}
    device, transport = await bind(unit)

    try:
        assert not device.supports_property(GreeProp.FEAT_TURBO_MODE)
        assert device.supports_property(GreeProp.POWER)
    finally:
        await transport.disconnect()


async def test_only_the_sensor_that_reports_is_kept(unit: FakeGreeDevice) -> None:
    """A unit exposes the same sensor under several names, most of them zero."""
    device, transport = await bind(unit)

    try:
        assert device.supports_property(GreeProp.SENSOR_INDOOR_TEMPERATURE_3)
        assert not device.supports_property(GreeProp.SENSOR_INDOOR_TEMPERATURE_1)
        assert not device.supports_property(GreeProp.SENSOR_INDOOR_TEMPERATURE_2)
    finally:
        await transport.disconnect()


async def test_a_sensor_that_reports_celsius_plus_forty_is_corrected(
    bound: GreeDevice,
) -> None:
    """61 indoors is not real. The resolver takes the offset off."""
    assert bound.indoors_temperature_c == 21
    assert bound.outdoors_temperature_c == 12
    assert bound.humidity == 55


async def test_push_sends_only_what_changed(
    unit: FakeGreeDevice, bound: GreeDevice
) -> None:
    """A push carries the pending values plus the forced beeper columns."""
    bound.set_power_mode(False)
    unit.reset_record()

    await bound.push_device_status()

    commands = [pack for pack in unit.packs if pack.get("t") == "cmd"]
    assert len(commands) == 1
    assert set(commands[0]["opt"]) == {
        GreeProp.POWER.value,
        GreeProp.BEEPER.value,
        GreeProp.BEEPER_NEW.value,
    }
    assert unit.values[GreeProp.POWER.value] == 0


async def test_push_without_a_change_sends_nothing(
    unit: FakeGreeDevice, bound: GreeDevice, gree_logs: RecordingHandler
) -> None:
    """Sending the value the unit already has is pointless."""
    unit.reset_record()

    await bound.push_device_status()

    assert [pack for pack in unit.packs if pack.get("t") == "cmd"] == []
    assert any("No changes in properties" in line for line in gree_logs.messages())


async def test_the_beeper_setting_is_forced_on_every_push(
    unit: FakeGreeDevice, bound: GreeDevice
) -> None:
    """A remote turns the beeper back on, so the component sends it every time."""
    bound.set_beeper(True)
    bound.set_power_mode(False)
    unit.reset_record()

    await bound.push_device_status()

    command = next(pack for pack in unit.packs if pack.get("t") == "cmd")
    values = dict(zip(command["opt"], command["p"], strict=True))
    assert values[GreeProp.BEEPER.value] == 0
    assert values[GreeProp.BEEPER_NEW.value] == 1
    assert bound.beeper is True


async def test_a_standalone_unit_confirms_a_command_on_the_first_read(
    unit: FakeGreeDevice, bound: GreeDevice
) -> None:
    """The read right after the command already shows the new value."""
    bound.set_power_mode(False)

    await bound.push_device_status()

    assert not bound.has_held_values
    assert bound.power_mode is False
    assert bound.gather_diagnostics()["state_held"] == {}


async def test_a_stale_read_after_a_command_keeps_the_sent_value(
    unit: FakeGreeDevice, bound: GreeDevice
) -> None:
    """A VRF gateway answers from its cache for a while. The UI must not flip back."""
    unit.stale_reads_after_cmd = 100
    bound.set_power_mode(False)

    await bound.push_device_status()

    assert unit.values[GreeProp.POWER.value] == 0
    assert bound.has_held_values
    assert bound.power_mode is False
    assert bound.gather_diagnostics()["state_held"] == {GreeProp.POWER.value: 0}

    await bound.fetch_device_status()

    assert bound.power_mode is False

    unit.catch_up()
    await bound.fetch_device_status()

    assert not bound.has_held_values
    assert bound.power_mode is False


async def test_a_command_the_unit_ignores_stays_held_until_the_ttl(
    unit: FakeGreeDevice, bound: GreeDevice
) -> None:
    """The unit acknowledges but keeps its old value. That is never a confirmation.

    What happens when the TTL runs out is tested in test_device_state.py with a
    fake clock.
    """
    unit.apply_commands = False
    bound.set_power_mode(False)

    await bound.push_device_status()

    assert unit.values[GreeProp.POWER.value] == 1
    assert bound.has_held_values
    assert bound.power_mode is False


async def test_a_poll_that_gets_no_answer_raises(
    unit: FakeGreeDevice, bound: GreeDevice
) -> None:
    """The coordinator needs to hear about it, so the entity goes unavailable."""
    unit.answer_status = False

    with pytest.raises(GreeConnectionError):
        await bound.fetch_device_status()


async def test_unbind(unit: FakeGreeDevice, bound: GreeDevice) -> None:
    """After an unbind the device is no longer available."""
    await bound.unbind_device()

    assert not bound.is_bound
    assert not bound.available


async def test_diagnostics_redact_the_key(bound: GreeDevice) -> None:
    """Diagnostics are attached to issues, so no key may be in them."""
    data = bound.gather_diagnostics()

    assert data["info"]["key"] == "V1sT9[redacted]"
    assert DEFAULT_SESSION_KEY not in str(data)
    assert data["info"]["mac"] == DEFAULT_MAC
    assert data["state"]


#
# Feature rules
#


async def test_reading_the_simple_properties(bound: GreeDevice) -> None:
    """The plain values come straight from the state."""
    assert bound.operation_mode is OperationMode.cool
    assert bound.fan_speed is FanSpeed.auto
    assert bound.target_temperature == 21.0
    assert bound.target_temperature_unit is TemperatureUnits.C
    assert bound.has_hvac_error is False


async def test_setting_the_swing_modes(bound: GreeDevice) -> None:
    """Swing has no rules attached to it."""
    bound.set_vertical_swing_mode(VerticalSwingMode.full_swing)
    bound.set_horizontal_swing_mode(HorizontalSwingMode.left_center)

    assert bound.vertical_swing_mode is VerticalSwingMode.full_swing
    assert bound.horizontal_swing_mode is HorizontalSwingMode.left_center


async def test_the_target_temperature_in_celsius(bound: GreeDevice) -> None:
    """Half degrees are kept in a separate column."""
    bound.set_target_temperature(22.5)

    assert bound.target_temperature == 22.5


async def test_the_target_temperature_in_fahrenheit(
    bound: GreeDevice, gree_logs: RecordingHandler
) -> None:
    """Fahrenheit is whole degrees only, so a half degree is rounded and logged."""
    bound.set_target_temperature_unit(TemperatureUnits.F)
    bound.set_target_temperature(70.7)

    assert bound.target_temperature == 71
    assert any(
        "does not support floating Fahrenheit" in line for line in gree_logs.warnings()
    )


async def test_sleep_needs_cool_or_heat(bound: GreeDevice) -> None:
    """The unit refuses sleep in any other mode, so the component does too."""
    bound.set_operation_mode(OperationMode.fan)

    with pytest.raises(GreeSleepUnavailable):
        bound.set_feature_sleep(SleepMode.normal)


async def test_sleep_is_allowed_in_cool(bound: GreeDevice) -> None:
    """In Cool it works, and both sleep columns are set together."""
    bound.set_operation_mode(OperationMode.cool)
    bound.set_feature_sleep(SleepMode.normal)

    assert bound.feature_sleep is SleepMode.normal


async def test_sleep_reports_disabled_when_the_two_columns_disagree(
    bound: GreeDevice, gree_logs: RecordingHandler
) -> None:
    """Sleep lives in two columns. A unit can report them out of step."""
    bound.set_operation_mode(OperationMode.cool)
    bound.set_feature_sleep(SleepMode.normal)
    bound.set_feature_sleep(SleepMode.disabled)

    assert bound.feature_sleep is SleepMode.disabled
    assert gree_logs.warnings() == []


async def test_turbo_needs_cool_or_heat(bound: GreeDevice) -> None:
    """Turbo is refused outside Cool and Heat."""
    bound.set_operation_mode(OperationMode.dry)

    with pytest.raises(GreeTurboUnavailable):
        bound.set_feature_turbo(True)


async def test_turbo_can_always_be_switched_off(bound: GreeDevice) -> None:
    """Switching a feature off is never refused."""
    bound.set_operation_mode(OperationMode.dry)
    bound.set_feature_turbo(False)

    assert bound.feature_turbo is False


async def test_energy_saving_needs_cool(bound: GreeDevice) -> None:
    """Energy saving only exists in Cool."""
    bound.set_operation_mode(OperationMode.heat)

    with pytest.raises(GreeEnergySavingUnavailable):
        bound.set_feature_energy_saving(True)


async def test_smart_heat_needs_heat(bound: GreeDevice) -> None:
    """Smart heat only exists in Heat."""
    bound.set_operation_mode(OperationMode.cool)

    with pytest.raises(GreeSmartHeatUnavailable):
        bound.set_feature_smart_heat(True)


async def test_energy_saving_switches_sleep_and_smart_heat_off(
    bound: GreeDevice,
) -> None:
    """The unit cannot run them together, so the component mirrors the remote."""
    bound.set_operation_mode(OperationMode.cool)
    bound.set_feature_sleep(SleepMode.normal)

    bound.set_feature_energy_saving(True)

    assert bound.feature_energy_saving is True
    assert bound.feature_sleep is SleepMode.disabled
    assert bound.feature_smart_heat is False


async def test_smart_heat_switches_sleep_and_energy_saving_off(
    bound: GreeDevice,
) -> None:
    """The same rule from the other side."""
    bound.set_operation_mode(OperationMode.heat)
    bound.set_feature_sleep(SleepMode.normal)

    bound.set_feature_smart_heat(True)

    assert bound.feature_smart_heat is True
    assert bound.feature_sleep is SleepMode.disabled
    assert bound.feature_energy_saving is False


async def test_leaving_cool_switches_energy_saving_off(bound: GreeDevice) -> None:
    """A mode change cleans up the features that no longer apply."""
    bound.set_operation_mode(OperationMode.cool)
    bound.set_feature_energy_saving(True)

    bound.set_operation_mode(OperationMode.fan)

    assert bound.feature_energy_saving is False


async def test_a_fan_speed_other_than_auto_switches_energy_saving_off(
    bound: GreeDevice, gree_logs: RecordingHandler
) -> None:
    """Energy saving picks the fan speed itself, so a manual speed ends it."""
    bound.set_operation_mode(OperationMode.cool)
    bound.set_feature_energy_saving(True)

    bound.set_fan_speed(FanSpeed.high)

    assert bound.feature_energy_saving is False
    assert any("Energy saving mode disabled" in line for line in gree_logs.messages())


async def test_humidity_control_needs_cool_or_dry(bound: GreeDevice) -> None:
    """Drying only makes sense in Cool and Dry."""
    bound.set_operation_mode(OperationMode.heat)

    with pytest.raises(GreeHumidityControlUnavailable):
        bound.set_feature_humidity_control(HumidityControlMode.target_dry)


async def test_smart_dry_needs_cool(bound: GreeDevice) -> None:
    """Smart dry is a Cool mode feature."""
    bound.set_operation_mode(OperationMode.dry)

    with pytest.raises(GreeSmartDryUnavailable):
        bound.set_feature_humidity_control(HumidityControlMode.smart_dry)


async def test_continuous_dry_needs_dry(bound: GreeDevice) -> None:
    """Continuous dry is a Dry mode feature."""
    bound.set_operation_mode(OperationMode.cool)

    with pytest.raises(GreeContinuousDryUnavailable):
        bound.set_feature_humidity_control(HumidityControlMode.continuous_dry)


async def test_target_dry_starts_at_the_lowest_value_for_the_mode(
    bound: GreeDevice,
) -> None:
    """In Cool the range starts at 40 percent, in Dry at 30."""
    bound.set_operation_mode(OperationMode.cool)
    bound.set_feature_humidity_control(HumidityControlMode.target_dry)

    assert bound.feature_humidity_control is HumidityControlMode.target_dry
    assert bound.feature_humidity_control_target == 40


async def test_a_humidity_target_needs_target_dry(bound: GreeDevice) -> None:
    """The other dry modes pick their own target."""
    bound.set_operation_mode(OperationMode.cool)
    bound.set_feature_humidity_control(HumidityControlMode.smart_dry)

    with pytest.raises(GreeHumidityControlTargetUnavailable):
        bound.set_feature_humidity_control_target(60)


async def test_setting_a_humidity_target(bound: GreeDevice) -> None:
    """In target dry the percentage can be picked."""
    bound.set_operation_mode(OperationMode.cool)
    bound.set_feature_humidity_control(HumidityControlMode.target_dry)

    bound.set_feature_humidity_control_target(60)

    assert bound.feature_humidity_control_target == 60


async def test_a_mode_change_switches_humidity_control_off(
    bound: GreeDevice, gree_logs: RecordingHandler
) -> None:
    """Drying does not survive a move to a mode that cannot dry."""
    bound.set_operation_mode(OperationMode.cool)
    bound.set_feature_humidity_control(HumidityControlMode.target_dry)

    bound.set_operation_mode(OperationMode.heat)

    assert bound.feature_humidity_control is HumidityControlMode.disabled
    assert any("Humidity control disabled" in line for line in gree_logs.messages())


async def test_the_plain_feature_switches(bound: GreeDevice) -> None:
    """These have no rules, they just go through to the state."""
    bound.set_feature_light(True)
    bound.set_feature_light_sensor(True)
    bound.set_feature_fresh_air(True)
    bound.set_feature_xfan(True)
    bound.set_feature_health(True)
    bound.set_feature_quiet(True)
    bound.set_feature_anti_direct_blow(True)

    assert bound.feature_light is True
    assert bound.feature_light_sensor is True
    assert bound.feature_fresh_air is True
    assert bound.feature_x_fan is True
    assert bound.feature_health is True
    assert bound.feature_quiet is True
    assert bound.feature_anti_direct_blow is True


async def test_target_dry_reads_back_as_target_dry(bound: GreeDevice) -> None:
    """Target dry is stored as 0 and disabled as 15, so a 0 must not read as off.

    Falling back on a falsy value here would report every drying device as
    disabled, and the humidity target could then never be set.
    """
    bound.set_operation_mode(OperationMode.cool)
    bound.set_feature_humidity_control(HumidityControlMode.target_dry)

    assert bound.feature_humidity_control is HumidityControlMode.target_dry


#
# Firmware and the paths that need another transport
#


async def test_sleep_reports_normal_when_the_unit_says_on_without_a_type(
    gree_logs: RecordingHandler,
) -> None:
    """Sleep lives in two columns and a unit can report them out of step."""
    unit = FakeGreeDevice()
    unit.values.update(LIVE_VALUES)
    unit.values[GreeProp.FEAT_SLEEP_MODE.value] = 1
    unit.values[GreeProp.FEAT_SLEEP_MODE_TYPE.value] = SleepMode.disabled.value
    await unit.start()
    device, transport = await bind(unit)

    try:
        assert device.feature_sleep is SleepMode.normal
    finally:
        await transport.disconnect()
        unit.close()

    assert any(
        "Inconsistent Sleep mode properties" in line for line in gree_logs.warnings()
    )


async def test_sleep_reports_disabled_when_the_unit_says_off_with_a_type(
    gree_logs: RecordingHandler,
) -> None:
    """The other way round, the switch wins over the type."""
    unit = FakeGreeDevice()
    unit.values.update(LIVE_VALUES)
    unit.values[GreeProp.FEAT_SLEEP_MODE.value] = 0
    unit.values[GreeProp.FEAT_SLEEP_MODE_TYPE.value] = SleepMode.normal.value
    await unit.start()
    device, transport = await bind(unit)

    try:
        assert device.feature_sleep is SleepMode.disabled
    finally:
        await transport.disconnect()
        unit.close()

    assert any(
        "Inconsistent Sleep mode properties" in line for line in gree_logs.warnings()
    )


async def test_a_unit_that_binds_but_never_answers_a_status(
    unit: FakeGreeDevice, gree_logs: RecordingHandler, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bind itself works, the first poll does not, so setup fails."""
    # Every column probe waits the full PROBE_TIMEOUT on a silent unit, which
    # is 5 seconds each in real life. The probe budget is not what this test is
    # about, so shorten it.
    monkeypatch.setattr(device_api_client, "PROBE_TIMEOUT", 0.2)
    unit.answer_status = False
    transport = GreeUdpTransport(unit.host, unit.port, max_retries=1, timeout=0.2)
    device = GreeDevice(name="Zolderkamer", mac_addr=unit.mac)

    try:
        with pytest.raises(GreeConnectionError):
            await device.bind_with_transport(
                local_controller_mac=unit.mac, local_transport=transport
            )
    finally:
        await transport.disconnect()

    assert any("Failed fetching device" in line for line in gree_logs.messages())


async def test_an_mqtt_transport_without_a_controller_mac_is_skipped(
    gree_logs: RecordingHandler, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a MAC there is nothing to address, so the attempt is dropped."""
    monkeypatch.setattr(transport_mqtt.aiomqtt, "Client", FakeMqttClient)
    mqtt = GreeMqttTransport(user_id="1", token="t", region=GreeRegion.EU)
    device = GreeDevice(name="Zolderkamer", mac_addr=DEFAULT_MAC)

    with pytest.raises(GreeBindingError):
        await device.bind_with_transport(mqtt_transport=mqtt)

    assert any(
        "No controller MAC provided for MQTT transport" in line
        for line in gree_logs.messages()
    )


async def test_a_firmware_check_without_a_code_gives_nothing(
    gree_logs: RecordingHandler,
) -> None:
    """A device that never reported its hid cannot be checked."""
    device = GreeDevice(name="Zolderkamer", mac_addr=DEFAULT_MAC)

    assert await device.check_fw_updates() == (False, None)
    assert any("firmware code is unknown" in line for line in gree_logs.messages())


async def test_a_firmware_check_finds_a_newer_version(
    bound: GreeDevice, monkeypatch: pytest.MonkeyPatch
) -> None:
    """3.80 is newer than the 3.75 this unit runs."""
    server = FakeGreeCloud(firmware_response={"r": 200, "ver": "3.80"})
    await server.start()
    monkeypatch.setitem(CLOUD_SERVERS, GreeRegion.EU, server.url)

    try:
        has_update, info = await bound.check_fw_updates()
    finally:
        await server.close()

    assert has_update is True
    assert info is not None
    assert info.version == "3.80"


async def test_a_firmware_check_on_the_latest_version(
    bound: GreeDevice, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same version is not an update."""
    server = FakeGreeCloud(firmware_response={"r": 200, "ver": "3.75"})
    await server.start()
    monkeypatch.setitem(CLOUD_SERVERS, GreeRegion.EU, server.url)

    try:
        has_update, info = await bound.check_fw_updates()
    finally:
        await server.close()

    assert has_update is False
    assert info is not None


async def test_a_firmware_check_that_the_server_cannot_answer(
    bound: GreeDevice, monkeypatch: pytest.MonkeyPatch, gree_logs: RecordingHandler
) -> None:
    """An unknown firmware code is not an update either."""
    server = FakeGreeCloud(firmware_response={"r": 404})
    await server.start()
    monkeypatch.setitem(CLOUD_SERVERS, GreeRegion.EU, server.url)

    try:
        assert await bound.check_fw_updates() == (False, None)
    finally:
        await server.close()

    assert any("bad server request" in line for line in gree_logs.messages())


async def test_the_device_model_comes_from_the_info_columns(bound: GreeDevice) -> None:
    """The model is what the entity shows in the device registry."""
    assert bound.device_model_id == "32768 (1)"
