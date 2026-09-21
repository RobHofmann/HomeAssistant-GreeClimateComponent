"""An in-memory transport, for the paths the UDP transport does not have.

Everything that goes over the wire is tested against a real socket. This
transport exists for the two things UDP cannot show:

- Pushed status. Only the MQTT transport calls its listeners. A real MQTT
  broker in a unit test would cost more than it proves, so the push is fired
  here by hand.
- A transport that cannot batch. `GreeMqttTransport` sets `batch_support` to
  False, which makes `request_json()` split a command into one request per
  option.

It answers with `FakeGreeDevice`, so the protocol itself is still the real
thing. Only the wire is missing.
"""

import json
from typing import Any, override

from aiogree.errors import GreeConnectionError
from aiogree.transport import GreeBaseTransport

from .device import FakeGreeDevice


class FakePushTransport(GreeBaseTransport):
    """A transport that talks to a fake device in memory and can push."""

    batch_support = False

    def __init__(self, device: FakeGreeDevice) -> None:
        """Wrap a fake device."""
        super().__init__()
        self.device = device
        self.connected = False
        self.subscriptions: list[str] = []

    @override
    def __str__(self) -> str:
        """Representation of the class."""
        return f"Fake({self.device.mac})"

    @override
    async def connect(self) -> None:
        """Mark the transport as connected."""
        self.connected = True

    @override
    async def disconnect(self) -> None:
        """Mark the transport as disconnected."""
        self.connected = False

    @override
    async def subscribe(self, mac_controller: str) -> None:
        """Start following one device."""
        await self.connect()
        self.subscriptions.append(mac_controller)
        self.connected_devices[mac_controller] += 1

    @override
    async def unsubscribe(self, mac_controller: str) -> None:
        """Stop following one device."""
        self.connected_devices.pop(mac_controller, None)
        if not self.connected_devices:
            await self.disconnect()

    @override
    async def request(
        self,
        mac_controller: str,
        json_str: str,
        max_attempts: int | None = None,
        timeout: float | None = None,
    ) -> str:
        """Hand the request to the fake device and return its reply."""
        envelope = json.loads(json_str)
        self.device.requests.append(envelope)

        reply = self.device.handle(envelope)
        if reply is None:
            raise GreeConnectionError(f"No answer from {self.device.mac}")

        return json.dumps(reply)

    def push(self, mac: str, topic: str, payload: dict[str, Any]) -> None:
        """Fire a message at the listeners, the way MQTT does."""
        for listener in list(self._listeners.get(mac, ())):
            listener(topic, payload)
