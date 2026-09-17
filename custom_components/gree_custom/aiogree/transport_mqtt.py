"""Handles MQTT connections."""

import asyncio
import contextlib
import json
import logging
import random
import ssl
from typing import override

import aiomqtt

from .cloud_api import GreeRegion
from .errors import GreeRuntimeError
from .transport import GreeBaseTransport

_LOGGER = logging.getLogger(__name__)


MQTT_SERVERS = {
    GreeRegion.AU: "mqtt-au.gree.com",
    GreeRegion.CN: "mqtt-cn.gree.com",
    GreeRegion.AS: "mqtt-as.gree.com",
    GreeRegion.EU: "mqtt-eu.gree.com",
    GreeRegion.IN: "mqtt-in.gree.com",
    GreeRegion.LA: "mqtt-la.gree.com",
    GreeRegion.ME: "mqtt-me.gree.com",
    GreeRegion.US: "mqtt-us.gree.com",
    GreeRegion.RU: "mqtt-ru.gree.com",
    GreeRegion.SA: "mqtt-sa.gree.com",
}


class GreeMqttTransport(GreeBaseTransport):
    """MQTT transport."""

    batch_support = True

    def __init__(
        self,
        user_id: str,
        token: str,
        region: GreeRegion,
        port: int = 1984,
        keepalive: int = 60,
        timeout: float = 10.0,
    ) -> None:
        """Initialize the MQTT transport object."""
        super().__init__()

        self._user_id = user_id
        self._token = token
        self._region = region
        self._port = port

        self._timeout = timeout
        self._keepalive = keepalive

        # Stable for the lifetime of this MQTT session.
        self._cid = str(random.randint(1_000_000_000, 9_999_999_999))

        self._client: aiomqtt.Client | None = None
        self._connected = False

        self._receive_task: asyncio.Task | None = None

        self._request_lock = asyncio.Lock()
        self._pending: asyncio.Future[str] | None = None

    @override
    def __str__(self) -> str:
        """Representation of the MQTT transport."""
        return f"MQTT({self._user_id}, {self._region.name})"

    @override
    async def connect(self) -> None:
        if self._connected:
            return

        # Create TLS context for secure connection
        tls_context = ssl.create_default_context()
        # Allow self-signed certificates (Gree broker uses custom cert)
        tls_context.check_hostname = False
        tls_context.verify_mode = ssl.CERT_NONE

        self._client = aiomqtt.Client(
            hostname=MQTT_SERVERS[self._region],
            port=self._port,
            username=self._user_id,
            password=self._token,
            identifier=f"app_{self._cid}",
            protocol=aiomqtt.ProtocolVersion.V311,
            keepalive=self._keepalive,
            tls_context=tls_context,
            timeout=self._timeout,
        )

        await self._client.__aenter__()  # pylint: disable=unnecessary-dunder-call
        self._connected = True

        # Create receiving task
        self._receive_task = asyncio.create_task(self._receive_loop())
        self._receive_task.add_done_callback(self._receive_task_done)

        _LOGGER.debug("Connected to MQTT broker %s:%d", self._region.value, self._port)

    @override
    async def disconnect(self) -> None:
        if not self._connected or not self._client:
            return

        # Close MQTT client
        try:
            await self._client.__aexit__(None, None, None)  # pylint: disable=unnecessary-dunder-call
        except Exception:
            _LOGGER.exception("Error closing MQTT client")
        finally:
            self._client = None

        # Clear receive task
        if self._receive_task:
            self._receive_task.cancel()

            with contextlib.suppress(asyncio.CancelledError):
                await self._receive_task

            self._receive_task.remove_done_callback(self._receive_task_done)
            self._receive_task = None

        self._pending = None

        self._connected = False
        _LOGGER.debug("Disconnected from MQTT broker")

    @override
    async def subscribe(self, mac_controller: str) -> None:
        await self.connect()

        if not self._connected or not self._client:
            raise GreeRuntimeError("MQTT transport not connected")

        if mac_controller not in self.connected_devices:
            topics = [
                f"response/{mac_controller}/#",
                f"status/{mac_controller}/#",
                f"connect/{mac_controller}",
            ]

            for topic in topics:
                await self._client.subscribe(topic, qos=1)
                _LOGGER.debug("Subscribed to topic: %s", topic)

        self.connected_devices[mac_controller] += 1

    @override
    async def unsubscribe(self, mac_controller: str) -> None:
        if not self._connected or not self._client:
            raise GreeRuntimeError("MQTT transport not connected")

        if self.connected_devices[mac_controller] > 1:
            self.connected_devices[mac_controller] -= 1
        else:
            self.connected_devices.pop(mac_controller, None)
            topics = [
                f"response/{mac_controller}/#",
                f"status/{mac_controller}/#",
                f"connect/{mac_controller}",
            ]

            for topic in topics:
                await self._client.unsubscribe(topic)
                _LOGGER.debug("Unsubscribed from topic: %s", topic)

        if len(self.connected_devices) == 0:
            return await self.disconnect()

        return None

    @override
    async def request(self, mac_controller: str, json_str: str) -> str:
        """Publish one MQTT request and wait for its response."""

        if not self._connected or not self._client:
            raise GreeRuntimeError("Transport not connected")

        async with self._request_lock:
            future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
            self._pending = future

            try:
                # Responses match 1:1 requests
                await self._client.publish(
                    topic=f"request/{mac_controller}",
                    payload=json_str,
                    qos=1,
                )

                return await asyncio.wait_for(
                    future,
                    timeout=self._timeout,
                )

            finally:
                self._pending = None

    def _receive_task_done(self, task: asyncio.Task[None]) -> None:
        """Handle receive task completion."""
        if task.cancelled():
            _LOGGER.debug("MQTT receive loop cancelled")
            return

        exception = task.exception()
        if exception:
            _LOGGER.debug(
                "MQTT receive loop stopped with exception",
                exc_info=exception,
            )
        else:
            _LOGGER.debug("MQTT receive loop stopped normally")

    async def _receive_loop(self) -> None:
        """Receive MQTT messages."""

        if not self._connected or not self._client:
            raise GreeRuntimeError("Transport not connected.")

        async for message in self._client.messages:
            topic = str(message.topic)
            payload = message.payload.decode()

            _LOGGER.debug("Received MQTT Message with topic: %s", topic)

            #
            # response/ completes pending request
            #
            if (
                topic.startswith("response/")
                and self._pending
                and not self._pending.done()
            ):
                self._pending.set_result(payload)
                continue

            #
            # status/ and connect/
            #
            for target_mac, listeners in self._listeners.items():
                if target_mac not in topic:
                    continue

                for listener in listeners:
                    try:
                        listener(topic, json.loads(payload))
                    except Exception:
                        _LOGGER.exception("MQTT listener raised")

    @property
    def cid(self) -> str:
        """MQTT client identifier used in request envelopes."""
        return self._cid
