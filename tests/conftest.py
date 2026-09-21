"""Shared fixtures for the protocol tests."""

import asyncio
from collections.abc import Awaitable, Callable, Iterator
import inspect
import logging
import random
import socket
from typing import Any, override

from aiogree.api import (
    GreeDiscoveredDevice,
    gree_discover_device_local,
    gree_discover_devices_local,
)
from aiogree.const import DEFAULT_DEVICE_PORT
import pytest

# Everything the protocol layer logs sits under this logger, because the tests
# import the package as "aiogree". Inside Home Assistant the same records are
# named "custom_components.gree_custom.aiogree.*".
LOGGER_ROOT = "aiogree"

# Discovery has no port argument, so it always uses the protocol default.
DISCOVERY_PORT = DEFAULT_DEVICE_PORT

DiscoverOne = Callable[..., Awaitable[list[GreeDiscoveredDevice]]]
DiscoverAll = Callable[..., Awaitable[list[GreeDiscoveredDevice]]]


class RecordingHandler(logging.Handler):
    """Captures records and any failure to format them.

    Standard logging swallows a formatting error and prints it to stderr, so a
    test that only reads the text of a log line never sees it. Calling
    `record.getMessage()` here turns that into something a test can assert on.
    Two real defects in PR 514 were log only: a warning that fired when nothing
    was wrong, and a warning that could not be formatted because `%d` got
    `None`.
    """

    def __init__(self) -> None:
        """Start with nothing recorded."""
        super().__init__()
        self.records: list[logging.LogRecord] = []
        self.format_errors: list[str] = []

    @override
    def emit(self, record: logging.LogRecord) -> None:
        """Record one line and note it if it cannot be formatted."""
        self.records.append(record)
        try:
            record.getMessage()
        except Exception as err:  # noqa: BLE001
            self.format_errors.append(f"{record.msg!r}: {err!r}")

    def messages(self, level: int = logging.NOTSET) -> list[str]:
        """Return the formatted messages at or above a level."""
        out: list[str] = []
        for record in self.records:
            if record.levelno < level:
                continue
            try:
                out.append(record.getMessage())
            except Exception:  # noqa: BLE001
                out.append(f"<unformattable {record.msg!r}>")
        return out

    def warnings(self) -> list[str]:
        """Return the messages logged at warning level or above."""
        return self.messages(logging.WARNING)


@pytest.fixture(autouse=True)
def gree_logs() -> Iterator[RecordingHandler]:
    """Capture the component's log records for the length of one test.

    The handler is autouse so no test can forget the format check. Propagation
    is switched off so pytest's own capture does not touch these records.
    """
    handler = RecordingHandler()
    logger = logging.getLogger(LOGGER_ROOT)

    old_level = logger.level
    old_propagate = logger.propagate
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.addHandler(handler)

    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)
        logger.propagate = old_propagate

    assert not handler.format_errors, (
        f"log lines that could not be formatted: {handler.format_errors}"
    )


def _takes_max_retries(func: Callable[..., Any]) -> bool:
    """Check whether a discovery function takes the PR 514 max_retries argument.

    PR 514 adds `max_retries` to the discovery functions, before `user_id` and
    without a default. Asking the signature keeps the tests working on both
    sides of that merge, so the change stays in this one place.
    """
    return "max_retries" in inspect.signature(func).parameters


# The argument list of these two differs per branch, so the tests call them
# through a loose type. The check above decides which call to make.
_discover_device_local: DiscoverOne = gree_discover_device_local
_discover_devices_local: DiscoverAll = gree_discover_devices_local


@pytest.fixture
def discover_one() -> DiscoverOne:
    """Scan one host, through whichever signature this branch has."""

    async def _discover(
        host: str, timeout: int = 1, max_retries: int = 1, user_id: int = 0
    ) -> list[GreeDiscoveredDevice]:
        if _takes_max_retries(gree_discover_device_local):
            return await _discover_device_local(host, timeout, max_retries, user_id)
        return await _discover_device_local(host, timeout, user_id)

    return _discover


@pytest.fixture
def discover_all() -> DiscoverAll:
    """Scan a list of addresses, through whichever signature this branch has."""

    async def _discover(
        addresses: list[str],
        timeout: int = 1,
        max_retries: int = 1,
        user_id: int = 0,
    ) -> list[GreeDiscoveredDevice]:
        if _takes_max_retries(gree_discover_devices_local):
            return await _discover_devices_local(
                addresses, timeout, max_retries, user_id
            )
        return await _discover_devices_local(addresses, timeout, user_id)

    return _discover


def _can_bind(host: str, port: int) -> bool:
    """Check whether a UDP socket can take this address."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((host, port))
    except OSError:
        return False
    else:
        return True
    finally:
        sock.close()


def _free_loopback_ips(count: int, port: int) -> list[str]:
    """Find loopback addresses that are free on a port.

    Discovery always talks to port 7000, because neither the scan nor the
    broadcast takes a port. Separate addresses out of 127.0.0.0/8 are what
    keeps the tests able to run next to each other. The whole range works on
    Linux; on Windows and macOS only 127.0.0.1 is there by default.
    """
    found: list[str] = []
    for _ in range(200):
        host = f"127.{random.randint(1, 254)}.{random.randint(0, 254)}.{random.randint(2, 254)}"
        if host in found or not _can_bind(host, port):
            continue
        found.append(host)
        if len(found) == count:
            return found

    if count == 1 and _can_bind("127.0.0.1", port):
        return ["127.0.0.1"]

    pytest.skip(
        f"needs {count} free loopback addresses on port {port}; "
        "the whole 127.0.0.0/8 range is only available on Linux"
    )


@pytest.fixture
def loopback_ip() -> str:
    """One loopback address that is free on the discovery port."""
    return _free_loopback_ips(1, DISCOVERY_PORT)[0]


@pytest.fixture
def loopback_ips() -> Callable[[int], list[str]]:
    """Several loopback addresses that are free on the discovery port."""

    def _reserve(count: int) -> list[str]:
        return _free_loopback_ips(count, DISCOVERY_PORT)

    return _reserve


@pytest.fixture
def settle() -> Callable[[], Awaitable[None]]:
    """Give the event loop a turn, so a queued datagram gets delivered."""

    async def _settle() -> None:
        await asyncio.sleep(0.05)

    return _settle
