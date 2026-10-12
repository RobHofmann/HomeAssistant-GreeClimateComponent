"""Tests for the reconfigure menu of an entry.

Most tests start from `cloud_entry`: a cloud entry made through the user flow,
with A on the LAN and B through the cloud only. C is on the account but not in
the entry. See `conftest.py` for what is real and what is faked.
"""

# pylint: disable=redefined-outer-name
# A test takes a fixture as an argument with the same name. That is the
# pytest pattern, not shadowing.

import copy

import pytest

from custom_components.gree_custom.aiogree.transport_mqtt import GreeMqttTransport
from custom_components.gree_custom.aiogree.transport_udp import GreeUdpTransport
from custom_components.gree_custom.const import (
    CONF_CLOUD,
    CONF_DEVICE_CONNECTION,
    CONF_DEVICE_CONNECTION_CLOUD,
    CONF_DEVICE_CONNECTION_LOCAL,
    CONF_DEVICE_OPTIONS,
    CONF_DEVICES,
    CONF_ENCRYPTION_VERSION,
    CONF_EXTRA_SCAN_HOSTS,
    CONF_MAC_CONTROLLER_LOCAL,
    CONF_PREFER_CLOUD,
    CONFENTRY_ID_LOCAL_ONLY,
    DOMAIN,
)
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from tests.config_flow.conftest import (
    DEPRECATED_LOOKUP,
    MAC_A,
    MAC_B,
    MAC_C,
    GreeEnv,
    add_entry,
    binds,
    choose,
    form_input,
    picker_options,
    registry_device,
    start_reconfigure,
    submit,
)
from tests.fakes.cloud import TOKEN
from tests.fakes.vrf import GATEWAY_MAC, FakeVrfGateway, sub_device_macs

FULL_MENU = ["edit_device", "rediscover", "remove_devices", "finish"]


def connection(entry: ConfigEntry, mac: str) -> dict:
    """Return the stored connection of one device."""
    return entry.data[CONF_DEVICES][mac][CONF_DEVICE_CONNECTION]


def coordinator_transport(entry: ConfigEntry, mac: str) -> object:
    """Return the transport the loaded entry uses for one device."""
    return entry.runtime_data[mac].device.transport


def reauth_flows(hass: HomeAssistant) -> list:
    """Return the reauth flows in progress."""
    return [
        flow
        for flow in hass.config_entries.flow.async_progress_by_handler(DOMAIN)
        if flow["context"]["source"] == SOURCE_REAUTH
    ]


async def test_finish_at_once_reloads_without_a_login(
    hass: HomeAssistant, gree: GreeEnv, cloud_entry: ConfigEntry
) -> None:
    """Finish without changes: no login, one reload, the same token, no reauth."""
    data_before = copy.deepcopy(dict(cloud_entry.data))

    result = await start_reconfigure(hass, cloud_entry)
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == FULL_MENU

    result = await choose(hass, result, "finish")
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()

    assert cloud_entry.state is ConfigEntryState.LOADED
    assert dict(cloud_entry.data) == data_before
    assert cloud_entry.data[CONF_CLOUD]["token"] == TOKEN
    assert not reauth_flows(hass)

    assert gree.logins == 0
    assert gree.setup_calls == 1
    gree.assert_only_entry_connections()


async def test_rediscover_finds_a_cloud_only_unit_on_the_lan(
    hass: HomeAssistant, gree: GreeEnv, cloud_entry: ConfigEntry
) -> None:
    """B shows up on the LAN. Only units that add something are listed.

    A already has both connections, so the picker leaves it out. B is listed
    because it gains a host, and C because it is not in the entry. After the
    forms, B has a local connection and nothing was removed.
    """
    host_a = connection(cloud_entry, MAC_A)[CONF_DEVICE_CONNECTION_LOCAL][CONF_HOST]
    host_b = await gree.start_udp(gree.devices[MAC_B])

    result = await start_reconfigure(hass, cloud_entry)
    result = await choose(hass, result, "rediscover")
    assert result["step_id"] == "rediscover"
    assert form_input(result)["include_local"] is True

    result = await submit(hass, result, include_local=True)
    assert result["step_id"] == "cloud_add"

    result = await submit(hass, result)
    assert result["step_id"] == "local_add"
    # The hosts of the first setup are prefilled
    assert form_input(result)[CONF_EXTRA_SCAN_HOSTS] == [host_a]

    result = await submit(hass, result, **{CONF_EXTRA_SCAN_HOSTS: [host_a, host_b]})
    assert result["step_id"] == "device_picker"
    assert sorted(picker_options(result)) == [MAC_B, MAC_C]

    result = await submit(hass, result, **{CONF_DEVICES: [MAC_B]})
    assert result["step_id"] == "connection_options"
    shown = form_input(result)
    assert shown[CONF_DEVICE_CONNECTION_LOCAL][CONF_HOST] == host_b
    assert shown[CONF_DEVICE_CONNECTION_LOCAL][CONF_MAC_CONTROLLER_LOCAL] == MAC_B

    result = await submit(hass, result)
    assert result["step_id"] == "device_options"
    result = await submit(hass, result)
    assert result["type"] is FlowResultType.MENU

    result = await choose(hass, result, "finish")
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()

    assert cloud_entry.state is ConfigEntryState.LOADED
    assert set(cloud_entry.data[CONF_DEVICES]) == {MAC_A, MAC_B}
    assert connection(cloud_entry, MAC_B)[CONF_DEVICE_CONNECTION_LOCAL][CONF_HOST] == (
        host_b
    )
    assert connection(cloud_entry, MAC_A)[CONF_DEVICE_CONNECTION_LOCAL][CONF_HOST] == (
        host_a
    )
    assert registry_device(hass, cloud_entry, MAC_A) is not None
    assert registry_device(hass, cloud_entry, MAC_B) is not None
    assert isinstance(coordinator_transport(cloud_entry, MAC_B), GreeUdpTransport)

    assert gree.logins == 1
    gree.assert_only_entry_connections()


async def test_rediscover_without_new_units_keeps_the_pending_edit(
    hass: HomeAssistant, gree: GreeEnv, cloud_entry: ConfigEntry
) -> None:
    """Nothing new: a step that says so, back to the menu, the edit survives."""
    # C left the account, so the cloud only lists the units of the entry
    gree.cloud.devices_per_home[1] = [
        d for d in gree.cloud.devices_per_home[1] if d["mac"] != MAC_C
    ]

    result = await start_reconfigure(hass, cloud_entry)
    result = await choose(hass, result, "edit_device")
    result = await submit(hass, result, **{CONF_DEVICES: MAC_B})
    result = await submit(hass, result)
    result = await submit(hass, result, **{CONF_NAME: "Slaapkamer boven"})
    assert result["type"] is FlowResultType.MENU

    result = await choose(hass, result, "rediscover")
    result = await submit(hass, result, include_local=False)
    result = await submit(hass, result)
    assert result["step_id"] == "no_new_devices"

    result = await submit(hass, result)
    assert result["type"] is FlowResultType.MENU

    result = await choose(hass, result, "finish")
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()

    options_b = cloud_entry.data[CONF_DEVICES][MAC_B][CONF_DEVICE_OPTIONS]
    assert options_b[CONF_NAME] == "Slaapkamer boven"
    assert cloud_entry.state is ConfigEntryState.LOADED

    assert gree.logins == 1
    assert gree.setup_calls == 1
    gree.assert_only_entry_connections()


async def test_edit_without_a_new_connection_reuses_the_running_device(
    hass: HomeAssistant, gree: GreeEnv, cloud_entry: ConfigEntry
) -> None:
    """A new name only: no login, no bind in the flow, one reload."""
    clients_before = len(gree.broker.clients)

    result = await start_reconfigure(hass, cloud_entry)
    result = await choose(hass, result, "edit_device")
    result = await submit(hass, result, **{CONF_DEVICES: MAC_B})
    assert result["step_id"] == "connection_options"

    result = await submit(hass, result)
    assert result["step_id"] == "device_options"
    result = await submit(hass, result, **{CONF_NAME: "Slaapkamer 2"})
    assert result["type"] is FlowResultType.MENU

    # The flow used the bind of the running entry
    assert binds(gree.devices[MAC_B]) == 0
    assert len(gree.broker.clients) == clients_before

    result = await choose(hass, result, "finish")
    await hass.async_block_till_done()

    options_b = cloud_entry.data[CONF_DEVICES][MAC_B][CONF_DEVICE_OPTIONS]
    assert options_b[CONF_NAME] == "Slaapkamer 2"
    assert cloud_entry.state is ConfigEntryState.LOADED

    assert gree.logins == 0
    assert gree.setup_calls == 1
    gree.assert_only_entry_connections()


async def test_edit_with_a_new_bind_setting_binds_with_the_stored_token(
    hass: HomeAssistant, gree: GreeEnv, cloud_entry: ConfigEntry
) -> None:
    """Prefer cloud for A: a bind over MQTT with the stored token, no login.

    The flow opens its own MQTT client for the bind and closes it when the
    flow ends.
    """
    clients_before = len(gree.broker.clients)

    result = await start_reconfigure(hass, cloud_entry)
    result = await choose(hass, result, "edit_device")
    result = await submit(hass, result, **{CONF_DEVICES: MAC_A})
    result = await submit(
        hass, result, **{CONF_DEVICE_CONNECTION_CLOUD: {CONF_PREFER_CLOUD: True}}
    )
    assert result["step_id"] == "device_options"

    flow_client = gree.broker.clients[clients_before]
    assert flow_client.options["password"] == TOKEN
    assert flow_client.entered
    assert not flow_client.exited
    assert any(topic == f"request/{MAC_A}" for topic, _ in flow_client.published)
    assert binds(gree.devices[MAC_A]) == 1
    assert gree.logins == 0

    result = await submit(hass, result)
    result = await choose(hass, result, "finish")
    await hass.async_block_till_done()

    assert flow_client.exited
    assert connection(cloud_entry, MAC_A)[CONF_DEVICE_CONNECTION_CLOUD][
        CONF_PREFER_CLOUD
    ]
    assert isinstance(coordinator_transport(cloud_entry, MAC_A), GreeMqttTransport)

    assert gree.logins == 0
    assert gree.setup_calls == 1
    gree.assert_only_entry_connections()


async def test_remove_devices(
    hass: HomeAssistant,
    gree: GreeEnv,
    cloud_entry: ConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A removed unit leaves the entry and the device registry.

    The lookup in the registry does not use the call that Home Assistant
    2026.10 reports as deprecated.
    """
    assert registry_device(hass, cloud_entry, MAC_B) is not None

    result = await start_reconfigure(hass, cloud_entry)
    result = await choose(hass, result, "remove_devices")
    result = await submit(hass, result, **{CONF_DEVICES: [MAC_B]})
    assert result["type"] is FlowResultType.MENU
    assert result["description_placeholders"]["device_cnt"] == "1"

    result = await choose(hass, result, "finish")
    await hass.async_block_till_done()

    assert set(cloud_entry.data[CONF_DEVICES]) == {MAC_A}
    assert registry_device(hass, cloud_entry, MAC_B) is None
    assert registry_device(hass, cloud_entry, MAC_A) is not None
    assert cloud_entry.state is ConfigEntryState.LOADED
    assert DEPRECATED_LOOKUP not in caplog.text

    assert gree.logins == 0
    gree.assert_only_entry_connections()


async def test_local_only_entry_never_logs_in(
    hass: HomeAssistant, gree: GreeEnv
) -> None:
    """A local-only entry: the edit reuses the running device, no step logs in."""
    host_a = await gree.start_udp(gree.devices[MAC_A])
    entry = await add_entry(hass, ["local"], [MAC_A], [host_a])
    assert entry.unique_id == CONFENTRY_ID_LOCAL_ONLY
    assert entry.data[CONF_CLOUD] is None
    gree.reset_counts()

    result = await start_reconfigure(hass, entry)
    assert result["menu_options"] == FULL_MENU

    result = await choose(hass, result, "edit_device")
    result = await submit(hass, result, **{CONF_DEVICES: MAC_A})
    result = await submit(hass, result)
    assert result["step_id"] == "device_options"
    assert binds(gree.devices[MAC_A]) == 0

    result = await submit(hass, result, **{CONF_NAME: "Woonkamer 2"})

    # Rediscover goes straight to the LAN scan
    result = await choose(hass, result, "rediscover")
    assert result["step_id"] == "local_add"
    result = await submit(hass, result)
    assert result["step_id"] == "no_new_devices"
    result = await submit(hass, result)

    result = await choose(hass, result, "finish")
    await hass.async_block_till_done()

    assert entry.data[CONF_DEVICES][MAC_A][CONF_DEVICE_OPTIONS][CONF_NAME] == (
        "Woonkamer 2"
    )
    assert entry.state is ConfigEntryState.LOADED
    assert not gree.cloud.requests
    assert not gree.broker.clients
    assert gree.setup_calls == 1
    gree.assert_only_entry_connections()


async def test_vrf_host_change_moves_every_sub_unit(
    hass: HomeAssistant, gree: GreeEnv
) -> None:
    """A new host for one sub-unit is also written to the others behind it.

    The gateway moved to a new address and port. The user edits one sub-unit,
    and its sibling gets the same values. A change of encryption version is
    not covered: the fake answers a scan in V2 when it is a V2 unit, and the
    component reads scan replies in V1 only.
    """
    old_gateway = FakeVrfGateway(sub_count=2)
    new_gateway = FakeVrfGateway(sub_count=2)
    gree.devices["old_gateway"] = old_gateway
    gree.devices["new_gateway"] = new_gateway
    old_host = await gree.start_udp(old_gateway)
    new_host = await gree.start_udp(new_gateway, port=0)

    sub_macs = sub_device_macs(GATEWAY_MAC, 2)
    entry = await add_entry(hass, ["local"], sub_macs, [old_host])
    for mac in sub_macs:
        local = connection(entry, mac)[CONF_DEVICE_CONNECTION_LOCAL]
        assert local[CONF_MAC_CONTROLLER_LOCAL] == GATEWAY_MAC
        assert local[CONF_HOST] == old_host
    gree.reset_counts()

    result = await start_reconfigure(hass, entry)
    result = await choose(hass, result, "edit_device")
    result = await submit(hass, result, **{CONF_DEVICES: sub_macs[0]})
    result = await submit(
        hass,
        result,
        **{
            CONF_DEVICE_CONNECTION_LOCAL: {
                CONF_HOST: new_host,
                CONF_PORT: new_gateway.port,
            }
        },
    )
    assert result["step_id"] == "device_options"
    result = await submit(hass, result)
    result = await choose(hass, result, "finish")
    await hass.async_block_till_done()

    for mac in sub_macs:
        local = connection(entry, mac)[CONF_DEVICE_CONNECTION_LOCAL]
        assert local[CONF_HOST] == new_host, mac
        assert local[CONF_PORT] == new_gateway.port, mac
        assert local[CONF_ENCRYPTION_VERSION] == "1", mac
        assert entry.runtime_data[mac].device.is_bound, mac

    assert entry.state is ConfigEntryState.LOADED
    assert binds(new_gateway) >= 1
    assert binds(old_gateway) == 0
    assert gree.setup_calls == 1
    gree.assert_only_entry_connections()


async def test_closing_reconfigure_after_a_login_closes_its_connection(
    hass: HomeAssistant, gree: GreeEnv, cloud_entry: ConfigEntry
) -> None:
    """The user closes the flow at the picker: its MQTT client closes too."""
    clients_before = len(gree.broker.clients)

    result = await start_reconfigure(hass, cloud_entry)
    result = await choose(hass, result, "rediscover")
    result = await submit(hass, result, include_local=False)
    result = await submit(hass, result)
    assert result["step_id"] == "device_picker"
    assert gree.logins == 1

    flow_client = gree.broker.clients[clients_before]
    assert flow_client.entered
    assert not flow_client.exited

    hass.config_entries.flow.async_abort(result["flow_id"])
    await hass.async_block_till_done()

    assert flow_client.exited
    assert cloud_entry.state is ConfigEntryState.LOADED
    assert gree.setup_calls == 0
    gree.assert_only_entry_connections()
