"""Tests for the Gree Cloud client.

These run against a fake cloud on a real HTTP socket, so the client does its own
encryption, its own request and its own parsing. Only the host is different.
"""

# pylint: disable=redefined-outer-name
# A test takes a fixture as an argument with the same name. That is the
# pytest pattern, not shadowing.

from collections.abc import AsyncIterator, Callable

from aiogree import cloud_api
from aiogree.cloud_api import (
    CLOUD_SERVERS,
    CloudDeviceInfoResponse,
    GreeCloudApi,
    GreeRegion,
    gree_get_latest_firmware_info,
)
from aiogree.errors import GreeCloudError, GreeCloudLoginError
import pytest

from .fakes.cloud import TOKEN, USER_ID, FakeGreeCloud, cloud_device

REGION = GreeRegion.EU
GATEWAY_MAC = "9424b8fd5ba3"
SUB_MAC = "9424b8fd5ba300"
DEVICE_KEY = "V1sT9p0aQ3zXcR7m"

CloudFactory = Callable[..., AsyncIterator[GreeCloudApi]]


@pytest.fixture
async def cloud_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[Callable[..., AsyncIterator[tuple[FakeGreeCloud, GreeCloudApi]]]]:
    """Start a fake cloud and point a client at it."""
    started: list[FakeGreeCloud] = []
    clients: list[GreeCloudApi] = []

    async def _build(**kwargs: object) -> tuple[FakeGreeCloud, GreeCloudApi]:
        server = FakeGreeCloud(**kwargs)  # type: ignore[arg-type]
        await server.start()
        started.append(server)

        monkeypatch.setitem(CLOUD_SERVERS, REGION, server.url)
        client = GreeCloudApi.for_server(REGION, "rob@example.com", "hunter2")
        clients.append(client)
        return server, client

    try:
        yield _build  # type: ignore[misc]
    finally:
        for client in clients:
            await client.close()
        for server in started:
            await server.close()


async def test_login_returns_the_credentials(cloud_factory: CloudFactory) -> None:
    """A good login stores the user id and token on the client."""
    server, client = await cloud_factory()  # type: ignore[misc]

    credentials = await client.login()

    assert credentials.user_id == USER_ID
    assert credentials.token == TOKEN
    assert client.user_id == USER_ID
    assert client.token == TOKEN
    assert server.requests[0][0] == "/App/UserLoginV2"


async def test_the_login_body_carries_the_app_signature(
    cloud_factory: CloudFactory,
) -> None:
    """Every call is signed. The cloud refuses anything without it."""
    server, client = await cloud_factory()  # type: ignore[misc]

    await client.login()

    _, payload = server.requests[0]
    assert payload["api"]["appId"] == GreeCloudApi.APP_ID
    assert payload["user"] == "rob@example.com"
    assert len(payload["psw"]) == 32
    assert "hunter2" not in str(payload)


async def test_a_login_in_the_nested_format(cloud_factory: CloudFactory) -> None:
    """Some servers wrap the answer in a data object."""
    _, client = await cloud_factory(  # type: ignore[misc]
        login_response={"data": {"uid": 7, "token": "nested-token"}}
    )

    credentials = await client.login()

    assert credentials.user_id == 7
    assert credentials.token == "nested-token"


async def test_a_refused_login_raises(cloud_factory: CloudFactory) -> None:
    """Wrong credentials give an error code, not an empty answer."""
    _, client = await cloud_factory(  # type: ignore[misc]
        login_response={"r": 401, "msg": "wrong password"}
    )

    with pytest.raises(GreeCloudLoginError, match="wrong password"):
        await client.login()


async def test_a_login_without_a_token_raises(cloud_factory: CloudFactory) -> None:
    """A token is what every later call needs."""
    _, client = await cloud_factory(login_response={"uid": 7, "token": ""})  # type: ignore[misc]

    with pytest.raises(GreeCloudLoginError, match="Missing uid or token"):
        await client.login()


async def test_an_unknown_login_format_raises(cloud_factory: CloudFactory) -> None:
    """Better an error than a client that thinks it is logged in."""
    _, client = await cloud_factory(login_response={"something": "else"})  # type: ignore[misc]

    with pytest.raises(GreeCloudError, match="Unexpected login response format"):
        await client.login()


async def test_a_server_error_raises(cloud_factory: CloudFactory) -> None:
    """An HTTP error is not a login failure, so it says so."""
    _, client = await cloud_factory(http_status=503)  # type: ignore[misc]

    with pytest.raises(GreeCloudError, match="HTTP 503"):
        await client.login()


async def test_calls_before_a_login_are_refused(cloud_factory: CloudFactory) -> None:
    """Without a token there is nothing to send."""
    _, client = await cloud_factory()  # type: ignore[misc]

    with pytest.raises(GreeCloudError, match="Not logged in"):
        await client.get_homes()


async def test_homes_are_listed_with_their_names_trimmed(
    cloud_factory: CloudFactory,
) -> None:
    """The cloud pads its names with spaces."""
    _, client = await cloud_factory(homes=[{"id": 3, "name": "  Thuis  "}])  # type: ignore[misc]
    await client.login()

    homes = await client.get_homes()

    assert len(homes) == 1
    assert homes[0].id == 3
    assert homes[0].name == "Thuis"


async def test_devices_are_read_from_every_room(cloud_factory: CloudFactory) -> None:
    """Devices sit inside rooms inside a home."""
    _, client = await cloud_factory(  # type: ignore[misc]
        homes=[{"id": 1, "name": "Thuis"}],
        devices_per_home={1: [cloud_device(SUB_MAC, DEVICE_KEY)]},
    )
    await client.login()

    devices = await client.get_devices(1)

    assert len(devices) == 1
    assert devices[0].mac == SUB_MAC
    assert devices[0].key == DEVICE_KEY


async def test_all_devices_covers_every_home(cloud_factory: CloudFactory) -> None:
    """An account can have more than one home."""
    _, client = await cloud_factory(  # type: ignore[misc]
        homes=[{"id": 1, "name": "Thuis"}, {"id": 2, "name": "Kantoor"}],
        devices_per_home={
            1: [cloud_device(SUB_MAC, DEVICE_KEY)],
            2: [cloud_device("c03937b12280", "0ther3ncrypt10nKy")],
        },
    )
    await client.login()

    devices = await client.get_all_devices()

    assert sorted(device.mac for device in devices) == [
        "9424b8fd5ba300",
        "c03937b12280",
    ]


async def test_a_duplicate_device_keeps_the_one_that_answers(
    cloud_factory: CloudFactory,
) -> None:
    """The cloud lists a VRF unit twice. Only the MAC ending in 00 answers."""
    _, client = await cloud_factory(  # type: ignore[misc]
        homes=[{"id": 1, "name": "Thuis"}],
        devices_per_home={
            1: [
                cloud_device(GATEWAY_MAC, DEVICE_KEY),
                cloud_device(SUB_MAC, DEVICE_KEY),
            ]
        },
    )
    await client.login()

    devices = await client.get_all_devices()

    assert [device.mac for device in devices] == [SUB_MAC]


async def test_two_devices_with_different_keys_are_both_kept(
    cloud_factory: CloudFactory,
) -> None:
    """Only a shared key marks the same unit listed twice."""
    _, client = await cloud_factory(  # type: ignore[misc]
        homes=[{"id": 1, "name": "Thuis"}],
        devices_per_home={
            1: [
                cloud_device(GATEWAY_MAC, DEVICE_KEY),
                cloud_device("c03937b12280", "0ther3ncrypt10nKy"),
            ]
        },
    )
    await client.login()

    devices = await client.get_all_devices()

    assert len(devices) == 2


async def test_the_client_closes_its_session(cloud_factory: CloudFactory) -> None:
    """It is also a context manager, so it cleans up on the way out."""
    _, client = await cloud_factory()  # type: ignore[misc]

    async with client as opened:
        await opened.login()

    assert client.user_id == USER_ID


def test_every_region_has_a_server() -> None:
    """A region without a host would fail at setup with a KeyError."""
    assert set(CLOUD_SERVERS) == set(GreeRegion)


async def test_firmware_info_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """The firmware check asks a plain JSON endpoint, not the encrypted one."""
    server = FakeGreeCloud(
        firmware_response={"r": 200, "ver": "3.80", "url": "https://example/fw.bin"}
    )
    await server.start()
    monkeypatch.setitem(CLOUD_SERVERS, REGION, server.url)

    try:
        info = await gree_get_latest_firmware_info(REGION, "362001065279")
    finally:
        await server.close()

    assert info is not None
    assert info.version == "3.80"
    assert info.url == "https://example/fw.bin"
    assert server.requests[0][1]["firmwareCode"] == "362001065279"


async def test_firmware_info_without_a_result_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A code the server does not know gives no information, not an error."""
    server = FakeGreeCloud(firmware_response={"r": 404})
    await server.start()
    monkeypatch.setitem(CLOUD_SERVERS, REGION, server.url)

    try:
        assert await gree_get_latest_firmware_info(REGION, "000") is None
    finally:
        await server.close()


def test_the_device_model_ignores_fields_it_does_not_know() -> None:
    """The cloud adds fields over time. A new one must not break discovery."""
    payload = cloud_device(SUB_MAC, DEVICE_KEY)
    payload["brandNewFieldFromTheApp"] = "surprise"

    device = CloudDeviceInfoResponse.model_validate(payload)

    assert device.mac == SUB_MAC


def test_the_module_keeps_its_app_identity() -> None:
    """These values come from the Gree app. The cloud refuses anything else."""
    assert cloud_api.GreeCloudApi.APP_ID == "4920681951525131286"
    assert len(cloud_api.GreeCloudApi.AES_KEY) == 16
