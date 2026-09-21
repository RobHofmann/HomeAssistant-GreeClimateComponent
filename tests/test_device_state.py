"""Tests for `DeviceState`, the local copy of what a device reports.

Pure state handling, no socket. The rules that matter here are which value a
read returns, when a property counts as supported, and when a property is
dropped from polling. A property only ever leaves the poll list, it never
comes back, so a wrong drop is permanent for the life of the object.
"""

# pylint: disable=redefined-outer-name
# A test takes a fixture as an argument with the same name. That is the
# pytest pattern, not shadowing.

from aiogree.api import GreeProp, InfoProp
from aiogree.device_state import DeviceState
import pytest

from .conftest import RecordingHandler

DEVICE_ID = "f4911e3f1ac8"


@pytest.fixture
def state() -> DeviceState:
    """Build a state object that knows every property."""
    return DeviceState(device_id=DEVICE_ID, capabilities=list(GreeProp))


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
