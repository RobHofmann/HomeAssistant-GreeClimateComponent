"""Tests for adding an entry: the user flow, the YAML import and reauth.

See `conftest.py` for what is real and what is faked.
"""

# pylint: disable=redefined-outer-name
# A test takes a fixture as an argument with the same name. That is the
# pytest pattern, not shadowing.

import copy
import logging

from aiomqtt.exceptions import MqttConnectError, MqttError
import pytest

from custom_components.gree_custom.config_schema import CONFIG_SCHEMA
from custom_components.gree_custom.const import (
    CONF_CLOUD,
    CONF_DEVICE_CONNECTION,
    CONF_DEVICE_CONNECTION_CLOUD,
    CONF_DEVICE_CONNECTION_LOCAL,
    CONF_DEVICE_OPTIONS,
    CONF_DEVICES,
    CONF_EXTRA_SCAN_HOSTS,
    CONF_MAC_CONTROLLER_CLOUD,
    CONFENTRY_ID_LOCAL_ONLY,
    DOMAIN,
)
from custom_components.gree_custom.helpers import is_mqtt_auth_refusal
from homeassistant.config_entries import (
    SOURCE_IMPORT,
    SOURCE_REAUTH,
    SOURCE_USER,
    ConfigEntry,
    ConfigEntryState,
)
from homeassistant.const import CONF_DISCOVERY, CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component
from tests.config_flow.conftest import (
    CLOUD_LOGIN,
    DEPRECATED_LOOKUP,
    MAC_A,
    MAC_B,
    MAC_C,
    GreeEnv,
    binds,
    registry_device,
    start_reconfigure,
    submit,
    submit_device_forms,
)
from tests.conftest import RecordingHandler
from tests.fakes.cloud import TOKEN, USER_ID
from tests.fakes.device import FakeGreeDevice
from tests.fakes.mqtt import connack_reason

# A unit that only the YAML knows.
MAC_D = "c03937d40004"
MAC_E = "c03937e50005"
NEW_TOKEN = "cloud-token-after-reauth"


async def test_user_setup_with_cloud_and_local(
    hass: HomeAssistant, gree: GreeEnv
) -> None:
    """Cloud and local discovery, one LAN unit and one cloud-only unit.

    The cloud lists three units and the LAN scan finds one of them. The user
    picks that one and a cloud-only one. The flow logs in once, binds A over
    UDP and B over MQTT, and closes its own connections when the entry is made.
    """
    host_a = await gree.start_udp(gree.devices[MAC_A])

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_DISCOVERY: ["cloud", "local"]}
    )
    assert result["step_id"] == "cloud_add"

    result = await submit(hass, result, **CLOUD_LOGIN)
    assert result["step_id"] == "local_add"
    assert gree.logins == 1

    result = await submit(hass, result, **{CONF_EXTRA_SCAN_HOSTS: [host_a]})
    assert result["step_id"] == "device_picker"
    assert result["description_placeholders"]["devices_found"] == "3"

    result = await submit(hass, result, **{CONF_DEVICES: [MAC_A, MAC_B]})
    assert result["step_id"] == "connection_options"

    result = await submit_device_forms(hass, result, [MAC_A, MAC_B])
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    entry = result["result"]
    assert entry.state is ConfigEntryState.LOADED
    assert entry.unique_id == str(USER_ID)
    assert entry.data[CONF_CLOUD]["token"] == TOKEN
    assert set(entry.data[CONF_DEVICES]) == {MAC_A, MAC_B}

    conn_a = entry.data[CONF_DEVICES][MAC_A][CONF_DEVICE_CONNECTION]
    conn_b = entry.data[CONF_DEVICES][MAC_B][CONF_DEVICE_CONNECTION]
    assert conn_a[CONF_DEVICE_CONNECTION_LOCAL][CONF_HOST] == host_a
    assert conn_a[CONF_DEVICE_CONNECTION_CLOUD][CONF_MAC_CONTROLLER_CLOUD] == MAC_A
    assert not conn_b[CONF_DEVICE_CONNECTION_LOCAL].get(CONF_HOST)
    assert conn_b[CONF_DEVICE_CONNECTION_CLOUD][CONF_MAC_CONTROLLER_CLOUD] == MAC_B

    # One login in total, the entry setup uses the stored token
    assert gree.logins == 1
    # The flow and the entry each bound A and B once
    assert binds(gree.devices[MAC_A]) == 2
    assert binds(gree.devices[MAC_B]) == 2
    assert binds(gree.devices[MAC_C]) == 0

    # The flow connected to the broker and closed it again. The entry has
    # its own client, for B.
    assert len(gree.broker.clients) == 2
    assert gree.broker.clients[0].exited
    assert len(gree.open_mqtt()) == 1
    gree.assert_only_entry_connections()


async def test_closing_the_user_flow_after_login_closes_its_connection(
    hass: HomeAssistant, gree: GreeEnv
) -> None:
    """The user closes the flow at the LAN step, after the cloud login."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_DISCOVERY: ["cloud", "local"]}
    )
    result = await submit(hass, result, **CLOUD_LOGIN)
    assert result["step_id"] == "local_add"
    assert len(gree.open_mqtt()) == 1

    hass.config_entries.flow.async_abort(result["flow_id"])
    await hass.async_block_till_done()

    assert gree.logins == 1
    assert not gree.open_mqtt()
    assert not hass.config_entries.async_entries(DOMAIN)


async def test_a_cloud_only_bind_logs_no_error(
    hass: HomeAssistant, gree: GreeEnv, component_logs: RecordingHandler
) -> None:
    """Binding a unit that has no host is normal and is not an error."""
    host_a = await gree.start_udp(gree.devices[MAC_A])
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_DISCOVERY: ["cloud", "local"]}
    )
    result = await submit(hass, result, **CLOUD_LOGIN)
    result = await submit(hass, result, **{CONF_EXTRA_SCAN_HOSTS: [host_a]})
    result = await submit(hass, result, **{CONF_DEVICES: [MAC_B]})
    result = await submit(hass, result)
    assert result["step_id"] == "device_options"

    try:
        assert "No controller MAC provided for local transport" not in (
            component_logs.messages(logging.ERROR)
        )
    finally:
        hass.config_entries.flow.async_abort(result["flow_id"])
        await hass.async_block_till_done()


def yaml_device(host: str, port: int, name: str) -> dict:
    """One device as a user writes it in configuration.yaml."""
    return {
        CONF_DEVICE_CONNECTION: {
            CONF_DEVICE_CONNECTION_LOCAL: {CONF_HOST: host, CONF_PORT: port}
        },
        CONF_DEVICE_OPTIONS: {CONF_NAME: name},
    }


async def test_yaml_managed_entry_cannot_be_reconfigured(
    hass: HomeAssistant, gree: GreeEnv, caplog: pytest.LogCaptureFixture
) -> None:
    """An entry from configuration.yaml refuses reconfigure.

    The YAML would put its own values back at the next start. When the YAML
    drops a device, the import removes it from the device registry, without
    the lookup that Home Assistant 2026.10 reports as deprecated.
    """
    hosts: dict[str, tuple[str, int]] = {}
    for mac, name in ((MAC_D, "Zolderkamer"), (MAC_E, "Washok")):
        gree.devices[mac] = FakeGreeDevice(mac=mac, name=name)
        host = await gree.start_udp(gree.devices[mac], port=0)
        hosts[mac] = (host, gree.devices[mac].port)

    config = {
        DOMAIN: [
            {
                CONF_DEVICES: {
                    MAC_D: yaml_device(*hosts[MAC_D], "Zolderkamer"),
                    MAC_E: yaml_device(*hosts[MAC_E], "Washok"),
                }
            }
        ]
    }
    assert await async_setup_component(hass, DOMAIN, config)
    await hass.async_block_till_done()

    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.unique_id == CONFENTRY_ID_LOCAL_ONLY
    assert entry.state is ConfigEntryState.LOADED
    assert registry_device(hass, entry, MAC_E) is not None

    result = await start_reconfigure(hass, entry)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "yaml_managed"

    # The next start reads a YAML without E. async_setup runs once per test,
    # so this hands the validated item to the import step, as it does.
    item = CONFIG_SCHEMA(
        {DOMAIN: [{CONF_DEVICES: {MAC_D: yaml_device(*hosts[MAC_D], "Zolderkamer")}}]}
    )[DOMAIN][0]
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_IMPORT}, data=item
    )
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()

    assert set(entry.data[CONF_DEVICES]) == {MAC_D}
    assert registry_device(hass, entry, MAC_E) is None
    assert registry_device(hass, entry, MAC_D) is not None
    assert entry.state is ConfigEntryState.LOADED
    assert DEPRECATED_LOOKUP not in caplog.text

    assert gree.logins == 0
    gree.assert_only_entry_connections()


def reauth_flows(hass: HomeAssistant) -> list:
    """Return the reauth flows in progress."""
    return [
        flow
        for flow in hass.config_entries.flow.async_progress_by_handler(DOMAIN)
        if flow["context"]["source"] == SOURCE_REAUTH
    ]


# What the fake cloud answers to a wrong password.
BAD_LOGIN = {"r": 400, "msg": "Wrong password"}


async def test_reauth_after_the_broker_refuses_the_token(
    hass: HomeAssistant, gree: GreeEnv, cloud_entry: ConfigEntry
) -> None:
    """A refused token and a failed login with the stored account start reauth.

    Setup tries one login with the stored account. When that fails too, it
    starts reauth. Reauth logs in once and reloads. Only the cloud block of
    the entry changes. The devices stay as they are.
    """
    devices_before = copy.deepcopy(dict(cloud_entry.data[CONF_DEVICES]))

    gree.broker.refuse_connect = True
    gree.cloud.login_response = BAD_LOGIN
    await hass.config_entries.async_reload(cloud_entry.entry_id)
    await hass.async_block_till_done()

    assert cloud_entry.state is ConfigEntryState.SETUP_ERROR
    flows = reauth_flows(hass)
    assert len(flows) == 1
    assert gree.logins == 1
    assert cloud_entry.data[CONF_CLOUD]["token"] == TOKEN
    # A was bound over UDP before B failed. The failed setup closed it again.
    assert not gree.open_udp()
    assert not gree.open_mqtt()

    gree.broker.refuse_connect = False
    gree.cloud.login_response = {"uid": USER_ID, "token": NEW_TOKEN}

    # Show the form of the step the flow waits in, then submit the stored account
    result = await hass.config_entries.flow.async_configure(flows[0]["flow_id"])
    assert result["step_id"] == "cloud_add"
    result = await submit(hass, result)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    await hass.async_block_till_done()

    assert cloud_entry.state is ConfigEntryState.LOADED
    assert cloud_entry.data[CONF_CLOUD]["token"] == NEW_TOKEN
    assert dict(cloud_entry.data[CONF_DEVICES]) == devices_before
    assert not reauth_flows(hass)

    assert gree.logins == 2
    # The entry connects with the new token
    assert [c.options["password"] for c in gree.open_mqtt()] == [NEW_TOKEN]
    gree.assert_only_entry_connections()


async def test_setup_refreshes_a_revoked_token_once(
    hass: HomeAssistant,
    gree: GreeEnv,
    cloud_entry: ConfigEntry,
    component_logs: RecordingHandler,
) -> None:
    """The Gree app logged in after Home Assistant, so the stored token is dead.

    Regression for the maintainer's report: "Save and reload" right after he
    created a cloud entry raised reauth with bad_credentials, because the
    broker refused the stored token. Setup now logs in once with the stored account, binds B with the new token
    and stores it. Storing the token does not reload the entry again.
    """
    gree.revoke_token(NEW_TOKEN)
    await hass.config_entries.async_reload(cloud_entry.entry_id)
    await hass.async_block_till_done()

    assert cloud_entry.state is ConfigEntryState.LOADED
    assert cloud_entry.data[CONF_CLOUD]["token"] == NEW_TOKEN
    assert cloud_entry.data[CONF_CLOUD]["uid"] == USER_ID
    assert not reauth_flows(hass)

    assert gree.logins == 1
    assert gree.setup_calls == 1
    assert binds(gree.devices[MAC_B]) == 1
    assert any("refused the stored token" in line for line in component_logs.warnings())

    assert [c.options["password"] for c in gree.open_mqtt()] == [NEW_TOKEN]
    gree.assert_only_entry_connections()


async def test_setup_starts_reauth_when_the_new_login_fails(
    hass: HomeAssistant, gree: GreeEnv, cloud_entry: ConfigEntry
) -> None:
    """A revoked token and a changed password: one login, then reauth."""
    gree.revoke_token(NEW_TOKEN)
    gree.cloud.login_response = BAD_LOGIN
    await hass.config_entries.async_reload(cloud_entry.entry_id)
    await hass.async_block_till_done()

    assert cloud_entry.state is ConfigEntryState.SETUP_ERROR
    assert len(reauth_flows(hass)) == 1
    assert cloud_entry.data[CONF_CLOUD]["token"] == TOKEN

    assert gree.logins == 1
    assert not gree.open_udp()
    assert not gree.open_mqtt()


async def test_setup_starts_reauth_when_the_new_token_is_refused_too(
    hass: HomeAssistant, gree: GreeEnv, cloud_entry: ConfigEntry
) -> None:
    """The login works, but the broker refuses the new token too: no loop.

    The login made the old token invalid, so the new one stays stored.
    """
    gree.broker.refuse_connect = True
    gree.cloud.login_response = {"uid": USER_ID, "token": NEW_TOKEN}
    await hass.config_entries.async_reload(cloud_entry.entry_id)
    await hass.async_block_till_done()

    assert cloud_entry.state is ConfigEntryState.SETUP_ERROR
    assert len(reauth_flows(hass)) == 1
    assert cloud_entry.data[CONF_CLOUD]["token"] == NEW_TOKEN

    assert gree.logins == 1
    assert not gree.open_udp()
    assert not gree.open_mqtt()


async def test_a_connect_error_that_is_not_about_the_token_does_not_log_in(
    hass: HomeAssistant, gree: GreeEnv, cloud_entry: ConfigEntry
) -> None:
    """A broker that is unavailable is no reason for a new login."""
    gree.broker.refuse_connect = True
    gree.broker.refuse_reason = connack_reason("Server unavailable")
    await hass.config_entries.async_reload(cloud_entry.entry_id)
    await hass.async_block_till_done()

    assert cloud_entry.state is ConfigEntryState.SETUP_ERROR
    assert cloud_entry.data[CONF_CLOUD]["token"] == TOKEN
    assert gree.logins == 0
    assert not gree.open_mqtt()


@pytest.mark.parametrize(
    ("rc", "refused"),
    [
        (4, True),
        (5, True),
        (connack_reason("Bad user name or password"), True),
        (connack_reason("Not authorized"), True),
        (3, False),
        (connack_reason("Server unavailable"), False),
    ],
)
def test_which_connect_errors_are_about_the_token(rc: object, refused: bool) -> None:
    """The MQTT 3.1.1 codes 4 and 5 and the MQTT 5 codes 134 and 135."""
    assert is_mqtt_auth_refusal(MqttConnectError(rc)) is refused
    assert not is_mqtt_auth_refusal(MqttError("lost connection"))
