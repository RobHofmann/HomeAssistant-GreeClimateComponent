# Architecture

Everything lives under `custom_components/gree_custom/`. There are two layers. The protocol layer (`aiogree/`) knows the device and nothing about Home Assistant. The Home Assistant layer knows entities and config entries and calls into `aiogree/`.

## Protocol layer, `aiogree/`

No Home Assistant imports here.

| File | What it does |
|---|---|
| `api.py` | Wire protocol. `GreeProp`, `InfoProp` and `OtherProps` enums, pack builders, status and command requests, discovery, `StatusResult`. |
| `cipher.py` | `CipherV1` (AES-128 ECB) and `CipherV2` (AES-128 GCM). `EncryptionVersion` enum. |
| `transport.py` | `GreeBaseTransport`. Shared request and listener logic. `request_json()` encrypts, sends, decrypts. |
| `transport_udp.py` | Local UDP transport. Port 7000. One socket, one request at a time, retries with backoff. |
| `transport_mqtt.py` | Gree Cloud MQTT transport, one broker per region. |
| `cloud_api.py` | Gree Cloud REST login and device list, one host per region. |
| `device.py` | `GreeDevice`. Binds, fetches info and status, pushes changes, exposes typed properties. |
| `device_api_client.py` | `DeviceApiClient`. Holds the bound session: transport, cipher, controller MAC. Runs the property queries. |
| `device_state.py` | `DeviceState`. Raw values, pending values, info values, which props are polled. |
| `helpers.py` | Encrypt and decrypt packs, temperature math, `TempOffsetResolver`, `redact_str`, `chunked`. |
| `const.py` | Protocol constants: `MAX_PACK_SIZE`, `MIN_PACK_PROPS`, `STATUS_CANARY_PROP`, `PROBE_TIMEOUT`, `MAX_UNANSWERED_IN_A_ROW`, temperature and humidity ranges. |
| `errors.py` | Exceptions. `GreeConnectionError` means no answer. `GreeProtocolError` means a bad answer. `GreeBindingError` means the key exchange failed. |

## Home Assistant layer

| File | What it does |
|---|---|
| `__init__.py` | Entry setup. Builds transports and devices, binds them, starts one `GreeCoordinator` per device. Creates and links the VRF controller devices, see [VRF controller device](#vrf-controller-device). |
| `coordinator.py` | `GreeCoordinator`. Polls on `scan_interval` and listens for status pushed by the device. Polls again every 2 s after a command while the device has not confirmed it, until the hold ends. |
| `config_flow.py` | Setup, reconfigure, reauth and YAML import flows. Local discovery, cloud login, device picker, per device options. `async_step_import` turns one validated YAML item into a config entry. |
| `config_schema.py` | `CONFIG_SCHEMA` for the `gree_custom:` block in `configuration.yaml`. Validates the YAML, normalizes the MAC addresses and fills the defaults. It also holds the form schemas that the config flow shows. |
| `migration.py` | Moves a 4.x setup (domain `gree`) to this integration: config entries, the `gree:` YAML block, and the device and entity registry rows. See [config-entry.md](config-entry.md#migration-from-4x). |
| `climate.py`, `switch.py`, `sensor.py`, `binary_sensor.py`, `number.py`, `select.py` | Entity platforms. |
| `entity.py`, `platform_helpers.py` | Base entity, availability logic, shared helpers. |
| `services.py`, `services.yaml` | Services `get_prop_values` and `get_prop_values_all`. |
| `diagnostics.py` | Diagnostics download for the entry and for a device. Redacts keys and passwords. |
| `helpers.py` | Discovery addresses, IP recovery, config entry lookups, and `reconcile_vrf_controllers()`. |
| `const.py` | Config keys, defaults, mode maps, `CURRENT_CONF_VERSION`. |

Also in the repo root: `supported-devices.md`, `manual-configuration.yaml`, `hacs.json`.

## Discovery

Discovery runs before any device object exists, and it has its own path.

- `gree_discover_devices_local()` sends a `scan` broadcast and reads whatever
  answers inside the listen window. The window is a plain sleep, so it always
  takes the full timeout.
- `gree_discover_device_local()` scans one host.
- A host that answers with `subCnt` above zero is a VRF gateway. It is bound,
  asked for its sub-device list, and then left out of the result itself. Only
  the units behind it are returned. The list request has three forms, see
  [protocol.md](protocol.md#vrf-gateways).
- `gree_discover_devices_local()` handles the scan replies side by side, so
  one slow gateway does not hold up the others.

Both functions build their own `GreeUdpTransport` and neither closes it. The
socket opens on the first request and is closed again when the function returns,
because `asyncio_dgram` closes it in `__del__`. Measured over 12 discovery runs
in a row, the number of open file descriptors stayed flat, so nothing builds up.
An explicit `disconnect()` would still be clearer, because this leans on
reference counting rather than on the code saying what it means.

## How a device comes to life

`GreeDevice.bind_with_transport()` runs these steps in order:

1. Bind. Try the local transport first, then MQTT. Binding is the key exchange, see [protocol.md](protocol.md#encryption). Right after the key exchange, `probe_device_limits()` measures how many columns one status request may carry on this firmware, see [protocol.md](protocol.md#requests-and-batching).
2. `fetch_device_info()`. Asks for the `InfoProp` columns (MAC, name, model, firmware).
3. `fetch_device_status()`. Asks for all polled `GreeProp` columns. The request is split into batches, see [protocol.md](protocol.md#requests-and-batching).
4. `_remove_unsupported_props()`. Any prop the device did not return is removed from polling for the life of the object. If the device returned nothing at all, this raises `GreeProtocolError` instead, so setup fails and Home Assistant retries later.

After that the coordinator calls `fetch_device_status()` every `scan_interval` seconds (default 60).

Entities are only created for props the device supports. A device with few features gets few entities. That is by design.

## VRF controller device

The indoor units behind one local VRF gateway are grouped under a controller device in the device registry. The device page of the gateway then shows the units under **Connected devices**.

- A sub-unit is a device whose `connection.local.mac_controller_local` is set and differs from its own MAC. The runtime `mac_address_controller` is not used, because for MQTT it comes from the cloud MAC.
- Every local controller MAC with at least one sub-unit gets one controller device. Its identifier is `(gree_custom, "controller_<mac>")`, its model is `VRF gateway`, and its name comes from the `vrf_controller` device translation.
- The controller has no entities and no `connections`. A MAC connection would merge it with any other device that has the same MAC.
- A cloud-only VRF has no local controller MAC, so it gets no controller device yet.

`reconcile_vrf_controllers()` in `helpers.py` does the work. Entry setup calls it twice. The first call, before the platforms are set up, creates the wanted controllers and removes the ones without a sub-unit. A wanted controller is never removed and created again, so its device id, user name and area survive a restart. The second call, after the platforms are set up, links each sub-unit with `async_update_device(via_device_id=...)`. The sub-unit devices only exist once their entities are added.

The link is set from setup code and not through `DeviceInfo`, because the API differs per Home Assistant version. In 2026.3 `DeviceInfo` only has `via_device`, a tuple. In 2026.9 it only has `via_device_id`, and `via_device` is deprecated. `async_update_device(via_device_id=...)` exists in both. The sub-units are looked up in `async_entries_for_config_entry()`, because `async_get_device()` is deprecated in 2026.9 and its replacement is not in 2026.3.

A user cannot delete the controller. `async_remove_config_entry_device()` raises the `remove_vrf_controller` error for it. After a sub-unit is deleted, the reconcile runs with the new device list, so a controller without sub-units goes away at once. The device diagnostics of a controller list the diagnostics of its sub-units.

## State model

State lives in `DeviceState`, one per device.

- `raw` is what the device last reported, as integers.
- `pending` is what we want to send next. `set()` writes here. Reads check `pending` first, then `held`, then `raw`.
- `held` is what was sent in the last commands to a VRF sub-unit and is not confirmed by the gateway yet. A hold ends when the device reports the sent value, or after 8 s. See [protocol.md](protocol.md#stale-state-after-a-command).
- `push_device_status()` sends the pending values in one command, moves them to `held`, and then refreshes `raw`.
- `info` holds the `InfoProp` values as strings.
- `unknown` holds columns the device sent that we do not know. They show up in diagnostics.
- `supports(prop)` is true only if the prop is in `raw` and in the capability list. The beeper is always supported.
- `polled_properties` is the list that goes out on every poll. It only shrinks.

## Availability

An entity is available when the last coordinator poll succeeded and the device client reports itself available. One missed poll makes the entity unavailable until the next good poll. `disable_available_check` in the device options turns this off, and the entity is then always available.

`max_online_attempts` in the local connection options sets how many times one UDP request is retried. It does not set how many polls may fail in a row.

## Recovery

When a poll fails with `GreeConnectionError`, the coordinator runs `try_find_new_ip()`. That does a discovery broadcast, and if the device's MAC shows up with a new IP, the config entry is updated and the poll is retried once.
