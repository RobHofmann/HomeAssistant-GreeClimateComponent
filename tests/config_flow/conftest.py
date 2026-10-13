"""Fixtures for the config flow tests.

These tests run the shipped config flow inside a real Home Assistant, from
pytest-homeassistant-custom-component: the flow manager, the config entries,
the device registry and the reload after a flow. What is real and what is
faked:

- Gree Cloud: `FakeGreeCloud`, real HTTP on loopback. Only the server address
  of the region changes, so the login and the device list run the real client.
- MQTT: `FakeMqttBroker`. It replaces `aiomqtt.Client`, and it hands every
  request to a `FakeGreeDevice`, so a bind over the cloud runs the real
  protocol. The broker can refuse a login, or accept only the newest token
  (`GreeEnv.revoke_token`).
- Local devices: `FakeGreeDevice` and `FakeVrfGateway` on real UDP sockets, on
  port 7000 of their own address in 127.0.0.0/8. Discovery reaches them through
  the extra hosts field of the flow, which is the real unicast scan.
- Broadcast: switched off. The test host has no LAN, and a broadcast would
  leave the machine. That is the one function of the component that is
  replaced (`helpers._get_hass_broadcast_addr`).

Every test also checks resource hygiene: how many cloud logins it made, and
that the only MQTT clients and UDP sockets still open belong to a loaded
config entry. When the test ends, every entry is unloaded and nothing may stay
open.
"""

from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from dataclasses import dataclass, field
import logging
from typing import Any

import pytest

import custom_components.gree_custom as gree_component
from custom_components.gree_custom import config_flow, helpers as gree_helpers
from custom_components.gree_custom.aiogree import (
    cloud_api,
    transport_mqtt,
    transport_udp,
)
from custom_components.gree_custom.aiogree.cloud_api import GreeRegion
from custom_components.gree_custom.aiogree.transport_mqtt import GreeMqttTransport
from custom_components.gree_custom.aiogree.transport_udp import GreeUdpTransport
from custom_components.gree_custom.const import (
    CONF_DEVICES,
    CONF_EXTRA_SCAN_HOSTS,
    DOMAIN,
)
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    SOURCE_USER,
    ConfigEntry,
    ConfigEntryState,
    ConfigFlowResult,
)
from homeassistant.const import CONF_DISCOVERY, CONF_EMAIL, CONF_PASSWORD, CONF_REGION
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, section
from homeassistant.helpers import device_registry as dr
from tests.conftest import RecordingHandler
from tests.fakes.cloud import USER_ID, FakeGreeCloud, cloud_device
from tests.fakes.device import FakeGreeDevice
from tests.fakes.mqtt import BrokerClient, FakeMqttBroker

# The component logs under this name inside Home Assistant.
COMPONENT_LOGGER = "custom_components.gree_custom"

DISCOVERY_PORT = 7000

# Three units on one cloud account. A is also reachable on the LAN, B and C
# only through the cloud, until a test starts their UDP side.
MAC_A = "c03937a10001"
MAC_B = "c03937b20002"
MAC_C = "c03937c30003"
NAMES = {MAC_A: "Woonkamer", MAC_B: "Slaapkamer", MAC_C: "Zolder"}
KEYS = {MAC_A: "KeyA4f9Qz7Lm2Wx1", MAC_B: "KeyB8d3Rt6Yn0Pv5", MAC_C: "KeyC2s7Hj4Gk9Bq3"}

CLOUD_LOGIN = {
    CONF_EMAIL: "rob@example.com",
    CONF_PASSWORD: "hunter2",
    CONF_REGION: GreeRegion.EU.value,
}

LOGIN_PATH = "/App/UserLoginV2"

# What Home Assistant 2026.10 logs when an integration calls the deprecated
# `device_registry.async_get_device`.
DEPRECATED_LOOKUP = "calls `device_registry.async_get_device`"


@dataclass
class GreeEnv:
    """The fakes of one test, and the counters the tests assert on."""

    hass: HomeAssistant
    cloud: FakeGreeCloud
    broker: FakeMqttBroker
    reserve_ips: Callable[[int], list[str]]
    devices: dict[str, FakeGreeDevice] = field(default_factory=dict)
    udp_streams: list[Any] = field(default_factory=list)
    setup_calls: int = 0

    @property
    def logins(self) -> int:
        """Count the cloud logins since the last reset."""
        return sum(1 for path, _ in self.cloud.requests if path == LOGIN_PATH)

    def reset_counts(self) -> None:
        """Start counting logins, setups and device requests from zero."""
        self.cloud.requests.clear()
        self.setup_calls = 0
        for device in self.devices.values():
            device.reset_record()

    async def start_udp(
        self, device: FakeGreeDevice, port: int = DISCOVERY_PORT
    ) -> str:
        """Put a device on the LAN, on its own loopback address. Returns the host."""
        host = self.reserve_ips(1)[0]
        await device.start(host, port)
        return host

    def revoke_token(self, new_token: str) -> None:
        """Make the stored token invalid, as a login in the Gree app does.

        The broker accepts only `new_token` from now on, and the next cloud
        login hands it out.
        """
        self.cloud.login_response = {"uid": USER_ID, "token": new_token}
        self.broker.accepted_tokens = {new_token}

    def open_mqtt(self) -> list[BrokerClient]:
        """Return the MQTT clients that are connected."""
        return self.broker.open_clients()

    def open_udp(self) -> list[Any]:
        """Return the UDP sockets of the component that are still open.

        asyncio_dgram has no public way to ask if a stream is closed.
        """
        return [
            s
            for s in self.udp_streams
            if not s._transport.is_closing()  # noqa: SLF001
        ]

    def entry_connections(self) -> tuple[list[Any], list[Any]]:
        """Return the MQTT clients and UDP sockets of the loaded entries.

        A transport keeps its connection private, so this reads the private
        fields. There is no public way to ask a transport for its socket.
        """
        mqtt: list[Any] = []
        udp: list[Any] = []
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.state is not ConfigEntryState.LOADED:
                continue
            for coordinator in (getattr(entry, "runtime_data", None) or {}).values():
                transport = coordinator.device.transport
                if isinstance(transport, GreeMqttTransport):
                    client = transport._client  # noqa: SLF001
                    if client:
                        mqtt.append(client)
                if isinstance(transport, GreeUdpTransport):
                    stream = transport._stream  # noqa: SLF001
                    if stream:
                        udp.append(stream)
        return mqtt, udp

    def assert_only_entry_connections(self) -> None:
        """Check that every open connection belongs to a loaded entry."""
        entry_mqtt, entry_udp = self.entry_connections()
        assert _ids(self.open_mqtt()) == _ids(entry_mqtt), (
            "an MQTT client is open that no loaded entry uses"
        )
        assert _ids(self.open_udp()) == _ids(entry_udp), (
            "a UDP socket is open that no loaded entry uses"
        )


def _ids(objects: list[Any]) -> set[int]:
    """Compare connections by identity."""
    return {id(o) for o in objects}


def binds(device: FakeGreeDevice) -> int:
    """Count the bind requests a device got since its last reset."""
    return sum(1 for pack in device.packs if pack.get("t") == "bind")


@pytest.fixture(autouse=True)
def component_logs() -> Iterator[RecordingHandler]:
    """Fail a test when the component writes a log line that cannot be formatted."""
    handler = RecordingHandler()
    logger = logging.getLogger(COMPONENT_LOGGER)
    logger.addHandler(handler)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)

    assert not handler.format_errors, (
        f"log lines that could not be formatted: {handler.format_errors}"
    )


@pytest.fixture
async def gree(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    monkeypatch: pytest.MonkeyPatch,
    loopback_ips: Callable[[int], list[str]],
) -> AsyncIterator[GreeEnv]:
    """Start the fakes and point the component at them."""
    cloud = FakeGreeCloud(
        devices_per_home={1: [cloud_device(m, KEYS[m], NAMES[m]) for m in NAMES]}
    )
    await cloud.start()
    monkeypatch.setitem(cloud_api.CLOUD_SERVERS, GreeRegion.EU, cloud.url)

    broker = FakeMqttBroker()
    monkeypatch.setattr(transport_mqtt.aiomqtt, "Client", broker.client)

    env = GreeEnv(hass=hass, cloud=cloud, broker=broker, reserve_ips=loopback_ips)

    for mac, name in NAMES.items():
        env.devices[mac] = FakeGreeDevice(mac=mac, name=name, session_key=KEYS[mac])
        broker.add(env.devices[mac])

    real_connect = transport_udp.asyncio_dgram.connect

    async def recording_connect(*args: Any, **kwargs: Any) -> Any:
        stream = await real_connect(*args, **kwargs)
        env.udp_streams.append(stream)
        return stream

    monkeypatch.setattr(transport_udp.asyncio_dgram, "connect", recording_connect)

    async def no_broadcast(_hass: HomeAssistant) -> list[str]:
        return []

    monkeypatch.setattr(gree_helpers, "_get_hass_broadcast_addr", no_broadcast)

    # A scan always waits for its whole window, so keep it short.
    monkeypatch.setattr(config_flow, "DEFAULT_DISCOVERY_TIMEOUT", 1)

    real_setup_entry = gree_component.async_setup_entry

    async def counting_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
        env.setup_calls += 1
        return await real_setup_entry(hass, entry)

    monkeypatch.setattr(gree_component, "async_setup_entry", counting_setup_entry)

    try:
        yield env

        # Close what a test left open, then check that nothing stays behind
        for flow in hass.config_entries.flow.async_progress_by_handler(DOMAIN):
            hass.config_entries.flow.async_abort(flow["flow_id"])
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.state is ConfigEntryState.LOADED:
                assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

        assert not env.open_mqtt(), "an MQTT client is open after every unload"
        assert not env.open_udp(), "a UDP socket is open after every unload"
    finally:
        for device in env.devices.values():
            device.close()
        await cloud.close()


# Form helpers. They fill a form the way the frontend does: every field starts
# at its default or suggested value, and the test only names what it changes.


def _schema_defaults(schema: Any) -> dict[str, Any]:
    """Return the values a form shows before the user changes anything."""
    values: dict[str, Any] = {}
    for key, value in schema.schema.items():
        name = str(key.schema)
        if isinstance(value, section):
            values[name] = _schema_defaults(value.schema)
        elif callable(key.default):
            values[name] = key.default()
        elif (key.description or {}).get("suggested_value"):
            values[name] = key.description["suggested_value"]
    return values


def form_input(result: ConfigFlowResult, **changes: Any) -> dict[str, Any]:
    """Return the input of a form, with some fields changed.

    A change to a section is a dict, merged into what the section shows.
    """
    assert result["type"] is FlowResultType.FORM, result
    schema = result["data_schema"]
    values = _schema_defaults(schema) if schema is not None else {}
    for name, value in changes.items():
        if isinstance(value, Mapping) and isinstance(values.get(name), dict):
            values[name] = {**values[name], **value}
        else:
            values[name] = value
    return values


async def submit(
    hass: HomeAssistant, result: ConfigFlowResult, **changes: Any
) -> ConfigFlowResult:
    """Submit a form with its defaults and the given changes."""
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], form_input(result, **changes)
    )


async def choose(
    hass: HomeAssistant, result: ConfigFlowResult, step: str
) -> ConfigFlowResult:
    """Choose one option of a menu."""
    assert result["type"] is FlowResultType.MENU, result
    assert step in result["menu_options"], result["menu_options"]
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": step}
    )


def picker_labels(result: ConfigFlowResult) -> dict[str, str]:
    """Return the label of every MAC a device picker lists, in list order."""
    assert result["type"] is FlowResultType.FORM, result
    selector = next(
        value
        for key, value in result["data_schema"].schema.items()
        if str(key.schema) == CONF_DEVICES
    )
    return {option["value"]: option["label"] for option in selector.config["options"]}


def picker_options(result: ConfigFlowResult) -> list[str]:
    """Return the MACs a device picker lists."""
    return list(picker_labels(result))


def form_mac(result: ConfigFlowResult, macs: list[str]) -> str:
    """Tell which device a device form is about."""
    shown = result["description_placeholders"]["device_name"]
    return next(mac for mac in macs if mac in shown)


async def submit_device_forms(
    hass: HomeAssistant,
    result: ConfigFlowResult,
    macs: list[str],
    connection: Mapping[str, Mapping[str, Any]] | None = None,
    options: Mapping[str, Mapping[str, Any]] | None = None,
) -> ConfigFlowResult:
    """Submit the connection and option forms of the picked devices.

    `connection` and `options` hold the changes per device MAC. A device
    without changes gets the defaults.
    """
    while result["type"] is FlowResultType.FORM and result["step_id"] in (
        "connection_options",
        "device_options",
    ):
        mac = form_mac(result, macs)
        changes = (
            connection if result["step_id"] == "connection_options" else options
        ) or {}
        result = await submit(hass, result, **changes.get(mac, {}))
    return result


async def add_entry(
    hass: HomeAssistant,
    methods: list[str],
    picks: list[str],
    hosts: list[str] | None = None,
) -> ConfigEntry:
    """Add a config entry through the user flow and wait until it is set up."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_DISCOVERY: methods}
    )
    if "cloud" in methods:
        assert result["step_id"] == "cloud_add"
        result = await submit(hass, result, **CLOUD_LOGIN)
    if "local" in methods:
        assert result["step_id"] == "local_add"
        result = await submit(hass, result, **{CONF_EXTRA_SCAN_HOSTS: hosts or []})

    assert result["step_id"] == "device_picker", result
    result = await submit(hass, result, **{CONF_DEVICES: picks})
    result = await submit_device_forms(hass, result, picks)

    assert result["type"] is FlowResultType.CREATE_ENTRY, result
    await hass.async_block_till_done()

    entry: ConfigEntry = result["result"]
    assert entry.state is ConfigEntryState.LOADED
    return entry


async def start_reconfigure(
    hass: HomeAssistant, entry: ConfigEntry
) -> ConfigFlowResult:
    """Open the reconfigure flow of an entry."""
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    )


def registry_device(
    hass: HomeAssistant, entry: ConfigEntry, mac: str
) -> dr.DeviceEntry | None:
    """Return the device registry row of one unit of an entry.

    `async_get_device` and lookups on `devices` are deprecated in Home
    Assistant 2026.10, and their replacements are not in 2026.3.
    """
    return next(
        (
            device
            for device in dr.async_entries_for_config_entry(
                dr.async_get(hass), entry.entry_id
            )
            if (DOMAIN, mac) in device.identifiers
        ),
        None,
    )


@pytest.fixture
async def cloud_entry(hass: HomeAssistant, gree: GreeEnv) -> ConfigEntry:
    """Set up a cloud entry through the user flow, as in the maintainer's test.

    A is picked from the LAN, B through the cloud only, C is left out. The
    counters start at zero after the setup.
    """
    host_a = await gree.start_udp(gree.devices[MAC_A])
    entry = await add_entry(hass, ["cloud", "local"], [MAC_A, MAC_B], [host_a])
    gree.reset_counts()
    return entry
