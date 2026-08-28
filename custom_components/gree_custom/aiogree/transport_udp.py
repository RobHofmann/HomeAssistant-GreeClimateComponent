"""Handles UDP connections."""

import asyncio
import json
import logging
from typing import Any, cast, override

import asyncio_dgram

from .cipher import CipherBase, EncryptionVersion, get_cipher
from .errors import GreeConnectionError, GreeError
from .helpers import gree_decrypt_pack, gree_encrypt_pack
from .transport import GreeBaseTransport

_LOGGER = logging.getLogger(__name__)


class GreeUdpTransport(GreeBaseTransport):
    """Gree UDP protocol implementation."""

    batch_support = True

    def __init__(
        self, ip_addr: str, port: int = 7000, max_retries: int = 3, timeout: float = 2.0
    ) -> None:
        """Initialize the transport object."""
        super().__init__()
        self.ip_addr = ip_addr
        self.port = port
        self.max_retries = max_retries
        self.timeout = timeout

        self._stream: asyncio_dgram.DatagramClient | None = None
        self._request_lock: asyncio.Lock = asyncio.Lock()
        self._stream_lock: asyncio.Lock = asyncio.Lock()

    @override
    def __str__(self) -> str:
        """Representation of the class."""
        return f"Local({self.ip_addr})"

    async def _get_stream(self) -> asyncio_dgram.DatagramClient:
        """Create stream once and reuse it while possible."""
        async with self._stream_lock:
            if self._stream is None:
                _LOGGER.debug("Creating stream for %s", self.ip_addr)
                self._stream = await asyncio_dgram.connect((self.ip_addr, self.port))
                _LOGGER.debug("Stream created")

        return self._stream

    def _reset_stream(self) -> None:
        """Safely reset UDP stream if it gets into a bad state."""
        _LOGGER.debug("Resetting stream for %s", self.ip_addr)

        if self._stream is not None:
            try:
                self._stream.close()
            except Exception:
                _LOGGER.exception("Could not close stream")
            self._stream = None

    async def set_ip(self, ip_addr: str) -> None:
        """Set the IP used in the transport."""
        async with self._stream_lock:
            self.ip_addr = ip_addr
            self._reset_stream()

    @override
    async def connect(self) -> None:
        if self._stream is None:
            await self._get_stream()

            try:
                # when connecting, perform a targeted scan so the device can respond to the consecutive bind request
                await self.request_json(
                    "", {"t": "scan"}, get_cipher(EncryptionVersion.V1)
                )
            except GreeError:
                self._reset_stream()

    @override
    async def disconnect(self) -> None:
        self._reset_stream()

    @override
    async def subscribe(self, mac_controller: str) -> None:
        await self.connect()
        self.connected_devices[mac_controller] += 1

    @override
    async def unsubscribe(self, mac_controller: str) -> None:
        if self.connected_devices[mac_controller] > 1:
            self.connected_devices[mac_controller] -= 1
        else:
            self.connected_devices.pop(mac_controller, None)

        if len(self.connected_devices) == 0:
            return await self.disconnect()
        return None

    @override
    async def request(
        self,
        mac_controller: str,
        json_str: str,
    ) -> str:

        last_error: Exception | None = None

        async with self._request_lock:  # prevents concurrent recv/send corruption
            for attempt in range(self.max_retries):
                try:
                    stream: asyncio_dgram.DatagramClient = await self._get_stream()

                    await stream.send(json_str.encode())

                    received_data, _ = await asyncio.wait_for(
                        stream.recv(), timeout=self.timeout
                    )

                except Exception as err:  # noqa: BLE001
                    last_error = err
                    _LOGGER.warning(
                        "Error communicating with %s. Attempt %d/%d",
                        self.ip_addr,
                        attempt + 1,
                        self.max_retries,
                    )
                    self._reset_stream()

                else:
                    return received_data.decode()

                # Apply backoff before retrying
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(0.5 + attempt * 0.3)  # 0.5s, 0.8s, 1.1s, ...

        raise GreeConnectionError(
            f"Failed to communicate with device '{self.ip_addr}:{self.port}' after {self.max_retries} attempts"
        ) from last_error


class UDPDiscoveryProtocol(asyncio.DatagramProtocol):
    """Helper Protocol to handle incoming UDP discovery responses.

    Responses will be added to a 'responses' field which can be queried.
    """

    def __init__(self, responses: dict[str, dict], cipher: CipherBase) -> None:
        """Initialize Discovery Transport. Use the responses to query the received data."""
        self._cipher = cipher
        self.responses = responses
        self.transport: asyncio.DatagramTransport | None = None

    @override
    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        """After UDP socket is set up."""
        self.transport = cast(asyncio.DatagramTransport, transport)

    @override
    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        """After a UDP packet is received."""
        try:
            # Decode the payload
            json_payload = json.loads(data.decode("utf-8", errors="ignore"))
            json_payload = gree_decrypt_pack(json_payload, self._cipher)
            ip_address = addr[0]

            self.responses[ip_address] = json_payload
            _LOGGER.debug("Received reply from %s", ip_address)

        except json.JSONDecodeError:
            _LOGGER.exception("Could not parse JSON response from %s: %s", addr, data)
        except Exception:
            _LOGGER.exception("Unexpected error processing packet from %s", addr)

    @override
    def error_received(self, exc: Exception) -> None:
        """After underlying network errors."""
        _LOGGER.error("UDP network error received: %s", exc)

    @override
    def connection_lost(self, exc: Exception | None) -> None:
        """After the socket is closed."""

    def send(self, json_payload: dict[str, Any], addr: tuple[str, int]) -> None:
        """Send a JSON payload to a target address."""
        _LOGGER.debug("Sending broadcast to %s", addr)

        if not self.transport:
            raise RuntimeError("Transport not initialized")

        # encrypt pack if present
        json_payload = gree_encrypt_pack(json_payload, self._cipher)

        raw_request = json.dumps(json_payload).encode("utf-8")

        self.transport.sendto(raw_request, addr)


async def async_udp_broadcast_request(
    broadcast_addresses: list[str],
    port: int,
    json_data: dict[str, Any],
    timeout: int,
    cipher: CipherBase,
) -> dict[str, dict]:
    """Send a UDP broadcast and waits for responses."""
    loop = asyncio.get_running_loop()
    responses: dict[str, dict] = {}

    # Remove duplicates
    broadcast_addresses = list(dict.fromkeys(broadcast_addresses))

    if len(broadcast_addresses) == 0:
        _LOGGER.info("No broadcast addresses to scan")
        return {}

    try:
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: UDPDiscoveryProtocol(responses, cipher),
            local_addr=(
                "0.0.0.0",
                0,
            ),  # Listen on all interfaces, random ephemeral port
            allow_broadcast=True,
        )
    except OSError as err:
        _LOGGER.error("Failed to bind UDP socket: %s", err)
        return responses

    try:
        # Send out the broadcast payload
        for addr in broadcast_addresses:
            try:
                protocol.send(json_data, (addr, port))
            except Exception:
                _LOGGER.exception("Failed sending to %s", addr)

        # Wait for devices to reply asynchronously
        _LOGGER.debug("Waiting %d seconds for UDP replies... ", timeout)
        await asyncio.sleep(timeout)

    finally:
        transport.close()

    _LOGGER.debug("Discovery finished. Got %d responses", len(responses))
    return responses
