"""Tests for local discovery of plain devices.

Discovery has no port argument, so every fake here binds the protocol port on
its own loopback address. `async_udp_broadcast_request` keys replies by source
IP, so two devices need two addresses, not two ports.

The listen window is a plain `asyncio.sleep`. Discovery does not stop early
when it has heard from everyone, so a test with a 5 second window takes 5
seconds. Keep windows short unless the test is about the window.
"""

# pylint: disable=redefined-outer-name
# A test takes a fixture as an argument with the same name. That is the
# pytest pattern, not shadowing.

from collections.abc import AsyncIterator, Callable

from aiogree.transport_udp import GreeUdpTransport
import pytest

from .conftest import DISCOVERY_PORT, DiscoverAll, DiscoverOne, RecordingHandler
from .fakes.device import DEFAULT_MAC, FakeGreeDevice


@pytest.fixture
async def device(loopback_ip: str) -> AsyncIterator[FakeGreeDevice]:
    """One plain device on the discovery port."""
    fake = FakeGreeDevice(name="Zolderkamer")
    await fake.start(loopback_ip, DISCOVERY_PORT)
    try:
        yield fake
    finally:
        fake.close()


async def test_one_device_answers_a_broadcast(
    device: FakeGreeDevice, discover_all: DiscoverAll
) -> None:
    """A device that answers the scan comes back with its MAC, host and name."""
    found = await discover_all([device.host], timeout=1)

    assert len(found) == 1
    assert found[0].mac == DEFAULT_MAC
    assert found[0].mac_controller_local == DEFAULT_MAC
    assert found[0].host == device.host
    assert found[0].port == DISCOVERY_PORT
    assert found[0].name == "Zolderkamer"


async def test_one_device_answers_a_targeted_scan(
    device: FakeGreeDevice, discover_one: DiscoverOne
) -> None:
    """A targeted scan finds the same device."""
    found = await discover_one(device.host, timeout=1)

    assert len(found) == 1
    assert found[0].mac == DEFAULT_MAC
    assert found[0].host == device.host


async def test_a_scan_closes_the_transport_it_opened(
    device: FakeGreeDevice, discover_one: DiscoverOne, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A targeted scan builds its own transport, so it has to close it too."""
    closed: list[str] = []
    original = GreeUdpTransport.disconnect

    async def spy(self: GreeUdpTransport) -> None:
        closed.append(self.ip_addr)
        await original(self)

    monkeypatch.setattr(GreeUdpTransport, "disconnect", spy)

    await discover_one(device.host, timeout=1)

    assert closed == [device.host]


async def test_a_device_that_never_answers_gives_an_empty_list(
    loopback_ip: str, discover_all: DiscoverAll
) -> None:
    """Silence is not an error. Nothing is found and nothing is raised."""
    device = FakeGreeDevice(answer_scan=False)
    await device.start(loopback_ip, DISCOVERY_PORT)

    try:
        found = await discover_all([device.host], timeout=1)
    finally:
        device.close()

    assert found == []
    assert len(device.requests) == 1


async def test_two_devices_on_two_addresses_are_both_found(
    loopback_ips: Callable[[int], list[str]], discover_all: DiscoverAll
) -> None:
    """Replies are keyed by source IP, so each device needs its own address."""
    first_ip, second_ip = loopback_ips(2)
    first = FakeGreeDevice(mac="f4911e3f1ac8", name="Zolderkamer")
    second = FakeGreeDevice(mac="9424b8fd5ba3", name="Woonkamer")
    await first.start(first_ip, DISCOVERY_PORT)
    await second.start(second_ip, DISCOVERY_PORT)

    try:
        found = await discover_all([first_ip, second_ip], timeout=1)
    finally:
        first.close()
        second.close()

    assert sorted(dev.mac for dev in found) == ["9424b8fd5ba3", "f4911e3f1ac8"]
    assert sorted(dev.name for dev in found) == ["Woonkamer", "Zolderkamer"]


async def test_a_slow_device_is_found_inside_the_listen_window(
    loopback_ip: str, discover_all: DiscoverAll
) -> None:
    """A device that takes 3 seconds still fits in a 5 second window."""
    device = FakeGreeDevice(scan_delay=3.0)
    await device.start(loopback_ip, DISCOVERY_PORT)

    try:
        found = await discover_all([device.host], timeout=5)
    finally:
        device.close()

    assert len(found) == 1


async def test_a_slow_device_is_missed_outside_the_listen_window(
    loopback_ip: str, discover_all: DiscoverAll
) -> None:
    """The same device is missed with a 2 second window.

    This is the cost of a shorter `DEFAULT_DISCOVERY_TIMEOUT`. The two tests
    together show what a change of that constant buys and what it loses.
    """
    device = FakeGreeDevice(scan_delay=3.0)
    await device.start(loopback_ip, DISCOVERY_PORT)

    try:
        found = await discover_all([device.host], timeout=2)
    finally:
        device.close()

    assert found == []


async def test_a_reply_that_is_not_json_does_not_stop_the_others(
    loopback_ips: Callable[[int], list[str]],
    discover_all: DiscoverAll,
    gree_logs: RecordingHandler,
) -> None:
    """One broken reply is logged. The other device is still found."""
    broken_ip, good_ip = loopback_ips(2)
    broken = FakeGreeDevice(raw_reply=b"this is not json")
    good = FakeGreeDevice(mac="9424b8fd5ba3", name="Woonkamer")
    await broken.start(broken_ip, DISCOVERY_PORT)
    await good.start(good_ip, DISCOVERY_PORT)

    try:
        found = await discover_all([broken_ip, good_ip], timeout=1)
    finally:
        broken.close()
        good.close()

    assert [dev.mac for dev in found] == ["9424b8fd5ba3"]
    assert any("Could not parse JSON" in line for line in gree_logs.messages())


async def test_a_reply_without_a_mac_is_skipped(
    loopback_ip: str, discover_all: DiscoverAll, gree_logs: RecordingHandler
) -> None:
    """A device with an empty MAC cannot be addressed, so it is dropped.

    Note that this covers an empty MAC. A scan reply with no `mac` key at all
    fails the model validation instead, which is a different path.
    """
    device = FakeGreeDevice(scan_info={"mac": "", "cid": ""})
    await device.start(loopback_ip, DISCOVERY_PORT)

    try:
        found = await discover_all([device.host], timeout=1)
    finally:
        device.close()

    assert found == []
    assert any("No MAC address in response" in line for line in gree_logs.messages())
