# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Custom Home Assistant integration for controlling Gree-compatible air conditioners over the local network via UDP (port 7000). Distributed through HACS. Domain: `gree`, version 3.3.2.

**Dependencies**: `pycryptodome` (AES encryption), `aiofiles` (async file I/O)

## Development Notes

- **No build system, test suite, or linting configuration exists.** There is no setup.py, pyproject.toml, pytest, flake8, or similar tooling.
- All code lives under `custom_components/gree/`. There are no other source directories.
- To test changes, copy `custom_components/gree/` into a Home Assistant installation's `custom_components/` directory and restart HA.

## Architecture

### Data Flow

```
HA UI action → Entity method → GreeClimate.SendStateToAc()
    → AES encrypt → UDP packet to device:7000 → device response
    → AES decrypt → update _acOptions dict → update HA entity state

Polling: every 60s via async_update() → GreeGetValues()
```

### Key Files

| File | Purpose |
|---|---|
| `__init__.py` | Integration setup, YAML config schema, platform forwarding (climate/switch/number/select/sensor) |
| `climate.py` | **Core file (912 lines)**. `GreeClimate(ClimateEntity)` — HVAC control, state polling, temperature handling, all AC commands |
| `gree_protocol.py` | UDP communication, AES encryption (v1=ECB, v2=GCM), device discovery, key negotiation, retry logic (8 attempts with backoff) |
| `config_flow.py` | UI config flow: discovery → encryption detection → device setup. Also handles options flow for runtime reconfiguration |
| `const.py` | Protocol constants, mode mappings (Gree protocol values ↔ HA values), config option keys |
| `helpers.py` | Temperature math: 0.5°C precision encoding (SetTem/TemRec), °F↔°C conversion, ±40°C sensor offset auto-detection (`TempOffsetResolver`) |
| `entity.py` | `GreeEntity` base class, `GreeEntityDescription` dataclass |
| `switch.py` | 12 toggle entities (x-fan, lights, health, sleep, power save, etc.) |
| `sensor.py` | Outside temperature and room humidity sensors |
| `number.py` | Target temperature step configuration entity |
| `select.py` | External temperature sensor selection entity |

### Encryption Protocol

Two encryption versions exist:
- **v1**: AES-128 ECB with generic key `a3K8Bx%2r8Y7#xDh`
- **v2**: AES-128 GCM with device-specific key, fixed IV and AAD

Encryption version is auto-detected during setup. The device key is retrieved via a handshake in `GetDeviceKey()`/`GetDeviceKeyGCM()`.

### Temperature Handling

The AC uses integer `SetTem` plus a `TemRec` bit for 0.5°C precision. Some devices report sensor temps with a +40°C offset. `TempOffsetResolver` auto-detects which mode the device uses based on observed temperature history. Fahrenheit support uses custom conversion functions (not simple formulas) due to protocol quirks.

### Device State

`GreeClimate._acOptions` dict tracks 19+ device properties: `Pow`, `Mod`, `SetTem`, `WdSpd`, `Air`, `Blo`, `Health`, `SwhSlp`, `Lig`, `SwUpDn`, `SwingLfRig`, `Quiet`, `Tur`, `StHt`, `TemUn`, `HeatCoolType`, `TemRec`, `SvSt`, `SlpMod`, and optionally `AntiDirectBlow`, `LigSen`, `OutEnvTem`, `TemSen`, `Buzzer_ON_OFF`.

### Configuration

Two config methods: UI config flow (recommended, with auto-discovery) and YAML import. See `manual-configuration.yaml` for YAML reference. Options flow allows runtime changes to available modes and sensor offset.

### VRF Support

VRF (Variable Refrigerant Flow) sub-units are addressed via MAC format `subMAC@mainMAC` and discovered through `get_subunits_list()`.

### Version 5 (gree_custom) and going back

Version 5 uses the domain `gree_custom` and moves the entity rows and device row of each entry of this version to its own entry, then disables the old entry. `async_setup` decides once whether `gree_custom` is installed and stores the answer in `hass.data[DOMAIN]["_successor_installed"]`.

- Installed: `_start_successor()` starts `gree_custom`, because after a HACS update it has no config entry or YAML key yet. `async_setup_entry` refuses (`ConfigEntryError`) an entry that still holds a migration record, so a re-enabled old entry does not give duplicate entities and a second client on the same unit.
- Not installed: `_async_go_back_from_successor()` runs inside `async_setup`, before any entry sets up its platforms. It reads the record version 5 left in the entry options, moves the entities back first (moving a device removes the entities of its old entry), creates the rows that version 5 removed again with their old entity ID, then moves the device, removes the record and enables the entry in a task. Entities of version 5 with no counterpart here are removed by Home Assistant when the device moves.

The record contract, written by version 5 under the options key `gree_custom_migration`:

```
{"version": 1,
 "entities": {"<entity_id>": "<old unique_id under platform gree>"},
 "devices": {"<device registry id>": [["gree", "<identifier value>"], ...]}}
```

`entities` are the rows moved to platform `gree_custom`. `devices` are the device rows moved to the `gree_custom` entry, with their identifiers from before the move. Only version 1 is read; change the version when the shape changes.
