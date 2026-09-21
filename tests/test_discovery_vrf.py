"""Tests for discovery of a VRF gateway and the units behind it.

A gateway answers the scan with `subCnt` above zero. The client then asks it
for the list of indoor units. Real gateways answer that in two shapes, with the
list at the top level or inside an encrypted pack, and both have to work.

These tests were written against `4.0-pre-release` before PR 514, where
discovery of a device with `subCnt` above zero was broken: the request went out
with the generic key and the reply was read as a pack, so the gateway answer
raised `GreeProtocolError` and discovery returned nothing. PR 514 fixed that
and the tests now pass.

Assertions here are on log records as well as on return values. Two of the real
defects found while reviewing PR 514 were log only: a warning that fired when
nothing was wrong, and a warning that could not be formatted because `%d` got
`None`. The `gree_logs` fixture catches the second kind for every test.
"""

# pylint: disable=redefined-outer-name
# A test takes a fixture as an argument with the same name. That is the
# pytest pattern, not shadowing.

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import pytest

from .conftest import DISCOVERY_PORT, DiscoverAll, DiscoverOne, RecordingHandler
from .fakes.device import DEFAULT_SESSION_KEY, FakeGreeDevice
from .fakes.vrf import GATEWAY_MAC, FakeVrfGateway

GatewayFactory = Callable[..., Awaitable[FakeVrfGateway]]


@pytest.fixture
async def gateway_factory(loopback_ip: str) -> AsyncIterator[GatewayFactory]:
    """Build a gateway on the discovery port and clean it up afterwards."""
    started: list[FakeVrfGateway] = []

    async def _build(**kwargs: Any) -> FakeVrfGateway:
        gateway = FakeVrfGateway(**kwargs)
        await gateway.start(loopback_ip, DISCOVERY_PORT)
        started.append(gateway)
        return gateway

    try:
        yield _build
    finally:
        for gateway in started:
            gateway.close()


@pytest.mark.parametrize("list_shape", ["top", "pack"])
async def test_a_gateway_reports_all_its_units(
    gateway_factory: GatewayFactory,
    discover_one: DiscoverOne,
    gree_logs: RecordingHandler,
    list_shape: str,
) -> None:
    """Four promised units, four delivered, in either reply shape."""
    gateway = await gateway_factory(sub_count=4, list_shape=list_shape)

    found = await discover_one(gateway.host, timeout=1)

    assert len(found) == 4
    assert gree_logs.warnings() == []


@pytest.mark.parametrize("list_shape", ["top", "pack"])
async def test_a_gateway_that_delivers_fewer_units_than_it_promised(
    gateway_factory: GatewayFactory,
    discover_one: DiscoverOne,
    gree_logs: RecordingHandler,
    list_shape: str,
) -> None:
    """Three of four come back. The three are used and one warning is logged."""
    gateway = await gateway_factory(sub_count=4, returned=3, list_shape=list_shape)

    found = await discover_one(gateway.host, timeout=1)

    assert len(found) == 3
    assert gree_logs.warnings() == [
        f"[{GATEWAY_MAC}] Expected 4 sub-devices and found 3"
    ]


async def test_a_gateway_that_returns_an_empty_list(
    gateway_factory: GatewayFactory,
    discover_one: DiscoverOne,
    gree_logs: RecordingHandler,
) -> None:
    """An empty list is not an exception. It is a warning and no devices."""
    gateway = await gateway_factory(sub_count=4, returned=0)

    found = await discover_one(gateway.host, timeout=1)

    assert found == []
    assert gree_logs.warnings() == [
        f"[{GATEWAY_MAC}] Expected 4 sub-devices and found 0"
    ]


async def test_every_sub_unit_is_addressable(
    gateway_factory: GatewayFactory, discover_one: DiscoverOne
) -> None:
    """Each unit needs its own name, the controller MAC and the bound key."""
    gateway = await gateway_factory(sub_count=4)

    found = await discover_one(gateway.host, timeout=1)

    assert len({dev.mac for dev in found}) == 4
    assert len({dev.name for dev in found}) == 4
    assert {dev.mac_controller_local for dev in found} == {GATEWAY_MAC}
    assert {dev.key for dev in found} == {DEFAULT_SESSION_KEY}
    assert {dev.host for dev in found} == {gateway.host}


async def test_the_sub_device_request_uses_the_bound_key(
    gateway_factory: GatewayFactory, discover_one: DiscoverOne
) -> None:
    """The gateway is bound first, so the request is readable with its key."""
    gateway = await gateway_factory(sub_count=4)

    await discover_one(gateway.host, timeout=1)

    assert gateway.sublist_key_used == "session"
    assert gateway.sublist_requests[0]["i"] == 0


async def test_a_gateway_that_never_answers_the_bind_does_not_lose_the_others(
    loopback_ips: Callable[[int], list[str]],
    discover_all: DiscoverAll,
    gree_logs: RecordingHandler,
) -> None:
    """One dead gateway must not take the rest of the network down with it."""
    gateway_ip, plain_ip = loopback_ips(2)
    gateway = FakeVrfGateway(sub_count=4, answer_bind=False)
    plain = FakeGreeDevice(mac="f4911e3f1ac8", name="Zolderkamer")
    await gateway.start(gateway_ip, DISCOVERY_PORT)
    await plain.start(plain_ip, DISCOVERY_PORT)

    try:
        found = await discover_all([gateway_ip, plain_ip], timeout=1)
    finally:
        gateway.close()
        plain.close()

    assert [dev.mac for dev in found] == ["f4911e3f1ac8"]
    assert any(
        "Could not connect to VRF gateway" in line for line in gree_logs.warnings()
    )


async def test_a_gateway_that_never_answers_the_list_does_not_lose_the_others(
    loopback_ips: Callable[[int], list[str]],
    discover_all: DiscoverAll,
) -> None:
    """The gateway binds and then goes quiet. The plain device is still found.

    This one is slow on `4.0-pre-release`, about 8 seconds, because the old
    code builds its own transport with the default 3 retries and 2 second
    timeout. With PR 514 the retries come from the caller and it drops to
    about 2 seconds.
    """
    gateway_ip, plain_ip = loopback_ips(2)
    gateway = FakeVrfGateway(sub_count=4, answer_sublist=False)
    plain = FakeGreeDevice(mac="f4911e3f1ac8", name="Zolderkamer")
    await gateway.start(gateway_ip, DISCOVERY_PORT)
    await plain.start(plain_ip, DISCOVERY_PORT)

    try:
        found = await discover_all([gateway_ip, plain_ip], timeout=1)
    finally:
        gateway.close()
        plain.close()

    assert [dev.mac for dev in found] == ["f4911e3f1ac8"]


async def test_a_plain_device_is_untouched_by_any_of_this(
    loopback_ip: str, discover_one: DiscoverOne, gree_logs: RecordingHandler
) -> None:
    """A device without subCnt never asks for a sub-device list."""
    device = FakeGreeDevice(mac="f4911e3f1ac8", name="Zolderkamer")
    await device.start(loopback_ip, DISCOVERY_PORT)

    try:
        found = await discover_one(device.host, timeout=1)
    finally:
        device.close()

    assert len(found) == 1
    assert found[0].mac == "f4911e3f1ac8"
    assert [req.get("t") for req in device.requests] == ["scan"]
    assert gree_logs.warnings() == []
