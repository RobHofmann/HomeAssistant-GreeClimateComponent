"""Tests for `DeviceState`, the local copy of what a device reports.

Pure state handling, no socket. The rules that matter here are which value a
read returns, when a property counts as supported, and when a property is
dropped from polling. A property only ever leaves the poll list, it never
comes back, so a wrong drop is permanent for the life of the object.

Held values are what was sent in the last command and is not confirmed yet. A
VRF gateway can report its old cached state for a few seconds after a command.
The hold tests use a fake clock, so no test waits for the real time to pass.
"""

# pylint: disable=redefined-outer-name
# A test takes a fixture as an argument with the same name. That is the
# pytest pattern, not shadowing.

from aiogree.api import GreeProp, InfoProp
from aiogree.const import HELD_VALUE_TTL
from aiogree.device_state import DeviceState
import pytest

from .conftest import RecordingHandler

DEVICE_ID = "f4911e3f1ac8"


@pytest.fixture
def state() -> DeviceState:
    """Build a state object that knows every property."""
    return DeviceState(device_id=DEVICE_ID, capabilities=list(GreeProp))


class FakeClock:
    """Monotonic seconds that only move when a test says so."""

    def __init__(self) -> None:
        """Start at a fixed time."""
        self.now = 1000.0

    def __call__(self) -> float:
        """Return the current time."""
        return self.now

    def advance(self, seconds: float) -> None:
        """Move the time forward."""
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    """Return a clock the test controls."""
    return FakeClock()


@pytest.fixture
def timed_state(clock: FakeClock) -> DeviceState:
    """Build a state object that reads the time from the fake clock."""
    return DeviceState(device_id=DEVICE_ID, capabilities=list(GreeProp), clock=clock)


def seed(state: DeviceState, values: dict[GreeProp, int]) -> None:
    """Fill the raw state the way a status reply would."""
    state.process_new_state({prop.value: str(value) for prop, value in values.items()})


def test_a_read_falls_back_to_the_default(
    state: DeviceState, gree_logs: RecordingHandler
) -> None:
    """A property the device never sent has no value."""
    assert state.get(GreeProp.POWER, 7) == 7
    assert any("not found in state" in line for line in gree_logs.messages())


def test_a_read_returns_the_raw_value(state: DeviceState) -> None:
    """After a status reply the value is there."""
    seed(state, {GreeProp.POWER: 1})

    assert state.get(GreeProp.POWER) == 1
    assert state.get_bool(GreeProp.POWER) is True


def test_a_read_prefers_the_pending_value(state: DeviceState) -> None:
    """A change that is not sent yet still reads back, so the UI follows along."""
    seed(state, {GreeProp.POWER: 1})
    state.set(GreeProp.POWER, 0)

    assert state.get(GreeProp.POWER) == 0
    assert state.raw[GreeProp.POWER] == 1


def test_setting_an_unsupported_property_is_refused(
    state: DeviceState, gree_logs: RecordingHandler
) -> None:
    """A device that never reported a property cannot be told to change it."""
    state.set(GreeProp.FEAT_TURBO_MODE, 1)

    assert GreeProp.FEAT_TURBO_MODE not in state.pending
    assert any("is unsupported on this device" in line for line in gree_logs.messages())


def test_the_beeper_is_always_supported(state: DeviceState) -> None:
    """The beeper is never reported by the device but is always settable."""
    assert state.supports(GreeProp.BEEPER)
    assert state.supports(GreeProp.BEEPER_NEW)


def test_a_property_outside_the_capabilities_is_not_supported() -> None:
    """A capability list from the config entry can narrow what may be set."""
    state = DeviceState(device_id=DEVICE_ID, capabilities=[GreeProp.POWER])
    seed(state, {GreeProp.POWER: 1, GreeProp.FEAT_LIGHT: 1})

    assert state.supports(GreeProp.POWER)
    assert not state.supports(GreeProp.FEAT_LIGHT)


def test_update_and_clear_pending(state: DeviceState) -> None:
    """Several changes go in at once and can be dropped at once."""
    seed(state, {GreeProp.POWER: 0, GreeProp.FEAT_LIGHT: 0})
    state.update({GreeProp.POWER: 1, GreeProp.FEAT_LIGHT: 1})

    assert state.has_pending_updates

    state.clear_pending()

    assert not state.has_pending_updates
    assert state.pending == {}


def test_a_pending_value_equal_to_the_raw_one_is_not_a_change(
    state: DeviceState,
) -> None:
    """Sending a value the device already has is pointless, so it is not pending."""
    seed(state, {GreeProp.POWER: 1})
    state.set(GreeProp.POWER, 1)

    assert not state.has_pending_updates


def test_set_bool(state: DeviceState) -> None:
    """A bool becomes 1 or 0."""
    seed(state, {GreeProp.FEAT_LIGHT: 0})
    state.set_bool(GreeProp.FEAT_LIGHT, True)

    assert state.pending[GreeProp.FEAT_LIGHT] == 1


def test_a_status_reply_is_sorted_into_state_info_and_unknown(
    state: DeviceState, gree_logs: RecordingHandler
) -> None:
    """The device sends three kinds of column in one reply."""
    state.process_new_state(
        {
            GreeProp.POWER.value: "1",
            InfoProp.HID.value: "362001065279+U-CS532Z(LT)V3.75.bin",
            "SomeNewColumn": "42",
        }
    )

    assert state.raw[GreeProp.POWER] == 1
    assert state.info[InfoProp.HID] == "362001065279+U-CS532Z(LT)V3.75.bin"
    assert state.unknown["SomeNewColumn"] == "42"
    assert any("Unknown properties" in line for line in gree_logs.messages())


def test_a_value_that_is_not_a_number_is_logged_and_dropped(
    state: DeviceState, gree_logs: RecordingHandler
) -> None:
    """Devices do not type their values, so a bad one must not crash the poll."""
    state.process_new_state({GreeProp.POWER.value: "not a number"})

    assert GreeProp.POWER not in state.raw
    assert any("Invalid values" in line for line in gree_logs.messages())


def test_a_property_that_is_no_longer_polled_is_not_stored(state: DeviceState) -> None:
    """Once a property is dropped, a late reply does not bring it back."""
    seed(state, {GreeProp.FEAT_LIGHT: 1})
    state.remove(GreeProp.FEAT_LIGHT)
    seed(state, {GreeProp.FEAT_LIGHT: 1})

    assert GreeProp.FEAT_LIGHT not in state.raw
    assert GreeProp.FEAT_LIGHT not in state.polled_properties


def test_missing_properties_are_dropped_from_polling(state: DeviceState) -> None:
    """A property the device did not answer is not asked for again."""
    seed(state, {GreeProp.POWER: 1, GreeProp.OP_MODE: 1})

    state.invalidate_missing_properties()

    assert set(state.polled_properties) == {GreeProp.POWER, GreeProp.OP_MODE}


def test_a_sensor_group_keeps_only_the_one_that_reports(state: DeviceState) -> None:
    """Units expose the same sensor under several names. Keep the one that works."""
    group = [
        GreeProp.SENSOR_INDOOR_TEMPERATURE_1,
        GreeProp.SENSOR_INDOOR_TEMPERATURE_2,
        GreeProp.SENSOR_INDOOR_TEMPERATURE_3,
    ]
    seed(
        state,
        {
            GreeProp.SENSOR_INDOOR_TEMPERATURE_1: 0,
            GreeProp.SENSOR_INDOOR_TEMPERATURE_2: 61,
            GreeProp.SENSOR_INDOOR_TEMPERATURE_3: 0,
        },
    )

    state.invalidate_missing_property_group(group)

    assert GreeProp.SENSOR_INDOOR_TEMPERATURE_2 in state.polled_properties
    assert GreeProp.SENSOR_INDOOR_TEMPERATURE_1 not in state.polled_properties
    assert GreeProp.SENSOR_INDOOR_TEMPERATURE_3 not in state.polled_properties


def test_a_sensor_group_that_reports_nothing_is_dropped_whole(
    state: DeviceState,
) -> None:
    """If none of them has a value, none of them is worth polling."""
    group = [GreeProp.SENSOR_HUMIDITY_1, GreeProp.SENSOR_HUMIDITY_2]
    seed(state, {GreeProp.SENSOR_HUMIDITY_1: 0, GreeProp.SENSOR_HUMIDITY_2: 0})

    state.invalidate_missing_property_group(group)

    assert all(prop not in state.polled_properties for prop in group)


def test_the_views_are_read_only(state: DeviceState) -> None:
    """Nothing outside the state object may write to it."""
    seed(state, {GreeProp.POWER: 1})

    with pytest.raises(TypeError):
        state.raw[GreeProp.POWER] = 0  # type: ignore[index]


#
# Held values
#


def test_a_stale_report_does_not_undo_a_sent_value(timed_state: DeviceState) -> None:
    """The gateway still reports the old value, but the read shows the sent one."""
    seed(timed_state, {GreeProp.TARGET_TEMPERATURE: 21})
    timed_state.hold({GreeProp.TARGET_TEMPERATURE: 24})

    seed(timed_state, {GreeProp.TARGET_TEMPERATURE: 21})

    assert timed_state.get(GreeProp.TARGET_TEMPERATURE) == 24
    assert timed_state.raw[GreeProp.TARGET_TEMPERATURE] == 21
    assert timed_state.held == {GreeProp.TARGET_TEMPERATURE: 24}


def test_a_report_of_the_sent_value_ends_the_hold(timed_state: DeviceState) -> None:
    """Once confirmed, later reports count again, for example from a remote."""
    seed(timed_state, {GreeProp.TARGET_TEMPERATURE: 21})
    timed_state.hold({GreeProp.TARGET_TEMPERATURE: 24})

    seed(timed_state, {GreeProp.TARGET_TEMPERATURE: 24})

    assert timed_state.held == {}

    seed(timed_state, {GreeProp.TARGET_TEMPERATURE: 19})

    assert timed_state.get(GreeProp.TARGET_TEMPERATURE) == 19


def test_a_hold_ends_when_its_time_is_up(
    timed_state: DeviceState, clock: FakeClock
) -> None:
    """After the TTL the reported value wins, even without a new report."""
    seed(timed_state, {GreeProp.POWER: 1})
    timed_state.hold({GreeProp.POWER: 0})
    seed(timed_state, {GreeProp.POWER: 1})

    clock.advance(HELD_VALUE_TTL - 0.1)
    assert timed_state.get(GreeProp.POWER) == 0

    clock.advance(0.1)
    assert timed_state.get(GreeProp.POWER) == 1
    assert timed_state.held == {}


def test_a_rejected_command_is_not_shown_for_ever(
    timed_state: DeviceState, clock: FakeClock
) -> None:
    """A device that keeps its old value gets the last word after the TTL."""
    seed(timed_state, {GreeProp.FAN_SPEED: 0})
    timed_state.hold({GreeProp.FAN_SPEED: 3})

    for _ in range(4):
        seed(timed_state, {GreeProp.FAN_SPEED: 0})
        assert timed_state.get(GreeProp.FAN_SPEED) == 3
        clock.advance(HELD_VALUE_TTL / 4)

    seed(timed_state, {GreeProp.FAN_SPEED: 0})

    assert timed_state.get(GreeProp.FAN_SPEED) == 0
    assert timed_state.held == {}


def test_a_new_command_starts_a_new_hold(
    timed_state: DeviceState, clock: FakeClock
) -> None:
    """The TTL counts from the last time a value was sent."""
    seed(timed_state, {GreeProp.POWER: 1})
    timed_state.hold({GreeProp.POWER: 0})
    clock.advance(HELD_VALUE_TTL - 1)

    timed_state.hold({GreeProp.POWER: 0})
    clock.advance(2)

    assert timed_state.get(GreeProp.POWER) == 0


def test_a_pending_value_wins_over_a_held_one(timed_state: DeviceState) -> None:
    """A change that is not sent yet is newer than the one that was sent."""
    seed(timed_state, {GreeProp.TARGET_TEMPERATURE: 21})
    timed_state.hold({GreeProp.TARGET_TEMPERATURE: 24})
    timed_state.set(GreeProp.TARGET_TEMPERATURE, 25)

    assert timed_state.get(GreeProp.TARGET_TEMPERATURE) == 25
    assert timed_state.pending == {GreeProp.TARGET_TEMPERATURE: 25}
    assert timed_state.held == {GreeProp.TARGET_TEMPERATURE: 24}

    timed_state.clear_pending()

    assert timed_state.get(GreeProp.TARGET_TEMPERATURE) == 24


def test_a_change_back_to_the_stale_value_is_still_sent(
    timed_state: DeviceState,
) -> None:
    """The device was told 24, so going back to 21 is a real change."""
    seed(timed_state, {GreeProp.TARGET_TEMPERATURE: 21})
    timed_state.hold({GreeProp.TARGET_TEMPERATURE: 24})

    timed_state.set(GreeProp.TARGET_TEMPERATURE, 21)
    assert timed_state.has_pending_updates

    timed_state.set(GreeProp.TARGET_TEMPERATURE, 24)
    assert not timed_state.has_pending_updates


def test_props_that_are_not_polled_are_not_held(timed_state: DeviceState) -> None:
    """The beeper is never reported, so there is nothing to wait for."""
    seed(timed_state, {GreeProp.POWER: 1})
    timed_state.hold({GreeProp.POWER: 0, GreeProp.BEEPER: 1, GreeProp.BEEPER_NEW: 0})

    assert timed_state.held == {GreeProp.POWER: 0}


def test_removing_a_prop_drops_its_hold(timed_state: DeviceState) -> None:
    """A prop that is no longer polled can never be confirmed."""
    seed(timed_state, {GreeProp.FEAT_LIGHT: 1})
    timed_state.hold({GreeProp.FEAT_LIGHT: 0})

    timed_state.remove(GreeProp.FEAT_LIGHT)

    assert timed_state.held == {}
