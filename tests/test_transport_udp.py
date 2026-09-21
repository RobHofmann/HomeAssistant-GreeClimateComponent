"""Tests for the UDP transport.

These run against a real socket on an ephemeral port, so retries, timeouts and
the stream reset all happen for real. Keep `max_retries` at 1 in any test that
is not about retrying, because a full failure costs a few seconds.
"""

# pylint: disable=redefined-outer-name
# A test takes a fixture as an argument with the same name. That is the
# pytest pattern, not shadowing.

from collections.abc import AsyncIterator

from aiogree.api import gree_get_response_pack, gree_get_status, gree_set_status
from aiogree.cipher import EncryptionVersion, get_cipher
from aiogree.errors import GreeConnectionError, GreeProtocolError
from aiogree.transport_udp import GreeUdpTransport
import pytest

from .fakes.device import DEFAULT_MAC, DEFAULT_SESSION_KEY, FakeGreeDevice


@pytest.fixture
async def device() -> AsyncIterator[FakeGreeDevice]:
    """Start a plain device on a free port."""
    fake = FakeGreeDevice()
    await fake.start()
    try:
        yield fake
    finally:
        fake.close()


async def get_power(
    transport: GreeUdpTransport,
    version: EncryptionVersion = EncryptionVersion.V1,
) -> dict[str, str]:
    """Ask the device for one column."""
    result = await gree_get_status(
        DEFAULT_MAC,
        DEFAULT_MAC,
        0,
        ["Pow"],
        get_cipher(version, DEFAULT_SESSION_KEY),
        transport,
    )
    return result.prop_values


async def test_one_request_when_the_device_answers(device: FakeGreeDevice) -> None:
    """A device that answers costs exactly one packet."""
    transport = GreeUdpTransport(device.host, device.port, max_retries=1, timeout=0.5)

    values = await get_power(transport)

    assert values == {"Pow": "1"}
    assert len(device.requests) == 1
    await transport.disconnect()


async def test_a_v2_device_answers_over_the_same_transport() -> None:
    """V2 (AES-GCM) carries a tag in the packet. The transport does not care."""
    device = FakeGreeDevice(encryption_version=EncryptionVersion.V2)
    await device.start()
    transport = GreeUdpTransport(device.host, device.port, max_retries=1, timeout=0.5)

    try:
        values = await get_power(transport, EncryptionVersion.V2)
    finally:
        await transport.disconnect()
        device.close()

    assert values == {"Pow": "1"}
    assert "tag" in device.requests[0]


async def test_three_requests_when_the_device_answers_on_the_third_try() -> None:
    """The transport keeps trying, and the late answer is still used."""
    device = FakeGreeDevice(ignore_first=2)
    await device.start()
    transport = GreeUdpTransport(device.host, device.port, max_retries=3, timeout=0.2)

    try:
        values = await get_power(transport)
    finally:
        await transport.disconnect()
        device.close()

    assert values == {"Pow": "1"}
    assert len(device.requests) == 3


async def test_connection_error_when_the_device_never_answers() -> None:
    """After the last attempt the transport gives up with a connection error."""
    device = FakeGreeDevice(drop_after=0)
    await device.start()
    transport = GreeUdpTransport(device.host, device.port, max_retries=2, timeout=0.2)

    try:
        with pytest.raises(GreeConnectionError):
            await get_power(transport)
    finally:
        await transport.disconnect()
        device.close()

    assert len(device.requests) == 2


async def test_backoff_grows_between_retries() -> None:
    """The wait is 0.5s after the first try and 0.8s after the second."""
    device = FakeGreeDevice(drop_after=0)
    await device.start()
    timeout = 0.1
    transport = GreeUdpTransport(
        device.host, device.port, max_retries=3, timeout=timeout
    )

    try:
        with pytest.raises(GreeConnectionError):
            await get_power(transport)
    finally:
        await transport.disconnect()
        device.close()

    assert len(device.request_times) == 3
    first_gap = device.request_times[1] - device.request_times[0] - timeout
    second_gap = device.request_times[2] - device.request_times[1] - timeout

    assert 0.5 <= first_gap < 0.75
    assert 0.8 <= second_gap < 1.1


async def test_protocol_error_when_the_reply_cannot_be_decrypted() -> None:
    """A device with a rotated key answers with a pack we cannot read."""
    device = FakeGreeDevice(reply_key="N0tTh3S3ss10nK3y")
    await device.start()
    transport = GreeUdpTransport(device.host, device.port, max_retries=1, timeout=0.5)

    try:
        with pytest.raises(GreeProtocolError):
            await get_power(transport)
    finally:
        await transport.disconnect()
        device.close()

    assert len(device.requests) == 1


async def test_a_command_is_split_when_the_transport_cannot_batch(
    device: FakeGreeDevice, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without batching every option goes out on its own and the replies merge."""
    monkeypatch.setattr(GreeUdpTransport, "batch_support", False)
    transport = GreeUdpTransport(device.host, device.port, max_retries=1, timeout=0.5)
    wanted = {"Lig": 1, "Quiet": 1, "Pow": 0}

    try:
        result = await gree_set_status(
            DEFAULT_MAC,
            DEFAULT_MAC,
            0,
            wanted,
            get_cipher(EncryptionVersion.V1, DEFAULT_SESSION_KEY),
            transport,
        )
    finally:
        await transport.disconnect()

    assert len(device.packs) == 3
    assert [pack["opt"] for pack in device.packs] == [["Lig"], ["Quiet"], ["Pow"]]
    assert result == wanted


async def test_a_command_goes_out_once_when_the_transport_can_batch(
    device: FakeGreeDevice,
) -> None:
    """UDP does support batching, so the same command is one packet."""
    transport = GreeUdpTransport(device.host, device.port, max_retries=1, timeout=0.5)

    try:
        await gree_set_status(
            DEFAULT_MAC,
            DEFAULT_MAC,
            0,
            {"Lig": 1, "Quiet": 1, "Pow": 0},
            get_cipher(EncryptionVersion.V1, DEFAULT_SESSION_KEY),
            transport,
        )
    finally:
        await transport.disconnect()

    assert len(device.packs) == 1
    assert device.packs[0]["opt"] == ["Lig", "Quiet", "Pow"]


async def test_a_bind_gets_the_session_key(device: FakeGreeDevice) -> None:
    """The generic key opens the bind and the device hands out its own key."""
    transport = GreeUdpTransport(device.host, device.port, max_retries=1, timeout=0.5)

    try:
        pack = await gree_get_response_pack(
            DEFAULT_MAC,
            {
                "cid": "app",
                "i": 1,
                "t": "pack",
                "pack": {"t": "bind", "uid": 0, "mac": DEFAULT_MAC},
                "tcid": DEFAULT_MAC,
                "uid": 0,
            },
            get_cipher(EncryptionVersion.V1),
            transport,
        )
    finally:
        await transport.disconnect()

    assert pack["key"] == DEFAULT_SESSION_KEY
    assert device.keys_used == ["generic"]
