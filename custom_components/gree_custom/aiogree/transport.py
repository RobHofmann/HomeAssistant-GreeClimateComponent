"""Handles network connections."""

import asyncio
import json
import logging
import socket
import time

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
            await asyncio.sleep(0.5 + attempt * 0.3)  # 0.5s, 0.8s, 1.1s, ...

        raise GreeConnectionError(
            f"Failed to communicate with device '{self.ip_addr}:{self.port}' after {self.max_retries} attempts"
        ) from last_error

    async def request_json(self, payload: dict) -> dict:
        """Send and receive a JSON payload."""
        raw = await self.udp_request(json.dumps(payload).encode("utf-8"))
        return json.loads(raw.decode("utf-8"))


def udp_broadcast_request(
    addresses: list[str], port: int, json_data: str, timeout: int
) -> dict[str, dict]:
    """Sends a UDP message to the bradcast address and returns the responses."""
    # Create UDP socket manually so we can enable broadcast
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(timeout)
    sock.bind(("", 0))

    responses: dict[str, dict] = {}

    # Default broadcast addresses to try
    default_broadcast_addresses = [
        "255.255.255.255",  # Limited broadcast
        "192.168.255.255",  # /16 broadcast for 192.168.x.x networks
        "10.255.255.255",  # /8 broadcast for 10.x.x.x networks
        "172.31.255.255",  # /12 broadcast for 172.16-31.x.x networks
    ]
    addresses.extend(default_broadcast_addresses)

    # Remove duplicates
    broadcast_addresses = list(dict.fromkeys(addresses))

    try:
        for broadcast_addr in broadcast_addresses:
            try:
                _LOGGER.debug("Sending broadcast to %s", broadcast_addr)
                sock.sendto(json_data.encode("utf-8"), (broadcast_addr, port))
            except Exception:
                _LOGGER.exception("Failed to send to %s", broadcast_addr)

        # Send broadcast
        _LOGGER.debug(
            "Sent broadcast packets, waiting %d seconds for replies... ", timeout
        )

        start_time: float = time.time()
        while time.time() - start_time < timeout:
            try:
                response, addr = sock.recvfrom(1024)

                try:
                    response = json.loads(response.decode(errors="ignore"))
                except Exception:
                    _LOGGER.exception("Could not parse response from %s", addr)
                else:
                    responses[addr[0]] = response
            except TimeoutError:
                break
    except Exception:
        _LOGGER.exception("Error sending broadcast packet")
    finally:
        sock.close()

    _LOGGER.debug(
        "Got %d responses in %d seconds: %s", len(responses), timeout, responses
    )
    return responses
