"""A fake aiomqtt client, for the MQTT transport.

This is the one place in the suite where the wire is replaced. MQTT needs a
broker, and running one in a unit test costs more than it proves. What the
transport itself does is worth testing: which topics it subscribes to, how it
matches a response to the request that is waiting, how it counts devices on one
connection, and what it does with a pushed status.

So the broker is faked and everything above it is real. The class below has the
same surface as `aiomqtt.Client` for the parts the transport uses.

`FakeMqttBroker` goes one step further, for the config flow tests. It hands
every request to a `FakeGreeDevice` and sends the reply back on the response
topic, so a bind over the cloud runs the real protocol end to end. It can also
refuse the connection, as the Gree broker does with a stale token, and it can
accept only some tokens, as the Gree broker does after a new login.
"""

import asyncio
import json
from types import TracebackType
from typing import TYPE_CHECKING, Any, Self, override

from aiomqtt.exceptions import MqttConnectError
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.reasoncodes import ReasonCode

if TYPE_CHECKING:
    from .device import FakeGreeDevice

# The MQTT 3.1.1 return code for a refused user name or password.
CONNACK_NOT_AUTHORIZED = 5


def connack_reason(name: str) -> ReasonCode:
    """Return a CONNACK reason the way paho 2 reports it, also for MQTT 3.1.1.

    paho turns the 3.1.1 return code 4 into "Bad user name or password"
    (code 134), so that is what aiomqtt puts in `MqttConnectError.rc`.
    """
    return ReasonCode(PacketTypes.CONNACK, name)


class FakeMqttMessage:
    """One message, shaped like the aiomqtt one."""

    def __init__(self, topic: str, payload: str) -> None:
        """Hold a topic and a payload."""
        self.topic = topic
        self.payload = payload.encode()


class FakeMqttClient:
    """Stands in for `aiomqtt.Client`."""

    # Every client built during one test, newest last.
    instances: list[FakeMqttClient] = []

    def __init__(self, **kwargs: Any) -> None:
        """Record how the transport configured the client."""
        self.options = kwargs
        self.subscriptions: list[str] = []
        self.unsubscriptions: list[str] = []
        self.published: list[tuple[str, str]] = []
        self.entered = False
        self.exited = False

        self._queue: asyncio.Queue[FakeMqttMessage] = asyncio.Queue()
        FakeMqttClient.instances.append(self)

    async def __aenter__(self) -> Self:
        """Open the connection."""
        self.entered = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close the connection."""
        self.exited = True

    async def subscribe(self, topic: str, qos: int = 0) -> None:
        """Follow a topic."""
        self.subscriptions.append(topic)

    async def unsubscribe(self, topic: str) -> None:
        """Stop following a topic."""
        self.unsubscriptions.append(topic)

    async def publish(self, topic: str, payload: str, qos: int = 0) -> None:
        """Send one message."""
        self.published.append((topic, payload))

    def deliver(self, topic: str, payload: str) -> None:
        """Hand a message to the receive loop, as a broker would."""
        self._queue.put_nowait(FakeMqttMessage(topic, payload))

    @property
    def messages(self) -> FakeMqttMessages:
        """The stream the transport reads in its receive loop."""
        return FakeMqttMessages(self._queue)


class FakeMqttMessages:
    """An endless stream of messages, like the aiomqtt one."""

    def __init__(self, queue: asyncio.Queue[FakeMqttMessage]) -> None:
        """Read from this queue."""
        self._queue = queue

    def __aiter__(self) -> Self:
        """Iterate over the messages."""
        return self

    async def __anext__(self) -> FakeMqttMessage:
        """Wait for the next message."""
        return await self._queue.get()


class FakeMqttBroker:
    """A broker that answers every request with a fake device.

    Install `client` in place of `aiomqtt.Client`. Each client the code under
    test builds is kept in `clients`, so a test can tell which connections are
    still open when a flow or an entry is done.
    """

    def __init__(self) -> None:
        """Start with no devices and a broker that accepts every login."""
        self.devices: dict[str, FakeGreeDevice] = {}
        # Refuse every connection with this reason
        self.refuse_connect = False
        self.refuse_reason: int | ReasonCode = CONNACK_NOT_AUTHORIZED
        # When set, only these tokens may connect. The others get "Bad user
        # name or password", as a token that a newer login replaced.
        self.accepted_tokens: set[str] | None = None
        self.clients: list[BrokerClient] = []

    def add(self, device: FakeGreeDevice, mac_controller: str | None = None) -> None:
        """Answer the requests for one controller MAC with this device."""
        self.devices[mac_controller or device.mac] = device

    def client(self, **kwargs: Any) -> BrokerClient:
        """Build a client, the way `aiomqtt.Client(...)` does."""
        client = BrokerClient(self, **kwargs)
        self.clients.append(client)
        return client

    def open_clients(self) -> list[BrokerClient]:
        """Return the clients that connected and did not disconnect."""
        return [c for c in self.clients if c.entered and not c.exited]


class BrokerClient(FakeMqttClient):
    """A fake client whose requests reach a fake device."""

    def __init__(self, broker: FakeMqttBroker, **kwargs: Any) -> None:
        """Remember the broker this client talks to."""
        super().__init__(**kwargs)
        self.broker = broker

    @override
    async def __aenter__(self) -> Self:
        """Open the connection, unless the broker refuses the login."""
        if self.broker.refuse_connect:
            raise MqttConnectError(self.broker.refuse_reason)
        accepted = self.broker.accepted_tokens
        if accepted is not None and self.options.get("password") not in accepted:
            raise MqttConnectError(connack_reason("Bad user name or password"))
        return await super().__aenter__()

    @override
    async def publish(self, topic: str, payload: str, qos: int = 0) -> None:
        """Send one message, and deliver the reply of the device it is for."""
        await super().publish(topic, payload, qos)

        kind, _, mac = topic.partition("/")
        device = self.broker.devices.get(mac)
        if kind != "request" or device is None:
            return

        envelope = json.loads(payload)
        device.requests.append(envelope)

        reply = device.handle(envelope)
        if reply is not None:
            self.deliver(f"response/{mac}/app", json.dumps(reply))
