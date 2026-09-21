"""A fake aiomqtt client, for the MQTT transport.

This is the one place in the suite where the wire is replaced. MQTT needs a
broker, and running one in a unit test costs more than it proves. What the
transport itself does is worth testing: which topics it subscribes to, how it
matches a response to the request that is waiting, how it counts devices on one
connection, and what it does with a pushed status.

So the broker is faked and everything above it is real. The class below has the
same surface as `aiomqtt.Client` for the parts the transport uses.
"""

import asyncio
from types import TracebackType
from typing import Any, Self


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
