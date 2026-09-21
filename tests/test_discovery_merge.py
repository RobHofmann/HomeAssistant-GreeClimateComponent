"""Tests for cloud discovery and for merging it with local discovery.

A device can show up twice, once from a broadcast on the network and once from
the Gree Cloud. The two lists carry different fields: local knows the IP, cloud
knows the key and the name the user gave it. Merging them wrong means a device
that cannot be reached, or one that shows up twice in the config flow.
"""

# pylint: disable=redefined-outer-name
# A test takes a fixture as an argument with the same name. That is the
# pytest pattern, not shadowing.

from collections.abc import AsyncIterator

from aiogree.api import (
    GreeDiscoveredDevice,
    gree_discover_devices,
    gree_discover_devices_cloud,
    gree_merge_discovered_devices,
)
from aiogree.cloud_api import CLOUD_SERVERS, GreeCloudApi, GreeRegion
import pytest

from .conftest import DISCOVERY_PORT
from .fakes.cloud import FakeGreeCloud, cloud_device
from .fakes.device import FakeGreeDevice

LOCAL_MAC = "f4911e3f1ac8"
CLOUD_MAC = "c03937b12280"
DEVICE_KEY = "V1sT9p0aQ3zXcR7m"


@pytest.fixture
async def cloud_with_one_device(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[GreeCloudApi]:
    """Start a cloud account that holds one device."""
    server = FakeGreeCloud(
        homes=[{"id": 1, "name": "Thuis"}],
        devices_per_home={1: [cloud_device(LOCAL_MAC, DEVICE_KEY, name="Zolderkamer")]},
    )
    await server.start()
    monkeypatch.setitem(CLOUD_SERVERS, GreeRegion.EU, server.url)

    api = GreeCloudApi.for_server(GreeRegion.EU, "rob@example.com", "hunter2")
    await api.login()
    try:
        yield api
    finally:
        await api.close()
        await server.close()


async def test_cloud_discovery_returns_the_account_devices(
    cloud_with_one_device: GreeCloudApi,
) -> None:
    """A cloud device carries its key, which local discovery never does."""
    found = await gree_discover_devices_cloud(cloud_with_one_device)

    assert len(found) == 1
    assert found[0].mac == LOCAL_MAC
    assert found[0].key == DEVICE_KEY
    assert found[0].name == "Zolderkamer"
    assert found[0].host is None


async def test_discovery_without_anything_to_search_returns_nothing() -> None:
    """No cloud account and no addresses means no work."""
    assert await gree_discover_devices(None, None) == []


async def test_discovery_joins_the_cloud_and_the_network(
    cloud_with_one_device: GreeCloudApi, loopback_ip: str
) -> None:
    """The same unit found twice comes back once, with both halves filled in."""
    unit = FakeGreeDevice(mac=LOCAL_MAC, name="Local name")
    await unit.start(loopback_ip, DISCOVERY_PORT)

    try:
        found = await gree_discover_devices(
            cloud_with_one_device, [loopback_ip], timeout=1
        )
    finally:
        unit.close()

    assert len(found) == 1
    assert found[0].mac == LOCAL_MAC
    assert found[0].host == loopback_ip
    assert found[0].key == DEVICE_KEY
    # The cloud name is the one the user gave the unit in the app.
    assert found[0].name == "Zolderkamer"


def test_a_device_that_is_only_local_is_kept() -> None:
    """Most installs have no cloud account at all."""
    local = GreeDiscoveredDevice(mac=LOCAL_MAC, host="192.168.1.10", name="Zolderkamer")

    merged = gree_merge_discovered_devices([local], [])

    assert merged == [local]


def test_a_device_that_is_only_in_the_cloud_is_kept() -> None:
    """A unit on another subnet is only reachable over the cloud."""
    cloud = GreeDiscoveredDevice(mac=CLOUD_MAC, key=DEVICE_KEY, name="Kantoor")

    merged = gree_merge_discovered_devices([], [cloud])

    assert merged == [cloud]


def test_merging_fills_the_local_fields_into_the_cloud_device() -> None:
    """Local knows how to reach it, the cloud knows what it is called."""
    local = GreeDiscoveredDevice(
        mac=LOCAL_MAC, host="192.168.1.10", port=7000, name="Local name", ver="V3.2.M"
    )
    cloud = GreeDiscoveredDevice(
        mac=LOCAL_MAC, key=DEVICE_KEY, name="Zolderkamer", user_id=4242
    )

    merged = gree_merge_discovered_devices([local], [cloud])

    assert len(merged) == 1
    assert merged[0].host == "192.168.1.10"
    assert merged[0].key == DEVICE_KEY
    assert merged[0].ver == "V3.2.M"
    assert merged[0].name == "Zolderkamer"
    assert merged[0].user_id == 4242


def test_merging_does_not_let_an_empty_local_field_win() -> None:
    """Local discovery leaves most fields blank. Blank must not erase the cloud.

    Only a blank field is skipped. A field with a real default, such as `model`
    and `brand` which both default to "gree", is treated as a value and the
    local one wins.
    """
    local = GreeDiscoveredDevice(mac=LOCAL_MAC, host="192.168.1.10")
    cloud = GreeDiscoveredDevice(
        mac=LOCAL_MAC, key=DEVICE_KEY, mid="60", hid="362001065279", model="U-CS532Z"
    )

    merged = gree_merge_discovered_devices([local], [cloud])

    assert merged[0].key == DEVICE_KEY
    assert merged[0].mid == "60"
    assert merged[0].hid == "362001065279"
    assert merged[0].model == "gree"


def test_merging_sorts_by_mac() -> None:
    """A stable order keeps the config flow list from jumping around."""
    first = GreeDiscoveredDevice(mac="aaaa00000000")
    second = GreeDiscoveredDevice(mac="bbbb00000000")

    merged = gree_merge_discovered_devices([second], [first])

    assert [device.mac for device in merged] == [
        "aaaa00000000",
        "bbbb00000000",
    ]


def test_the_friendly_name_says_where_a_device_was_found() -> None:
    """The config flow shows this, so it has to tell the two apart."""
    local = GreeDiscoveredDevice(mac=LOCAL_MAC, host="192.168.1.10", name="Zolderkamer")
    cloud = GreeDiscoveredDevice(mac=CLOUD_MAC)

    assert local.friendly_name == f"Zolderkamer, {LOCAL_MAC} (Local)"
    assert cloud.friendly_name == f"{CLOUD_MAC} (Cloud)"
