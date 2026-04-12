"""Handles network connections."""

import asyncio
import json
import logging

import asyncio_dgram

from .errors import GreeConnectionError

_LOGGER = logging.getLogger(__name__)


class GreeTransport:
    """Handles the connection with the Gree device."""

    def __init__(
        self, ip_addr: str, port: int, max_retries: int = 3, timeout: float = 2.0
    ) -> None:
        """Initialize the connection object."""
        self.ip_addr = ip_addr
        self.port = port
        self.max_retries = max_retries
        self.timeout = timeout

    async def udp_request(
        self,
        data: bytes,
    ) -> bytes:
        """Send a payload data to the device and reads the response."""

        last_error: Exception = None

        for attempt in range(self.max_retries):
            stream: asyncio_dgram.DatagramClient | None = None

            try:
                stream = await asyncio_dgram.connect((self.ip_addr, self.port))

                await stream.send(data)

                recv_task = asyncio.create_task(stream.recv())

                try:
                    received_data, _ = await asyncio.wait_for(recv_task, self.timeout)
                except TimeoutError:
                    recv_task.cancel()
                    raise
                else:
                    return received_data

            except Exception as err1:  # noqa: BLE001
                _LOGGER.warning(
                    "Error communicating with %s. Attempt %d/%d",
                    self.ip_addr,
                    attempt + 1,
                    self.max_retries,
                )
                last_error = err1

            finally:
                if stream:
                    try:
                        stream.close()
                    except Exception as err2:  # noqa: BLE001
                        _LOGGER.warning(
                            "Error communicating with %s. Attempt %d/%d",
                            self.ip_addr,
                            attempt + 1,
                            self.max_retries,
                        )
                        last_error = err2

            # Apply backoff before retrying
            if attempt < self.max_retries - 1:
                await asyncio.sleep(0.5 + attempt * 0.3)  # 0.5s, 0.8s, 1.1s, ...

        raise GreeConnectionError(
            f"Failed to communicate with device '{self.ip_addr}:{self.port}' after {self.max_retries} attempts"
        ) from last_error

    async def request_json(self, payload: dict) -> dict:
        """Send and receive a JSON payload."""
        raw = await self.udp_request(json.dumps(payload).encode("utf-8"))
        return json.loads(raw.decode("utf-8"))


class UDPDiscoveryProtocol(asyncio.DatagramProtocol):
    """Helper Protocol to handle incoming UDP discovery responses.

    Responses will be added to a 'responses' field which can be queried.
    """

    def __init__(self, responses: dict[str, dict]) -> None:
        """Setup Discovery Transport. Use the responses to query the received data."""
        self.responses = responses
        self.transport = None

    def connection_made(self, transport: asyncio.DatagramTransport):
        """Called when the UDP socket is set up."""
        self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str, int]):
        """Called when a UDP packet is received."""
        try:
            # Decode the payload
            payload = json.loads(data.decode("utf-8", errors="ignore"))
            ip_address = addr[0]

            self.responses[ip_address] = payload
            _LOGGER.debug("Received reply from %s", ip_address)

        except json.JSONDecodeError:
            _LOGGER.exception("Could not parse JSON response from %s: %s", addr, data)
        except Exception:
            _LOGGER.exception("Unexpected error processing packet from %s", addr)

    def error_received(self, exc):
        """Called on underlying network errors."""
        _LOGGER.error("UDP network error received: %s", exc)

    def connection_lost(self, exc):
        """Called when the socket is closed."""


async def async_udp_broadcast_request(
    broadcast_addresses: list[str], port: int, json_data: str, timeout: int
) -> dict[str, dict]:
    """Sends an async UDP broadcast and waits for responses."""
    loop = asyncio.get_running_loop()
    responses: dict[str, dict] = {}

    # Remove duplicates
    broadcast_addresses = list(dict.fromkeys(broadcast_addresses))

    try:
        transport, _ = await loop.create_datagram_endpoint(
            lambda: UDPDiscoveryProtocol(responses),
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
        payload = json_data.encode("utf-8")
        for addr in broadcast_addresses:
            try:
                _LOGGER.debug("Sending broadcast to %s:%s", addr, port)
                transport.sendto(payload, (addr, port))
            except Exception:
                _LOGGER.exception("Failed sending to %s", addr)

        # Wait for devices to reply asynchronously
        _LOGGER.debug("Waiting %d seconds for UDP replies... ", timeout)
        await asyncio.sleep(timeout)

    finally:
        transport.close()

    _LOGGER.debug("Discovery finished. Got %d responses", len(responses))
    return responses
