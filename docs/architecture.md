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
| `__init__.py` | Entry setup. Builds transports and devices, binds them, starts one `GreeCoordinator` per device. |
| `coordinator.py` | `GreeCoordinator`. Polls on `scan_interval` and listens for status pushed by the device. |
| `config_flow.py` | Setup, reconfigure and reauth flows. Local discovery, cloud login, device picker, per device options. |
| `climate.py`, `switch.py`, `sensor.py`, `binary_sensor.py`, `number.py`, `select.py` | Entity platforms. |
| `entity.py`, `platform_helpers.py` | Base entity, availability logic, shared helpers. |
| `services.py`, `services.yaml` | Services `get_prop_values` and `get_prop_values_all`. |
| `diagnostics.py` | Diagnostics download for the entry and for a device. Redacts keys and passwords. |
| `const.py` | Config keys, defaults, mode maps, `CURRENT_CONF_VERSION`. |

Also in the repo root: `supported-devices.md`, `manual-configuration.yaml`, `hacs.json`.

## How a device comes to life

`GreeDevice.bind_with_transport()` runs these steps in order:

1. Bind. Try the local transport first, then MQTT. Binding is the key exchange, see [protocol.md](protocol.md#encryption). Right after the key exchange, `probe_device_limits()` measures how many columns one status request may carry on this firmware, see [protocol.md](protocol.md#requests-and-batching).
2. `fetch_device_info()`. Asks for the `InfoProp` columns (MAC, name, model, firmware).
3. `fetch_device_status()`. Asks for all polled `GreeProp` columns. The request is split into batches, see [protocol.md](protocol.md#requests-and-batching).
4. `_remove_unsupported_props()`. Any prop the device did not return is removed from polling for the life of the object. If the device returned nothing at all, this raises `GreeProtocolError` instead, so setup fails and Home Assistant retries later.

After that the coordinator calls `fetch_device_status()` every `scan_interval` seconds (default 60).

Entities are only created for props the device supports. A device with few features gets few entities. That is by design.

## State model

State lives in `DeviceState`, one per device.

- `raw` is what the device last reported, as integers.
- `pending` is what we want to send next. `set()` writes here. Reads check `pending` first, then `raw`.
- `push_device_status()` sends the pending values in one command and then refreshes `raw`.
- `info` holds the `InfoProp` values as strings.
- `unknown` holds columns the device sent that we do not know. They show up in diagnostics.
- `supports(prop)` is true only if the prop is in `raw` and in the capability list. The beeper is always supported.
- `polled_properties` is the list that goes out on every poll. It only shrinks.

## Availability

An entity is available when the last coordinator poll succeeded and the device client reports itself available. One missed poll makes the entity unavailable until the next good poll. `disable_available_check` in the device options turns this off, and the entity is then always available.

`max_online_attempts` in the local connection options sets how many times one UDP request is retried. It does not set how many polls may fail in a row.

## Recovery

When a poll fails with `GreeConnectionError`, the coordinator runs `try_find_new_ip()`. That does a discovery broadcast, and if the device's MAC shows up with a new IP, the config entry is updated and the poll is retried once.
