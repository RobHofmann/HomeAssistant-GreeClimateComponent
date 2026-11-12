"""Tests for half degrees Celsius and the temperature unit (issue 569).

Units use different columns for the half degree: the bit (TemRec or StFahFlg),
Add0.5 (0 or 1) and Add0.1 (a tenths digit). A unit can answer a column and
still ignore it. So every answered column is written, and a value is a half
degree when any of them is set. These tests drive the real bind and poll
cycle against a fake unit and check what goes over the wire.
"""

# pylint: disable=redefined-outer-name
# A test takes a fixture as an argument with the same name. That is the
# pytest pattern, not shadowing.

from collections.abc import AsyncIterator, Callable
from typing import Any

from aiogree.api import TemperatureUnits
from aiogree.const import HELD_VALUE_TTL
from aiogree.device import GreeDevice
from aiogree.transport_udp import GreeUdpTransport
import pytest

from .fakes.device import FakeGreeDevice

HALF_COLUMNS = {"TemRec", "StFahFlg", "Add0.5", "Add0.1"}

# The columns a unit answers, by the kind of unit. The fake answers every
# other column it is asked for with 0, as some real units do.
UNITS = {
    # A normal split unit: only the bit
    "tem_rec": {"TemRec"},
    # The bit in the second column, as a zone has it
    "st_fah_flg": {"StFahFlg"},
    # The unit of PR 537: Add0.5
    "add_0_5": {"Add0.5"},
    # The cloud gateway of PR 568: Add0.1, with TemRec read as ""
    "add_0_1": {"Add0.1"},
    # A unit that answers all of them
    "all": {"TemRec", "Add0.5", "Add0.1"},
    # A unit without any
    "none": set(),
}


async def start_unit(
    answers: set[str], values: dict[str, Any] | None = None, **kwargs: Any
) -> FakeGreeDevice:
    """Start a fake unit that answers these half degree columns and no other."""
    fake = FakeGreeDevice(unsupported_props=HALF_COLUMNS - answers, **kwargs)
    fake.values.update({"SetTem": 21, "TemUn": 0, "Mod": 1})
    fake.values.update(dict.fromkeys(answers, 0))
    fake.values.update(values or {})
    await fake.start()
    return fake


async def bind(fake: FakeGreeDevice, mac: str | None = None) -> GreeDevice:
    """Bind a device to the fake unit, or to a sub-unit behind it."""
    transport = GreeUdpTransport(fake.host, fake.port, max_retries=1, timeout=0.3)
    device = GreeDevice(name="Zolderkamer", mac_addr=mac or fake.mac)
    await device.bind_with_transport(
        local_controller_mac=fake.mac, local_transport=transport
    )
    return device


@pytest.fixture
async def unit_factory() -> AsyncIterator[Callable[..., Any]]:
    """Start fake units and bind devices to them. Everything is closed after."""
    fakes: list[FakeGreeDevice] = []
    devices: list[GreeDevice] = []

    async def make(
        answers: set[str], values: dict[str, Any] | None = None, **kwargs: Any
    ) -> tuple[FakeGreeDevice, GreeDevice]:
        fake = await start_unit(answers, values, **kwargs)
        fakes.append(fake)
        device = await bind(fake)
        devices.append(device)
        return fake, device

    yield make

    for device in devices:
        if device.transport is not None:
            await device.transport.disconnect()
    for fake in fakes:
        fake.close()


def sent_commands(fake: FakeGreeDevice) -> list[dict[str, int]]:
    """Return every command the fake got, as column to value."""
    return [
        dict(zip(pack["opt"], pack["p"], strict=True))
        for pack in fake.packs
        if pack.get("t") == "cmd"
    ]


def half_columns(command: dict[str, int]) -> dict[str, int]:
    """Return the half degree columns of one command."""
    return {k: v for k, v in command.items() if k in HALF_COLUMNS}


async def set_and_push(device: GreeDevice, value: float) -> None:
    """Set a target temperature and send it."""
    device.set_target_temperature(value)
    await device.push_device_status()


#
# What the unit offers
#


@pytest.mark.parametrize(
    ("kind", "half", "unit_change"),
    [
        ("tem_rec", True, True),
        ("st_fah_flg", True, True),
        ("add_0_5", True, False),
        ("add_0_1", True, False),
        ("all", True, True),
        ("none", False, False),
    ],
)
async def test_what_a_unit_offers(
    unit_factory: Callable[..., Any], kind: str, half: bool, unit_change: bool
) -> None:
    """Half degrees with any half column, a unit change only with TemUn and a bit."""
    _, device = await unit_factory(UNITS[kind])

    assert device.supports_half_degrees is half
    assert device.supports_temperature_unit_change is unit_change


async def test_a_unit_without_a_bit_is_celsius_only(
    unit_factory: Callable[..., Any],
) -> None:
    """SetTem is always Celsius. Without a bit there is no Fahrenheit table."""
    _, device = await unit_factory(UNITS["add_0_5"], {"TemUn": 1, "SetTem": 22})

    assert device.target_temperature_unit is TemperatureUnits.C
    assert device.target_temperature == 22

    device.set_target_temperature_unit(TemperatureUnits.F)
    assert "TemUn" not in device.gather_diagnostics()["state_pending"]


#
# The step
#


async def test_the_step_follows_the_option_and_the_unit(
    unit_factory: Callable[..., Any],
) -> None:
    """0.5 only in Celsius with the option on and a half column."""
    _, device = await unit_factory(UNITS["tem_rec"])
    assert device.target_temperature_step == 1.0

    device.set_half_degrees(True)
    assert device.half_degrees
    assert device.target_temperature_step == 0.5

    device.set_target_temperature_unit(TemperatureUnits.F)
    assert device.target_temperature_step == 1.0


async def test_the_option_does_nothing_without_a_half_column(
    unit_factory: Callable[..., Any],
) -> None:
    """The option is only offered with a column, but an old config can still hold it."""
    fake, device = await unit_factory(UNITS["none"])
    device.set_half_degrees(True)

    assert not device.half_degrees
    assert device.target_temperature_step == 1.0

    await set_and_push(device, 22.5)
    assert sent_commands(fake)[-1]["SetTem"] == 23
    assert not half_columns(sent_commands(fake)[-1])


#
# What goes over the wire
#


@pytest.mark.parametrize(
    ("kind", "half_sent"),
    [
        ("tem_rec", {"TemRec": 1}),
        ("st_fah_flg", {"StFahFlg": 1}),
        ("add_0_5", {"Add0.5": 1}),
        ("add_0_1", {"Add0.1": 5}),
        ("all", {"TemRec": 1, "Add0.5": 1, "Add0.1": 5}),
    ],
)
async def test_a_half_degree_goes_out_on_every_answered_column(
    unit_factory: Callable[..., Any], kind: str, half_sent: dict[str, int]
) -> None:
    """22.5 is SetTem 22 with the half on each column, and 23 clears them all."""
    fake, device = await unit_factory(UNITS[kind])
    device.set_half_degrees(True)

    await set_and_push(device, 22.5)
    command = sent_commands(fake)[-1]
    assert command["SetTem"] == 22
    assert half_columns(command) == half_sent
    assert device.target_temperature == 22.5

    await set_and_push(device, 23)
    command = sent_commands(fake)[-1]
    assert command["SetTem"] == 23
    assert half_columns(command) == dict.fromkeys(half_sent, 0)
    assert device.target_temperature == 23


@pytest.mark.parametrize(("value", "set_tem"), [(22.5, 23), (23.5, 24), (22.4, 22)])
async def test_with_the_option_off_a_half_degree_rounds_up(
    unit_factory: Callable[..., Any], value: float, set_tem: int
) -> None:
    """Whole degrees only, and a half goes up, not to the even number."""
    fake, device = await unit_factory(UNITS["all"])

    await set_and_push(device, value)

    command = sent_commands(fake)[-1]
    assert command["SetTem"] == set_tem
    assert half_columns(command) == {"TemRec": 0, "Add0.5": 0, "Add0.1": 0}


async def test_with_the_option_off_a_half_set_by_a_remote_still_shows(
    unit_factory: Callable[..., Any],
) -> None:
    """The option sets what Home Assistant sends, not what it reads."""
    _, device = await unit_factory(UNITS["add_0_5"], {"SetTem": 24, "Add0.5": 1})

    assert device.target_temperature == 24.5


async def test_fahrenheit_uses_the_bit_and_clears_the_celsius_columns(
    unit_factory: Callable[..., Any],
) -> None:
    """70 F is SetTem 21 with the bit 1. Add0.5 and Add0.1 have no Fahrenheit meaning."""
    fake, device = await unit_factory(UNITS["all"], {"TemUn": 1})
    device.set_half_degrees(True)

    await set_and_push(device, 70)

    command = sent_commands(fake)[-1]
    assert (command["SetTem"], command["TemRec"]) == (21, 1)
    assert (command["Add0.5"], command["Add0.1"]) == (0, 0)
    assert device.target_temperature == 70


#
# Reading back
#


@pytest.mark.parametrize(
    "half",
    [{"TemRec": 1}, {"Add0.5": 1}, {"Add0.1": 5}],
)
async def test_any_set_column_reads_as_a_half_degree(
    unit_factory: Callable[..., Any], half: dict[str, int]
) -> None:
    """A column the unit ignores reads 0, so any column that is set wins."""
    _, device = await unit_factory(UNITS["all"], {"SetTem": 25, **half})

    assert device.target_temperature == 25.5


async def test_a_column_answered_as_empty_is_dropped(
    unit_factory: Callable[..., Any],
) -> None:
    """The gateway of PR 568 answers TemRec with "". That column is not used."""
    fake, device = await unit_factory({"TemRec", "Add0.1"}, {"TemRec": ""})
    device.set_half_degrees(True)

    assert not device.has_target_temperature_bit
    await set_and_push(device, 27.5)
    assert half_columns(sent_commands(fake)[-1]) == {"Add0.1": 5}


#
# A unit that answers a column and ignores it
#


def command_count(fake: FakeGreeDevice) -> int:
    """Return how many commands the fake got."""
    return len(sent_commands(fake))


async def poll(device: GreeDevice, times: int) -> None:
    """Poll the unit a few times, as the coordinator does."""
    for _ in range(times):
        await device.fetch_device_status()


async def test_an_ignored_column_is_not_sent_again_by_itself(
    unit_factory: Callable[..., Any],
) -> None:
    """The unit takes TemRec and ignores Add0.5. Nothing resends Add0.5."""
    fake, device = await unit_factory({"TemRec", "Add0.5"}, read_only_props={"Add0.5"})
    device.set_half_degrees(True)

    await set_and_push(device, 22.5)
    assert fake.values["TemRec"] == 1
    assert fake.values["Add0.5"] == 0
    assert device.target_temperature == 22.5

    await poll(device, 3)
    assert command_count(fake) == 1
    assert not device.has_held_values
    assert device.target_temperature == 22.5


async def test_an_ignored_column_on_a_sub_unit_ends_with_the_hold(
    unit_factory: Callable[..., Any],
) -> None:
    """A sub-unit holds what it sent. The hold of the ignored column ends at the TTL.

    After that the device shows what the unit reports, sends nothing by itself,
    and has nothing pending.
    """
    now = [1000.0]
    fake, device = await unit_factory({"TemRec", "Add0.5"}, read_only_props={"Add0.5"})
    # Bind a sub-unit behind the same fake, with a clock the test moves
    sub = await bind(fake, f"{fake.mac}01")
    # The hold uses the clock of the state. No public way to set it here.
    sub._state._clock = lambda: now[0]  # noqa: SLF001
    sub.set_half_degrees(True)

    try:
        await set_and_push(sub, 22.5)
        count = command_count(fake)
        assert sub.has_held_values

        await poll(sub, 2)
        assert sub.has_held_values

        now[0] += HELD_VALUE_TTL + 1
        await poll(sub, 2)

        assert not sub.has_held_values
        assert sub.gather_diagnostics()["state_pending"] == {}
        assert command_count(fake) == count
        assert sub.target_temperature == 22.5
    finally:
        if sub.transport is not None:
            await sub.transport.disconnect()
    assert device.is_bound


async def test_a_unit_that_only_answers_an_ignored_column_shows_the_truth(
    unit_factory: Callable[..., Any],
) -> None:
    """Add0.5 answered but ignored: 22.5 lands on 22, and that is what shows."""
    fake, device = await unit_factory({"Add0.5"}, read_only_props={"Add0.5"})
    device.set_half_degrees(True)

    await set_and_push(device, 22.5)
    await poll(device, 2)

    assert device.target_temperature == 22
    assert command_count(fake) == 1
