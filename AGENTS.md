# AGENTS.md

Guide for coding agents working on this repository.
Read this before you change code. It covers what you cannot see from the code alone.

## 1. What this is

A custom Home Assistant integration for Gree air conditioners. Domain `gree_custom`, folder `custom_components/gree_custom/`. It talks to devices over local UDP, and can also use the Gree Cloud over MQTT.

The domain is `gree_custom` and not `gree` because Home Assistant ships its own `gree` integration. Do not rename it.

Older releases (4.x) used the domain `gree` and a different code base. Their config entries are flat, one device per entry. This version uses one hub entry per Gree account with a `devices` map and local-only hub entry when CLoud is not used. The two are not compatible and there is no automatic migration. Users moving from 4.x set the integration up again.

## 2. Versions

- Python: **3.14**. `.ruff.toml`, `mypy.ini` and `.pylintrc` all target 3.14.
- Home Assistant: the runtime this is tested on is 2026.3 or newer. HA 2026.3 was the first release that requires Python 3.14.
- Python 3.14 syntax is used on purpose. Example: `except GreeConnectionError, GreeProtocolError:` without brackets is valid (PEP 758). Do not "fix" it.
- `hacs.json` states the lowest HA version for HACS installs. Keep it in line with the Python version the code needs. HA 2026.1 and 2026.2 still run Python 3.13.

## 3. Where things live

Everything is under `custom_components/gree_custom/`.

Protocol layer is in `aiogree`, no Home Assistant imports:

| File                           | What it does                                                                                           |
| ------------------------------ | ------------------------------------------------------------------------------------------------------ |
| `aiogree/api.py`               | Wire protocol. `GreeProp` and `InfoProp` enums, pack builders, status and command requests, discovery. |
| `aiogree/cipher.py`            | `CipherV1` (AES-ECB) and `CipherV2` (AES-GCM). `EncryptionVersion` enum.                               |
| `aiogree/transport_udp.py`     | Local UDP transport. Port 7000. Reuses one socket.                                                     |
| `aiogree/transport_mqtt.py`    | Gree Cloud MQTT transport, one broker per region.                                                      |
| `aiogree/cloud_api.py`         | Gree Cloud REST login and device list, one host per region.                                            |
| `aiogree/device.py`            | `GreeDevice`. Binds, fetches info and status, pushes changes.                                          |
| `aiogree/device_api_client.py` | Holds the bound session: transport, key, controller MAC.                                               |
| `aiogree/device_state.py`      | `DeviceState`. Raw values, pending values, which props are polled.                                     |
| `aiogree/helpers.py`           | Protocol layer helpers: Encrypt and decrypt packs, temperature math, `redact_str`...                   |
| `aiogree/const.py`             | Protocol layer constants.                                                                              |
| `aiogree/errors.py`            | Protocol layer defined exceptions.                                                                     |

Home Assistant layer:

| File                                                                                 | What it does                                                                   |
| ------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------ |
| `__init__.py`                                                                        | Entry setup. Builds transports and devices, starts one coordinator per device. |
| `coordinator.py`                                                                     | `GreeCoordinator`. Polls on `scan_interval` and listens for pushed status.     |
| `config_flow.py`                                                                     | Setup and reconfigure flows. Local discovery, cloud login, per device options. |
| `climate.py`, `switch.py`, `sensor.py`, `binary_sensor.py`, `number.py`, `select.py` | Entity platforms.                                                              |
| `entity.py`, `platform_helpers.py`                                                   | Base entity and shared helpers.                                                |
| `services.py`, `services.yaml`                                                       | Services `get_prop_values` and `get_prop_values_all`.                          |
| `diagnostics.py`                                                                     | Diagnostics download. Redacts keys and passwords.                              |
| `const.py`                                                                           | Config keys, defaults, mode maps. `CURRENT_CONF_VERSION`.                      |

Also in the repo root: `supported-devices.md`, `manual-configuration.yaml`, `hacs.json`.

## 4. How a device comes to life

`GreeDevice.bind_with_transport()` does this, in order:

1. Bind. Try the local transport first, then MQTT.
2. `fetch_device_info()`. Asks for the `InfoProp` columns.
3. `fetch_device_status()`. Asks for all polled `GreeProp` columns.
4. `_remove_unsupported_props()`. Any prop the device did not return is removed from polling for the life of the object.

After that the coordinator calls `fetch_device_status()` every `scan_interval` seconds (default 60).

State lives in `DeviceState`:

- `raw` is what the device last reported.
- `pending` is what we want to send. `set()` writes here.
- `push_device_status()` sends pending values and refreshes raw.
- `supports(prop)` is true only if the prop is in `raw` and in the capability list.

Entities are only created for props the device supports. Fewer entities than an older version gave is normal.

## 5. Protocol facts that are easy to get wrong

Encryption:

- V1 is AES-128 ECB. Bind uses the generic key `GREE_GENERIC_DEVICE_KEY_ECB`. The device answers with its own key. All later packs use that key.
- V2 is AES-128 GCM with a fixed IV (`GCM_IV`) and a tag field in the packet.
- `EncryptionVersion.V1 = 1`, `V2 = 2`. In config, `"0"` means auto detect.
- A device silently drops any pack it cannot decrypt. No reply is the normal sign of a wrong key.

Requests:

- Packs are split into batches so no request passes `MAX_PACK_SIZE` (512 bytes) before encryption or `MAX_PACK_PROPS` (25 columns), whichever comes first. See `api.py`, the status request builder. The column cap exists because at least one firmware answers 29 columns, returns an empty result for 30 and stops replying at 31, no matter how small the pack is.
- A device may return fewer columns than asked. That is normal. Missing columns are reported in the result. It is not possible to reliable associate columns and values. 
- A device may return `r=200` with empty `cols` and `dat`. That is "no data", not "nothing is supported". `_remove_unsupported_props()` raises `GreeProtocolError` when the first status comes back empty, so setup fails and retries instead of leaving a device with nothing to poll.
- Some props are never answered at all, not even with an empty result. Seen on one firmware: `ElcDatDte`, `ElcDatHor`, `ElcDatMth`. The request just times out and the device is fine right after. This is why the diagnostic services (`get_prop_values`, `get_prop_values_all`) pass `max_attempts=1`, so an ignored prop costs one timeout instead of timeout x retries, and why `query_props()` stops after `MAX_UNANSWERED_IN_A_ROW` unanswered requests. Request rate is not a problem: 600 back-to-back single-prop requests were answered without a drop.
- The device does not type its values. `InfoProp` values can come back as `int` (seen: `ModelType` as `32768`) while others are `str`. Coerce everything to string on status pack received.

Temperature:

- `SetTem` is a whole number. `TemRec` adds the half degree.
- Some devices report sensors with a +40 offset. `TempOffsetResolver` in `aiogree/helpers.py` detects this from the values it sees.
- Fahrenheit uses the protocol's own lookup, not a formula.

Discovery and network:

- Local discovery is a UDP broadcast. `extra_scan_networks` and `extra_scan_hosts` exist for devices on another subnet where broadcast does not reach, and are probed via unicast.
- There are multiple ways to identify the devices (via their MAC addresses)
  - MACs are formated by using lower case and no separators.
  - There are 2 types of devices, normal units and VRF units.
  - The communication to a device requires a device MAC (device to control) and a controller MAC (device responsible to manage the target device)
  - For normal units both MACs are usually the same
  - For VRF units, behavior changes depending on protocol
    - Local (UDP): 
      - Device MAC: is a 12 chars MAC with 2 chars at the end, so not a normal MAC, obtained via discovery
      - Controller MAC: is a 12 chars MAC
    - Cloud (MQTT):
      - Device MAC: is a 12 chars MAC with 2 chars at the end, so not a normal MAC, obtained via discovery
      - Controller MAC: is the first 12 chars of Device MAC
- Encryption version 2 is only used locally, for MQTT use always v1

## 6. Config entry shape

Version is `CURRENT_CONF_VERSION` in `const.py` (3 at the time of writing). One entry is a hub. A local only entry has `unique_id` `local_only`.

Example, shortened:

```json
{
  "cloud": null,
  "devices": {
    "<mac>": {
      "connection": {
        "local": {
          "mac_controller_local": "<mac>",
          "host": "192.168.x.x",
          "port": 7000,
          "timeout": 10,
          "encryption_version": "1",
          "max_online_attempts": 3
        },
        "cloud": { "prefer_cloud": false, "mac_controller_cloud": "" },
        "scan_interval": 60,
        "disable_available_check": false,
        "encryption_key": "<redacted>",
        "uid": 0
      },
      "options": { "name": "<name>", "features": ["beeper"], "restore_states": true }
    }
  }
}
```

If you change this shape, bump `CURRENT_CONF_VERSION` in `const.py`. There is no migration code yet. Home Assistant will refuse to load older entries after a bump unless you add `async_migrate_entry` in `__init__.py`.

## 7. Working on the code

Use the devcontainer. `CONTRIBUTING.md` has the steps. Inside it, VS Code tasks do the work:

- `Run Home Assistant`: starts HA with this component. Restart it after every code change.
- `Ruff: check`, `Ruff: format`, `Pylint`, `Mypy`: run all of them before a PR. The configs match HA core.
- `HA: Check config`, `HA: Compile translations`.

There is no unit test suite. Testing means running Home Assistant against a device. If you do not have a device, say so in the PR. A fake device that speaks the UDP protocol is the best way to test failure paths without touching real hardware.

Debug logs:

```yaml
logger:
  logs:
    custom_components.gree_custom: debug
```

Inside HA the logger name is `custom_components.gree_custom.*`. If you import `aiogree` directly in a script, the logger name is different.

## 8. Secrets in logs

Never log an encryption key, cloud password or token in clear text.

- Use `redact_str()` from `aiogree/helpers.py` for single values.
- Use `async_redact_data()` with `encryption_key` and `password` for dicts. `__init__.py`, `config_flow.py` and `diagnostics.py` already do this. Follow the same pattern.
- Do not add new `_LOGGER` lines that print packs before redaction.

## 9. Translations

- `translations/` holds files that ship. Only edit these when you change the flow or an entity name, and keep `en.json` complete.
- `translation-to-review/` holds files that are not checked yet. Do not move a file out of it unless a native speaker reviewed it.

## 10. Versions and releases

- The version lives in `manifest.json` and nowhere else.
- The maintainers own the version. Releases are cut with the workflows in `.github/workflows/`, which bump `manifest.json` and publish the release. Do not change the version in a normal PR unless a maintainer asks for it.
- Pre-release versions look like `4.0.0-alpha.105`. They are not tags or GitHub releases, so an exact pre-release cannot always be checked out again later.

## 11. Writing rules

These apply to everything you produce in this repo.

- English for all output: code, comments, docstrings, docs, commit messages, PR titles and PR descriptions.
- Chat with the user can follow the user's own language.
- Plain and simple English. No vague or padded text. Say what it is and stop.
- Sentence structure at B2 level or lower. Word choice at B1 level or lower. Technical terms are fine when there is no simpler word.
- Do not use em dashes.
- Match the style of the code around you. Do not reformat lines you did not need to touch.
- Do not mention AI tools in commits, PRs or branch names.

## 12. Before you open a PR

- [ ] Ruff, Pylint and Mypy pass.
- [ ] Both encryption versions are covered by your reasoning if you touched keys, ciphers or transports.
- [ ] No new secret can reach a log line.
- [ ] You tested against a real device, or you said in the PR that you could not.
- [ ] `en.json` is complete if you changed the flow or entity names.
- [ ] Docs in the repo root are updated if behavior changed.
