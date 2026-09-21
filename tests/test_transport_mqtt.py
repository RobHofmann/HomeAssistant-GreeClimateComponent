"""Tests for the MQTT transport.

The broker is faked here, see `tests/fakes/mqtt.py` for why. Everything above
it is the shipped code: the topics it follows, how it matches a response to the
request that is waiting, how it counts devices on one connection, and what it
does with a status the device pushes on its own.
"""

# pylint: disable=redefined-outer-name
# A test takes a fixture as an argument with the same name. That is the
# pytest pattern, not shadowing.

import asyncio
from collections.abc import AsyncIterator
import json

from aiogree import transport_mqtt
from aiogree.cloud_api import GreeRegion
from aiogree.errors import GreeRuntimeError
from aiogree.transport_mqtt import MQTT_SERVERS, GreeMqttTransport
import pytest

from .conftest import RecordingHandler
from .fakes.mqtt import FakeMqttClient

MAC = "9424b8fd5ba3"


@pytest.fixture
async def transport(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[GreeMqttTransport]:
    """Build an MQTT transport wired to a fake broker."""
    FakeMqttClient.instances.clear()
    monkeypatch.setattr(transport_mqtt.aiomqtt, "Client", FakeMqttClient)

    mqtt = GreeMqttTransport(
        user_id="4242", token="cloud-token", region=GreeRegion.EU, timeout=0.5
    )
    try:
        yield mqtt
    finally:
        await mqtt.disconnect()


def broker() -> FakeMqttClient:
    """Return the client the transport built last."""
    return FakeMqttClient.instances[-1]


async def settle() -> None:
    """Let the receive loop pick up what was just delivered."""
    await asyncio.sleep(0.05)


def test_every_region_has_a_broker() -> None:
    """A region without a host would fail at connect with a KeyError."""
    assert set(MQTT_SERVERS) == set(GreeRegion)


async def test_connect_uses_the_broker_of_the_region(
    transport: GreeMqttTransport,
) -> None:
    """The account credentials go in as the MQTT user and password."""
    await transport.connect()

    assert broker().entered
    assert broker().options["hostname"] == MQTT_SERVERS[GreeRegion.EU]
    assert broker().options["username"] == "4242"
    assert broker().options["password"] == "cloud-token"
    assert broker().options["identifier"] == f"app_{transport.cid}"


async def test_connecting_twice_reuses_the_connection(
    transport: GreeMqttTransport,
) -> None:
    """One broker connection carries every device on the account."""
    await transport.connect()
    await transport.connect()

    assert len(FakeMqttClient.instances) == 1


async def test_subscribe_follows_the_three_topics(
    transport: GreeMqttTransport,
) -> None:
    """Responses, pushed status and the connect message each have a topic."""
    await transport.subscribe(MAC)

    assert broker().subscriptions == [
        f"response/{MAC}/#",
        f"status/{MAC}/#",
        f"connect/{MAC}",
    ]


async def test_a_second_device_does_not_subscribe_twice(
    transport: GreeMqttTransport,
) -> None:
    """Two entities on one device share the subscription."""
    await transport.subscribe(MAC)
    await transport.subscribe(MAC)

    assert len(broker().subscriptions) == 3


async def test_the_last_device_closes_the_connection(
    transport: GreeMqttTransport,
) -> None:
    """The connection stays open while anything is still using it."""
    await transport.subscribe(MAC)
    await transport.subscribe(MAC)

    await transport.unsubscribe(MAC)
    assert not broker().exited

    await transport.unsubscribe(MAC)
    assert broker().unsubscriptions == [
        f"response/{MAC}/#",
        f"status/{MAC}/#",
        f"connect/{MAC}",
    ]
    assert broker().exited


async def test_a_request_is_published_and_waits_for_its_response(
    transport: GreeMqttTransport,
) -> None:
    """MQTT has no retries. One request, one response."""
    await transport.subscribe(MAC)

    task = asyncio.ensure_future(transport.request(MAC, '{"t":"status"}'))
    await settle()

    assert broker().published == [(f"request/{MAC}", '{"t":"status"}')]

    broker().deliver(f"response/{MAC}/x", '{"t":"dat"}')

    assert await task == '{"t":"dat"}'


async def test_a_request_without_an_answer_times_out(
    transport: GreeMqttTransport,
) -> None:
    """The caller must not wait forever on a broker that says nothing."""
    await transport.subscribe(MAC)

    with pytest.raises(TimeoutError):
        await transport.request(MAC, '{"t":"status"}', timeout=0.1)


async def test_a_request_before_connecting_is_refused(
    transport: GreeMqttTransport,
) -> None:
    """There is no broker to publish to yet."""
    with pytest.raises(GreeRuntimeError, match="Transport not connected"):
        await transport.request(MAC, '{"t":"status"}')


async def test_unsubscribe_before_connecting_is_refused(
    transport: GreeMqttTransport,
) -> None:
    """Nothing was ever followed."""
    with pytest.raises(GreeRuntimeError, match="not connected"):
        await transport.unsubscribe(MAC)


async def test_a_pushed_status_reaches_the_listeners(
    transport: GreeMqttTransport,
) -> None:
    """The device sends state without being asked. That is the point of MQTT."""
    await transport.subscribe(MAC)
    seen: list[tuple[str, dict]] = []
    transport.add_listener(MAC, lambda topic, payload: seen.append((topic, payload)))

    broker().deliver(f"status/{MAC}/1", json.dumps({"t": "pack", "pack": "abc"}))
    await settle()

    assert seen == [(f"status/{MAC}/1", {"t": "pack", "pack": "abc"})]


async def test_a_status_for_another_device_is_ignored(
    transport: GreeMqttTransport,
) -> None:
    """One connection carries every device, so the MAC has to match."""
    await transport.subscribe(MAC)
    seen: list[tuple[str, dict]] = []
    transport.add_listener(MAC, lambda topic, payload: seen.append((topic, payload)))

    broker().deliver("status/c03937b12280/1", json.dumps({"t": "pack"}))
    await settle()

    assert not seen


async def test_a_listener_that_raises_is_logged(
    transport: GreeMqttTransport, gree_logs: RecordingHandler
) -> None:
    """One broken entity must not stop the receive loop."""
    await transport.subscribe(MAC)

    def broken(topic: str, payload: dict) -> None:
        raise RuntimeError("entity is gone")

    transport.add_listener(MAC, broken)
    broker().deliver(f"status/{MAC}/1", json.dumps({"t": "pack"}))
    await settle()

    assert any("MQTT listener raised" in line for line in gree_logs.messages())


async def test_a_listener_can_be_removed(transport: GreeMqttTransport) -> None:
    """An entity that goes away stops hearing about the device."""
    await transport.subscribe(MAC)
    seen: list[str] = []

    def listener(topic: str, payload: dict) -> None:
        seen.append(topic)

    transport.add_listener(MAC, listener)
    transport.remove_listener(MAC, listener)
    transport.remove_listener(MAC, listener)

    broker().deliver(f"status/{MAC}/1", json.dumps({"t": "pack"}))
    await settle()

    assert not seen


async def test_disconnect_is_safe_when_nothing_is_connected(
    transport: GreeMqttTransport,
) -> None:
    """Calling it twice must not raise."""
    await transport.disconnect()
    await transport.disconnect()

    assert not FakeMqttClient.instances


def test_the_transport_names_itself_by_account_and_region(
    transport: GreeMqttTransport,
) -> None:
    """Log lines carry this, so it has to say which account and region."""
    assert str(transport) == "MQTT(4242, EU)"
