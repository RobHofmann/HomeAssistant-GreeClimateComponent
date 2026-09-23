"""Tests for discovery of a VRF gateway and the units behind it.

A gateway answers the scan with `subCnt` above zero. The client then asks it
for the list of indoor units. Real gateways answer that in two shapes, with the
list at the top level or inside an encrypted pack, and both have to work.

The request itself has three forms (device key, generic key, subDev), and a
WiFi module may answer only some of them, each with its own subset of units.
The client asks all of them and joins the lists by MAC.

These tests were written against the code before PR 514, where
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

from aiogree.api import SubListForm, _get_sub_devices_list
from aiogree.cipher import EncryptionVersion, get_cipher
from aiogree.transport_udp import GreeUdpTransport
import pytest

from .conftest import DISCOVERY_PORT, DiscoverAll, DiscoverOne, RecordingHandler
from .fakes.device import DEFAULT_SESSION_KEY, FakeGreeDevice
from .fakes.vrf import GATEWAY_MAC, FakeVrfGateway, sub_device_macs

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


async def test_every_form_is_sent_with_the_bound_key(
    gateway_factory: GatewayFactory, discover_one: DiscoverOne
) -> None:
    """The gateway is bound first, so each form is readable with its key."""
    gateway = await gateway_factory(sub_count=4)

    await discover_one(gateway.host, timeout=1)

    assert gateway.sublist_forms == [
        SubListForm.DEVICE_KEY,
        SubListForm.GENERIC_KEY,
        SubListForm.SUB_DEV,
    ]
    assert gateway.sublist_keys == ["session", "session", "session"]
    assert [(req["t"], req["i"]) for req in gateway.sublist_requests] == [
        ("pack", 0),
        ("subList", 1),
        ("pack", 0),
    ]


@pytest.mark.parametrize("list_shape", ["top", "pack"])
async def test_the_forms_are_joined_by_mac(
    gateway_factory: GatewayFactory,
    discover_one: DiscoverOne,
    gree_logs: RecordingHandler,
    list_shape: str,
) -> None:
    """Four units from the device key form and three from the generic one make four.

    This is what the GR-Gcloud V3.2.M gateway in PR 507 answered.
    """
    gateway = await gateway_factory(
        sub_count=4,
        list_shape=list_shape,
        forms={
            SubListForm.DEVICE_KEY: [0, 1, 2, 3],
            SubListForm.GENERIC_KEY: [0, 1, 2],
        },
    )

    found = await discover_one(gateway.host, timeout=1)

    assert [dev.mac for dev in found] == sub_device_macs(GATEWAY_MAC, 4)
    assert not any("sub-devices" in line for line in gree_logs.warnings())
    assert (
        f"[{GATEWAY_MAC}] Sub-device list per form: device-key=4, "
        "generic-key=3, subDev=n/a, merged=4"
    ) in gree_logs.messages()


async def test_units_that_only_one_form_knows_are_kept_in_first_seen_order(
    gateway_factory: GatewayFactory, discover_one: DiscoverOne
) -> None:
    """Each form adds the units the earlier forms did not have."""
    gateway = await gateway_factory(
        sub_count=4,
        forms={
            SubListForm.DEVICE_KEY: [0, 1],
            SubListForm.GENERIC_KEY: [3, 1],
            SubListForm.SUB_DEV: [2, 0],
        },
    )

    found = await discover_one(gateway.host, timeout=1)

    macs = sub_device_macs(GATEWAY_MAC, 4)
    assert [dev.mac for dev in found] == [macs[0], macs[1], macs[3], macs[2]]


async def test_a_gateway_that_only_answers_the_generic_key_form(
    gateway_factory: GatewayFactory,
    discover_one: DiscoverOne,
    gree_logs: RecordingHandler,
) -> None:
    """One unit behind the gateway, found through the generic key form alone.

    The reply comes in a pack encrypted with the generic key, while the request
    used the bound key. Reading the reply with the bound key would fail.
    """
    gateway = await gateway_factory(
        sub_count=1, list_shape="pack", forms={SubListForm.GENERIC_KEY: None}
    )

    found = await discover_one(gateway.host, timeout=1)

    assert [dev.mac for dev in found] == sub_device_macs(GATEWAY_MAC, 1)
    assert found[0].key == DEFAULT_SESSION_KEY
    assert not any("sub-devices" in line for line in gree_logs.warnings())


async def test_a_gateway_that_only_answers_the_sub_dev_form(
    gateway_factory: GatewayFactory,
    discover_one: DiscoverOne,
    gree_logs: RecordingHandler,
) -> None:
    """An older W06 module only knows subDev."""
    gateway = await gateway_factory(
        sub_count=2, list_shape="pack", forms={SubListForm.SUB_DEV: None}
    )

    found = await discover_one(gateway.host, timeout=1)

    assert [dev.mac for dev in found] == sub_device_macs(GATEWAY_MAC, 2)
    assert not any("sub-devices" in line for line in gree_logs.warnings())


async def test_a_gateway_that_answers_no_form_gives_nothing_and_warns(
    gateway_factory: GatewayFactory,
    discover_one: DiscoverOne,
    gree_logs: RecordingHandler,
) -> None:
    """Each form is tried, then one warning says why no units came back."""
    gateway = await gateway_factory(sub_count=4, answer_sublist=False)

    found = await discover_one(gateway.host, timeout=1)

    assert found == []
    assert len(gateway.sublist_forms) == 3
    assert [line for line in gree_logs.warnings() if "sub-devices" in line] == [
        f"[{GATEWAY_MAC}] VRF gateway did not answer any form of the sub-device list request. Its sub-devices will be ignored"
    ]


async def test_a_v2_gateway_is_only_asked_the_device_key_form() -> None:
    """Only the device key form is known to work with AES-GCM.

    This calls the list query straight away with the bound key, because the
    fake answers a scan in V2 and discovery reads scan replies in V1.
    """
    gateway = FakeVrfGateway(
        sub_count=4, list_shape="pack", encryption_version=EncryptionVersion.V2
    )
    await gateway.start()
    transport = GreeUdpTransport(gateway.host, gateway.port, max_retries=1, timeout=1)

    try:
        found = await _get_sub_devices_list(
            GATEWAY_MAC,
            0,
            get_cipher(EncryptionVersion.V2, DEFAULT_SESSION_KEY),
            transport,
            expected=4,
        )
    finally:
        await transport.disconnect()
        gateway.close()

    assert [dev.mac for dev in found] == sub_device_macs(GATEWAY_MAC, 4)
    assert gateway.sublist_forms == [SubListForm.DEVICE_KEY]


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

    This one was slow before PR 514, about 8 seconds, because the old
    code built its own transport with the default 3 retries and 2 second
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


async def test_gateways_are_asked_for_their_units_at_the_same_time(
    loopback_ips: Callable[[int], list[str]],
    discover_all: DiscoverAll,
) -> None:
    """Two slow gateways do not wait for each other.

    Both only answer the last form, so each spends about two seconds on the
    two forms before it. One after another, the second gateway would get its
    first sub-device request about two seconds after the first one.
    """
    first_ip, second_ip = loopback_ips(2)
    first = FakeVrfGateway(sub_count=2, forms={SubListForm.SUB_DEV: None})
    second = FakeVrfGateway(
        mac="9424b8fd5ba4", sub_count=2, forms={SubListForm.SUB_DEV: None}
    )
    await first.start(first_ip, DISCOVERY_PORT)
    await second.start(second_ip, DISCOVERY_PORT)

    try:
        found = await discover_all([first_ip, second_ip], timeout=1)
    finally:
        first.close()
        second.close()

    assert sorted(dev.mac for dev in found) == sorted(
        sub_device_macs(first.mac, 2) + sub_device_macs(second.mac, 2)
    )
    assert abs(first.sublist_times[0] - second.sublist_times[0]) < 0.5


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
