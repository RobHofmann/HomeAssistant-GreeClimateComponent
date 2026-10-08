"""Tests for `DeviceApiClient`, the bound session with one device.

This is where the bind, the column probe and the diagnostic sweeps live. All of
it runs against a real UDP socket, so the retries and timeouts are real too.

The column probe is the expensive part to get wrong: it decides how many
columns every later poll may carry. A device that answers nothing must not end
up with a wrong limit that stays until the next rebind.
"""

# pylint: disable=redefined-outer-name
# A test takes a fixture as an argument with the same name. That is the
# pytest pattern, not shadowing.

from collections.abc import AsyncIterator

from aiogree import device_api_client
from aiogree.api import POLLED_PROPS, GreeProp
from aiogree.cipher import EncryptionVersion
from aiogree.const import (
    MIN_PACK_PROPS,
    STATUS_CANARY_PROP,
    STATUS_CANARY_PROP_MAX_REQUESTS,
)
from aiogree.device_api_client import DeviceApiClient
from aiogree.errors import GreeBindingError, GreeConnectionError
from aiogree.helpers import gree_encrypt_pack
from aiogree.transport_udp import GreeUdpTransport
import pytest

from .conftest import RecordingHandler
from .fakes.device import (
    DEFAULT_MAC,
    DEFAULT_SESSION_KEY,
    ROTATED_SESSION_KEY,
    FakeGreeDevice,
)
from .fakes.transport import FakePushTransport
from .fakes.vrf import GATEWAY_MAC, FakeVrfGateway, sub_device_macs


@pytest.fixture
async def device() -> AsyncIterator[FakeGreeDevice]:
    """Start a plain device on a free port."""
    fake = FakeGreeDevice()
    await fake.start()
    try:
        yield fake
    finally:
        fake.close()


async def connect(device: FakeGreeDevice) -> tuple[DeviceApiClient, GreeUdpTransport]:
    """Build a client on a transport that points at the fake."""
    transport = GreeUdpTransport(device.host, device.port, max_retries=1, timeout=0.3)
    client = DeviceApiClient(mac=device.mac, userid=0)
    await client.set_transport(transport)
    return client, transport


def status_column_counts(device: FakeGreeDevice) -> list[int]:
    """How many columns each status request carried."""
    return [len(pack["cols"]) for pack in device.packs if pack.get("t") == "status"]


def canary_requests(device: FakeGreeDevice) -> int:
    """How many status requests asked for the canary prop alone."""
    return sum(
        1
        for pack in device.packs
        if pack.get("t") == "status" and pack.get("cols") == [STATUS_CANARY_PROP]
    )


def bind_requests(device: FakeGreeDevice) -> int:
    """How many bind requests reached the device."""
    return sum(1 for pack in device.packs if pack.get("t") == "bind")


async def test_bind_gets_the_key_and_version(device: FakeGreeDevice) -> None:
    """After a bind the client holds the session key the device handed out."""
    client, transport = await connect(device)

    try:
        await client.bind(device.mac)
    finally:
        await transport.disconnect()

    assert client.bound
    assert client.available
    assert client.encryption_key == DEFAULT_SESSION_KEY
    assert client.encryption_version == EncryptionVersion.V1
    assert client.binding_info is not None


async def test_bind_twice_does_nothing(device: FakeGreeDevice) -> None:
    """A second bind on a bound client is a no-op, not a second key exchange."""
    client, transport = await connect(device)

    try:
        await client.bind(device.mac)
        device.reset_record()
        await client.bind(device.mac)
    finally:
        await transport.disconnect()

    assert device.requests == []


async def test_bind_without_a_transport_is_refused() -> None:
    """There is nothing to bind over."""
    client = DeviceApiClient(mac=DEFAULT_MAC, userid=0)

    with pytest.raises(GreeBindingError, match="No transport configured"):
        await client.bind(DEFAULT_MAC)


async def test_bind_without_a_controller_mac_is_refused(
    device: FakeGreeDevice,
) -> None:
    """Every request is addressed to a controller, so the MAC is required."""
    client, transport = await connect(device)

    try:
        with pytest.raises(GreeBindingError, match="No controller MAC provided"):
            await client.bind("  ")
    finally:
        await transport.disconnect()


async def test_a_device_that_never_answers_the_bind(device: FakeGreeDevice) -> None:
    """The bind fails and the client stays unbound."""
    device.answer_bind = False
    client, transport = await connect(device)

    try:
        with pytest.raises(GreeBindingError):
            await client.bind(device.mac)
    finally:
        await transport.disconnect()

    assert not client.bound


async def test_a_device_without_a_column_limit(
    device: FakeGreeDevice, gree_logs: RecordingHandler
) -> None:
    """One probe is enough when the first one passes, and no limit is kept."""
    client, transport = await connect(device)

    try:
        await client.bind(device.mac)
        probes = status_column_counts(device)
        device.reset_record()
        await client.query_props(
            [prop.value for prop in POLLED_PROPS], len(POLLED_PROPS)
        )
    finally:
        await transport.disconnect()

    assert probes == [len(POLLED_PROPS)]
    assert any("are not limited" in line for line in gree_logs.messages())
    assert status_column_counts(device) == [len(POLLED_PROPS)]


async def test_a_device_with_a_column_limit(gree_logs: RecordingHandler) -> None:
    """The probe finds the largest request the device still answers."""
    device = FakeGreeDevice(max_columns=12)
    await device.start()
    client, transport = await connect(device)

    try:
        await client.bind(device.mac)
        device.reset_record()
        await client.query_props(
            [prop.value for prop in POLLED_PROPS], len(POLLED_PROPS)
        )
    finally:
        await transport.disconnect()
        device.close()

    assert any(
        "Status requests are limited to 12 columns" in line
        for line in gree_logs.messages()
    )
    assert max(status_column_counts(device)) == 12


async def test_a_device_that_answers_no_columns_at_all(
    gree_logs: RecordingHandler,
) -> None:
    """Every probe fails. The client falls back to the smallest request."""
    device = FakeGreeDevice(max_columns=0)
    await device.start()
    client, transport = await connect(device)

    try:
        await client.bind(device.mac)
        device.reset_record()
        await client.query_props(
            [prop.value for prop in POLLED_PROPS], len(POLLED_PROPS)
        )
    finally:
        await transport.disconnect()
        device.close()

    assert any(
        "the device may be answering nothing at all" in line
        for line in gree_logs.warnings()
    )
    assert max(status_column_counts(device)) == MIN_PACK_PROPS


async def test_a_query_reports_what_the_device_left_out(
    device: FakeGreeDevice,
) -> None:
    """A device may answer fewer columns than asked. That is normal."""
    device.unsupported_props = {GreeProp.FEAT_TURBO_MODE.value}
    client, transport = await connect(device)

    try:
        await client.bind(device.mac)
        result = await client.query_props(
            [GreeProp.POWER.value, GreeProp.FEAT_TURBO_MODE.value], 2
        )
    finally:
        await transport.disconnect()

    assert result.prop_values == {GreeProp.POWER.value: "1"}
    assert result.missing_props == [GreeProp.FEAT_TURBO_MODE.value]


async def test_a_query_raises_when_the_device_goes_quiet(
    device: FakeGreeDevice,
) -> None:
    """A normal poll must fail loudly, so the entity goes unavailable.

    It sends no canary: the error is raised either way, so a canary would
    only add a wait and a warning to every poll of a unit that is off.
    """
    client, transport = await connect(device)

    try:
        await client.bind(device.mac)
        device.answer_status = False
        device.reset_record()

        with pytest.raises(GreeConnectionError):
            await client.query_props([GreeProp.TARGET_TEMPERATURE.value])
    finally:
        await transport.disconnect()

    assert canary_requests(device) == 0
    assert not client.available


async def test_a_sweep_goes_on_when_the_device_answers_the_canary(
    device: FakeGreeDevice, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A prop the device never answers is missing, and the sweep goes on.

    After each unanswered request one canary request checks that the device
    still talks. It does, so the next prop is asked as normal.
    """
    monkeypatch.setattr(device_api_client, "PROBE_TIMEOUT", 0.2)
    client, transport = await connect(device)

    try:
        await client.bind(device.mac)
        device.ignored_props = {"ElcDatDte", "ElcDatHor"}
        device.reset_record()

        result = await client.query_props(
            [
                GreeProp.TARGET_TEMPERATURE.value,
                "ElcDatDte",
                "ElcDatHor",
                GreeProp.OP_MODE.value,
            ],
            request_batch=1,
            error_as_missing=True,
            max_attempts=1,
        )
    finally:
        await transport.disconnect()

    assert result.prop_values == {
        GreeProp.TARGET_TEMPERATURE.value: "21",
        GreeProp.OP_MODE.value: "1",
    }
    assert sorted(result.missing_props) == ["ElcDatDte", "ElcDatHor"]
    assert canary_requests(device) == 2
    assert client.available


async def test_a_sweep_raises_when_the_device_stops_answering(
    device: FakeGreeDevice, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A device that does not answer the canary either is gone.

    The error is raised even with error_as_missing, so a sweep does not wait
    out every prop on a device that stopped talking.
    """
    monkeypatch.setattr(device_api_client, "PROBE_TIMEOUT", 0.2)
    client, transport = await connect(device)
    props = [f"Prop{i:02d}" for i in range(12)]

    try:
        await client.bind(device.mac)
        device.answer_status = False
        device.reset_record()

        with pytest.raises(GreeConnectionError):
            await client.query_props(
                props, request_batch=1, error_as_missing=True, max_attempts=1
            )
    finally:
        await transport.disconnect()

    assert status_column_counts(device) == [1] * (1 + STATUS_CANARY_PROP_MAX_REQUESTS)
    assert canary_requests(device) == STATUS_CANARY_PROP_MAX_REQUESTS
    assert not client.available


async def test_a_sweep_keeps_going_while_the_device_answers(
    device: FakeGreeDevice,
) -> None:
    """Props the device does not know cost one timeout each, not a whole sweep."""
    client, transport = await connect(device)

    try:
        await client.bind(device.mac)
        device.unsupported_props = {"Unknown1", "Unknown2"}
        result = await client.query_props(
            [GreeProp.POWER.value, "Unknown1", "Unknown2", GreeProp.OP_MODE.value],
            request_batch=1,
            error_as_missing=True,
            max_attempts=1,
        )
    finally:
        await transport.disconnect()

    assert result.prop_values == {
        GreeProp.POWER.value: "1",
        GreeProp.OP_MODE.value: "1",
    }
    assert sorted(result.missing_props) == ["Unknown1", "Unknown2"]


async def test_set_props_reaches_the_device(device: FakeGreeDevice) -> None:
    """A command changes the value the device reports afterwards."""
    client, transport = await connect(device)

    try:
        await client.bind(device.mac)
        await client.set_props({GreeProp.POWER.value: 0})
    finally:
        await transport.disconnect()

    assert device.values[GreeProp.POWER.value] == 0


async def test_a_query_on_an_unbound_client_tries_to_bind_first() -> None:
    """Without a controller MAC there is nothing to rebind to."""
    client = DeviceApiClient(mac=DEFAULT_MAC, userid=0)

    with pytest.raises(GreeBindingError):
        await client.query_props([GreeProp.POWER.value])


async def test_unbind_and_rebind(device: FakeGreeDevice) -> None:
    """A rebind measures the device again, because firmware can change."""
    client, transport = await connect(device)

    try:
        await client.bind(device.mac)
        await client.unbind()

        assert not client.bound
        assert not client.available

        device.reset_record()
        await client.rebind()
    finally:
        await transport.disconnect()

    assert client.bound
    assert client.encryption_key == DEFAULT_SESSION_KEY
    assert status_column_counts(device) == [len(POLLED_PROPS)]


async def test_unbind_on_an_unbound_client_does_nothing() -> None:
    """Calling it twice is safe."""
    client = DeviceApiClient(mac=DEFAULT_MAC, userid=0)

    await client.unbind()

    assert not client.bound


async def test_a_pushed_status_reaches_the_listeners() -> None:
    """Over MQTT the device sends status without being asked."""
    fake = FakeGreeDevice()
    transport = FakePushTransport(fake)
    client = DeviceApiClient(mac=fake.mac, userid=0)
    await client.set_transport(transport)
    await client.bind(fake.mac)

    seen: list[dict[str, str]] = []
    client.add_status_listener(seen.append)

    payload = gree_encrypt_pack(
        {"t": "pack", "pack": {"t": "dat", "cols": ["Pow"], "dat": [1]}},
        fake.session_cipher(),
    )
    transport.push(fake.mac, f"gree/{fake.mac}/status", payload)

    assert seen == [{"Pow": "1"}]


async def test_a_pushed_message_on_another_topic_is_ignored() -> None:
    """Only the status topic carries state."""
    fake = FakeGreeDevice()
    transport = FakePushTransport(fake)
    client = DeviceApiClient(mac=fake.mac, userid=0)
    await client.set_transport(transport)
    await client.bind(fake.mac)

    seen: list[dict[str, str]] = []
    client.add_status_listener(seen.append)

    payload = gree_encrypt_pack(
        {"t": "pack", "pack": {"t": "dat", "cols": ["Pow"], "dat": [1]}},
        fake.session_cipher(),
    )
    transport.push(fake.mac, f"gree/{fake.mac}/res", payload)

    assert not seen


async def test_a_listener_that_raises_does_not_stop_the_others(
    gree_logs: RecordingHandler,
) -> None:
    """One broken entity must not block the rest of the update."""
    fake = FakeGreeDevice()
    transport = FakePushTransport(fake)
    client = DeviceApiClient(mac=fake.mac, userid=0)
    await client.set_transport(transport)
    await client.bind(fake.mac)

    seen: list[dict[str, str]] = []

    def broken(_: dict[str, str]) -> None:
        raise RuntimeError("entity is gone")

    client.add_status_listener(broken)
    client.add_status_listener(seen.append)

    payload = gree_encrypt_pack(
        {"t": "pack", "pack": {"t": "dat", "cols": ["Pow"], "dat": [1]}},
        fake.session_cipher(),
    )
    transport.push(fake.mac, f"gree/{fake.mac}/status", payload)

    assert seen == [{"Pow": "1"}]
    assert any(
        "Error during listener execution" in line for line in gree_logs.messages()
    )


async def test_removing_a_listener_that_is_not_there_is_logged(
    gree_logs: RecordingHandler,
) -> None:
    """It is a programming error, but it must not raise."""
    client = DeviceApiClient(mac=DEFAULT_MAC, userid=0)

    client.remove_status_listener(lambda _: None)

    assert any("not in the listeners list" in line for line in gree_logs.warnings())


async def bind_sub_units(
    gateway: FakeVrfGateway,
) -> tuple[FakePushTransport, list[DeviceApiClient]]:
    """Bind two sub-units of one gateway over one shared transport."""
    transport = FakePushTransport(gateway)
    clients: list[DeviceApiClient] = []

    for mac in sub_device_macs(gateway.mac, 2):
        client = DeviceApiClient(mac=mac, userid=0)
        await client.set_transport(transport)
        await client.bind(gateway.mac)
        clients.append(client)

    return transport, clients


async def test_sub_units_of_one_controller_share_one_bind() -> None:
    """The transport binds once per controller MAC, not once per sub-unit."""
    gateway = FakeVrfGateway()
    sub_macs = sub_device_macs(GATEWAY_MAC, 2)

    transport, clients = await bind_sub_units(gateway)

    assert bind_requests(gateway) == 1
    assert all(client.bound for client in clients)
    assert all(client.encryption_key == DEFAULT_SESSION_KEY for client in clients)
    assert transport.subscriptions == [GATEWAY_MAC]
    assert transport.connections == {GATEWAY_MAC: sub_macs}
    assert transport.listener_macs() == set(sub_macs)


async def test_polling_a_bound_sub_unit_does_not_bind_again() -> None:
    """A poll uses the shared binding, so no key exchange goes out."""
    gateway = FakeVrfGateway()
    sub_macs = sub_device_macs(GATEWAY_MAC, 2)
    _, clients = await bind_sub_units(gateway)
    gateway.reset_record()

    for client in clients:
        result = await client.query_props([GreeProp.POWER.value])
        assert result.prop_values == {GreeProp.POWER.value: "1"}

    assert bind_requests(gateway) == 0
    assert [pack["mac"] for pack in gateway.packs] == sub_macs


async def test_a_forced_rebind_gives_every_sub_unit_the_new_key() -> None:
    """After a key rotation, one forced rebind fixes every sub-unit.

    The other sub-unit stays bound the whole time, so the transport still has
    a binding for the controller. The fresh key must replace it.
    """
    gateway = FakeVrfGateway()
    _, clients = await bind_sub_units(gateway)

    gateway.rotate_key()
    gateway.reset_record()
    await clients[0].rebind(force_bind=True)

    assert bind_requests(gateway) == 1
    assert all(client.encryption_key == ROTATED_SESSION_KEY for client in clients)

    for client in clients:
        result = await client.query_props([GreeProp.POWER.value])
        assert result.prop_values == {GreeProp.POWER.value: "1"}
        assert client.bound


async def test_the_binding_goes_when_the_last_sub_unit_leaves() -> None:
    """The binding lives while any device of the controller is connected."""
    gateway = FakeVrfGateway()
    transport, clients = await bind_sub_units(gateway)

    await clients[0].unbind()

    assert transport.get_controller_binding_info(GATEWAY_MAC) is not None
    assert clients[1].bound
    assert not transport.unsubscriptions

    await clients[1].unbind()

    assert transport.get_controller_binding_info(GATEWAY_MAC) is None
    assert transport.connections == {}
    assert transport.unsubscriptions == [GATEWAY_MAC]
    assert not transport.connected
