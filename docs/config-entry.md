# Config entry

One config entry is a hub. There is one entry per Gree Cloud account, plus one entry for all local-only devices. The local-only entry has `unique_id` `local_only`.

The entry version is `CURRENT_CONF_VERSION` in `const.py` (3 at the time of writing).

## Shape

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

For a cloud entry, `cloud` holds the account email, region, user id and token. The key names are in `const.py` (`CONF_CLOUD`, `CONF_EMAIL`, `CONF_REGION`, `CONF_UID`, `CONF_TOKEN`).

## Fields

| Field | Meaning |
|---|---|
| `connection.local.mac_controller_local` | MAC of the unit that answers UDP. The device MAC for a normal unit, the gateway MAC for a VRF sub-unit. Every distinct gateway MAC with a sub-unit gets a controller device without config of its own, see [architecture.md](architecture.md#vrf-controller-device). |
| `connection.local.host`, `port` | Where the unit answers UDP. Port is 7000 for every known unit. |
| `connection.local.timeout` | Seconds to wait for one UDP reply. |
| `connection.local.encryption_version` | `"0"` auto, `"1"` ECB, `"2"` GCM. After a successful bind the detected version is written back here. |
| `connection.local.max_online_attempts` | How many times one UDP request is retried. Not how many polls may fail in a row. |
| `connection.cloud.prefer_cloud` | Use MQTT even when a local transport is available. |
| `connection.scan_interval` | Poll interval in seconds. Minimum is `MIN_SCAN_INTERVAL`. |
| `connection.disable_available_check` | When true, entities never go unavailable. |
| `connection.encryption_key` | The device key from the last bind. Empty means "fetch it". Redacted in logs and diagnostics. |
| `connection.uid` | User id sent in every pack. 0 for local. |
| `options.name` | Device name in Home Assistant. Defaults to the name the unit reports, which is usually the tail of its MAC. |
| `options.features` | Which optional switches to create. Only features the unit reported as supported are offered. |
| `options.restore_states` | Restore the last known entity states after a restart. |

## YAML import

An entry can also come from `configuration.yaml`. The parts:

- `config_schema.py` holds `CONFIG_SCHEMA`. It validates the `gree_custom:` block, normalizes the MAC addresses and fills the defaults, so an imported item already has the shape above. The device key goes through `gree_extract_macs()`, the same function discovery uses, so the controller MACs default the way discovery sets them: the device MAC for a normal unit, the first 12 characters for a VRF main device MAC that ends in `00`, and the part after `@` for a key written as `<mac>@<controller mac>`. A VRF sub-device key without `@` has no known local controller, so the schema requires `mac_controller_local` for it (see [protocol.md](protocol.md#mac-addresses)). `__init__.py` imports `CONFIG_SCHEMA` so Home Assistant and hassfest find it.
- `async_setup` in `__init__.py` starts one import flow per item in the list.
- `async_step_import` in `config_flow.py` resolves the target entry. Without a `cloud` block that is the local-only entry (`unique_id` `local_only`). With a `cloud` block it first looks for an entry that already stores the same email, region and password. If it finds one, it reuses that `unique_id` and the stored `uid` and `token`, so there is no cloud login on every restart. Only when there is no such entry does it log in and use the returned user id as `unique_id`. A login matters: Gree allows one session per account, so every login logs the Gree app out. It happens on the first import and after a change of email, region or password. A changed email still lands on the same entry, because the user id from the login is the `unique_id`.
- The step then creates the entry, or updates the existing one with `async_update_reload_and_abort`. Unchanged YAML changes nothing and causes no reload. Changed YAML updates the entry and reloads it once, after startup. A device that is already in another entry is skipped, with an error in the log and a repair issue (`yaml_import_failed`).
- Devices that are in the entry but not in the YAML are removed, together with their device registry rows.
- The step adds the `unique_id` to the set in `hass.data[DATA_YAML_UNIQUE_IDS]`, also when it aborts after the `unique_id` is known. Reconfigure refuses an entry in that set with `yaml_managed`. `entry.source` cannot tell this, because an import that updates a UI entry keeps the source `user`. The set lives in memory only, so after the YAML block is removed and Home Assistant restarts, the entry can be reconfigured again.

The YAML wins at every start, so values that change after the import are not preserved:

- `connection.local.host` updated by discovery goes back to the `host` in the YAML at the next start. Keep the YAML current, or give the unit a fixed IP.
- The import does not bind the device, so it stores the `encryption_key` and `encryption_version` as written. With a blank key and version `"0"`, entry setup fetches the key and detects the version on every start. That is the normal path.
- Changes made in the UI to a YAML managed entry are replaced by the YAML values at the next start.

## Reconfigure

`async_step_reconfigure` in `config_flow.py` shows a menu, and every reconfigure step returns to it. The flow copies the entry devices deep into `_pending_devices` (MAC to `connection` and `options`). The menu steps change that copy, and only `finish` writes it with `_async_finish`, which reloads the entry once.

- `edit_device` runs the normal `connection_options` and `device_options` steps for one device. When the submitted settings that decide the bind (`_bind_settings()`: key, uid, controller MACs, host, port, encryption version, `prefer_cloud`) equal the stored ones, and the entry is loaded with that device bound, the flow uses the running `GreeDevice` from `entry.runtime_data` and does not bind. Otherwise it binds. A cloud bind uses a `GreeMqttTransport` built from the stored `token`, `uid` and `region` with `create_mqtt_transport()` in `helpers.py`, the same helper entry setup uses. There is no cloud login, unless the broker refuses the stored token. Then `_bind_device()` refreshes the token once, see [Token refresh](#token-refresh).
- `rediscover` runs `cloud_add` (with a login, because the cloud device list needs one), `local_add` and `device_picker`, as before. In reconfigure, `device_picker` first calls `_keep_new_rediscovered_devices()`. That keeps a device when it is not in `_pending_devices`, or when `_adds_connection()` is true: discovery found a host for a device without `local.host`, or a cloud controller for a device without `cloud.mac_controller_cloud`. The kept devices are all preselected. Every picked device goes through `connection_options` and `device_options`. For a configured device the forms start from the pending config, and `_apply_discovery_info()` fills in the found host and controller MACs. The other configured devices that discovery found get the found `local.host`, `local.mac_controller_local` and `cloud.mac_controller_cloud` from `_apply_discovery_info()` without a form, like the DHCP step. Rediscover never removes a device. When nothing is kept, the flow shows `no_new_devices`, a form without fields that returns to the menu, because an abort would drop the pending changes. Picking no device also returns to the menu.
- `remove_devices` removes the picked devices from the copy.
- When an edit changes `host`, `port` or `encryption_version` of a device with a `mac_controller_local`, the other devices with the same controller MAC get the same values.
- `_async_finish` removes the device registry rows of removed devices and moves local-only devices found in the cloud to the account entry, as before.

Reauth does not use the menu. It runs `cloud_add` and updates only the `cloud` block.

## Connection lifetime

Entry setup creates its own `GreeMqttTransport` and one `GreeUdpTransport` per local controller. A transport is never shared between entries, or between an entry and a config flow.

- `async_unload_entry` unloads the platforms, then shuts down every coordinator, which unbinds its device. Then it disconnects every distinct transport of the coordinators with `async_disconnect_transports()` in `helpers.py`. The last unbind on a transport normally disconnects it already. The explicit disconnect also covers an unbind that fails, for example after the broker dropped the connection.
- Home Assistant runs the coordinator shutdown again from the unload callbacks of the entry. `GreeCoordinator.async_shutdown()` only does its work on the first call.
- The config flow keeps its own transports in `_mqtt_transport` and `_local_transports`. `cloud_add` closes the earlier MQTT transport before it opens a new one. `_async_finish` closes all flow transports before it writes the entry. `async_remove()` closes them when the flow aborts or the user closes it. Home Assistant calls `async_remove()` for every flow that ends, see `_async_remove_flow_progress` in `data_entry_flow.py`.
- When the broker refuses the connection at entry setup (`MqttConnectError`), setup first tries one [token refresh](#token-refresh) if the reason is about the token. When that is not possible or does not help, setup logs the reason at warning level and raises `ConfigEntryAuthFailed`, which starts reauth.

### Token refresh

Sometimes the broker refuses a stored token with "Bad user name or password". Why Gree ends a token is not known. Seen so far: a token can stop working soon after the login that issued it, and the cloud may rate-limit logins. A cloud login ends the Gree app session, but an MQTT connection with an existing token does not. `is_mqtt_auth_refusal()` in `helpers.py` decides if an `MqttConnectError` is about the token. The transport uses MQTT 3.1.1, but paho 2 turns the 3.1.1 return codes 4 and 5 into the MQTT 5 reason codes 134 and 135 before aiomqtt puts them in `rc`. The helper accepts all four. Any other connect error keeps the old behaviour.

`async_refresh_cloud_token()` in `helpers.py` logs in with the stored `email`, `password` and `region` through `GreeCloudApi.login()`, and returns the cloud block with the new `token` and `uid`. It refuses a login that returns another `uid`. It logs a warning, because the login logs the Gree app out. Two callers use it, each at most once:

- `async_setup_entry` in `__init__.py`. On an auth refusal it calls `_async_refresh_entry_token()`, which stores the new block with `async_update_entry` right after the login. The login already made the old token invalid, so keeping it is never right. The integration has no update listener, and `async_update_entry` only saves and notifies (`_async_save_and_notify` in `config_entries.py`), so this does not reload. Setup then disconnects the old MQTT transport, builds a new one, and binds the device again over MQTT only, because its local transport already failed. Devices later in the setup use the new transport. A failed login, or a second refusal, raises `ConfigEntryAuthFailed` as before.
- `_bind_device()` in `config_flow.py`, during reconfigure, when this flow did not log in yet (`_cloud_token_fresh`). `_async_refresh_stored_token()` puts the new block in `_config_data[CONF_CLOUD]`, so `_async_finish` writes it, and replaces the flow MQTT transport. When the login fails, or the retry fails, the form shows `cannot_connect_mqtt`.

A YAML import copies the stored cloud block of the matching entry, so a refreshed token survives the next start.

## Migration from 4.x

Releases 4.x used the domain `gree` and a flat entry: one device per entry, all fields at the top level. `async_migrate_entry` cannot help here, because it only works inside one domain. `migration.py` moves a 4.x setup over in two phases instead.

### What starts it

Home Assistant only sets up an integration that has a config entry or a YAML key. After an update through HACS, `gree_custom` has neither. HACS also leaves the old `custom_components/gree` folder in place: it installs into the folder named after the new domain and only removes a folder on uninstall. So something else has to start `gree_custom` once:

- The last 4.x release calls `async_setup_component("gree_custom")` from its own `async_setup` when that integration is installed. This is the path without user action.
- Without that release, the setup flow starts it. `async_step_user` and `async_step_dhcp` call `async_setup_from_flow()`, which sets the integration up when it is not set up yet and 4.x entries exist. The flow then stops with `legacy_migration_started`. So a user who opens **Add Integration** > **Gree A/C** starts the migration with that one action.

After the first run `gree_custom` has its own entry and starts by itself.

### Phase 1, in `async_setup`

`async_prepare_legacy_migration()` reads the 4.x entries (domain `gree` with `mac` and `host` in the data, so the entries of the built-in `gree` integration are left alone) and the `gree:` block, if there is one. It merges the entry options over the data, like 4.x did, and converts every device with `convert_legacy_device()`:

| 4.x | Here |
|---|---|
| `name` | `options.name` |
| `mac`, with `:` and `-` removed | device key, `<mac>@<controller mac>` for VRF |
| `host`, `port` | `connection.local.host`, `connection.local.port` |
| `encryption_version` 1 or 2 | `connection.local.encryption_version` `"1"` or `"2"`, kept so no detection is needed |
| `encryption_key`, `uid`, `disable_available_check` | `connection.*` |
| `hvac_modes`, `fan_modes` | the same names |
| `swing_modes`, `swing_horizontal_modes` | other names, matched on the value sent to the unit (4.x `swing_downmost` and 5.0 `swing_upper` both send 7) |
| `temp_sensor_offset` | dropped, the offset is detected here |
| state of the 4.x `target_temp_step` number and the two external sensor selects | `options.target_temp_step`, `options.external_temperature_sensor`, `options.external_humidity_sensor` |

A missing mode list counts as the 4.x default list, because 4.x used that list at runtime. Values that equal the defaults here are left out. A mode list that holds every mode is left out too, except `fan_modes`: the 4.x default holds `turbo` and `quiet`, the default here does not, so that list is written out. Every converted device then goes through `ITEM_SCHEMA`, so a device that is not valid here is skipped with an error in the log.

Then the devices come in one of two ways:

- When a YAML block manages the local devices (a `gree:` block, or a local item in `gree_custom:`), the devices are merged into the local YAML item and the YAML import handles them at every start. A device the user already wrote in `gree_custom:` wins. The repair issue `legacy_yaml` shows the `gree_custom:` block to paste, and a warning goes to the log at every start.
- Otherwise the `migrate` flow step adds them to the local-only entry. That step only adds devices and never removes one, and it skips devices that are already in another entry.

The repair issue `legacy_folder` is raised while `custom_components/gree` holds the 4.x component. The repair issue `legacy_entries` is described under phase 2. All three issues are checked at every start and removed when they no longer apply.

### Phase 2, in `async_setup_entry`

Before the platforms are set up, `async_migrate_legacy_registry()` handles every 4.x entry whose device is in this entry:

1. Unload the 4.x entry. A setup in progress is awaited first, because Home Assistant cannot unload it. The same unload also runs at the start of the entry setup, so the two clients do not talk to the unit at the same time. Then write the record of the rows that move into the options of the 4.x entry, see [The record for 4.x](#the-record-for-4x).
2. Move the entity rows with `async_update_entity_platform()`. The climate entity `gree_<mac>` becomes `<mac>_hvac`, `outside_temperature` becomes `outdoor_temperature`, the switches and `room_humidity` keep their key. The number and the two selects have no entity here and stay behind. Moving the row keeps the entity ID, so history, automations and dashboards keep working.
3. Move the device row with `async_update_device()`, so its area and user name stay. The entities have to move first: Home Assistant removes the entities of the old entry when their device moves.
4. Disable the 4.x entry, so 4.x does not load it or import it again. The entry is never removed here: it stays, so the user can go back to 4.x without setting it up again.

At the end of phase 2, and also at the end of phase 1, the repair issue `legacy_entries` is checked. It is raised when there is a 4.x entry that is disabled, whose device is in an entry of this integration, while the 4.x folder is gone and no `gree:` YAML device needs that entry (the MAC is not in `macs_needing_old_entry`). The issue is fixable: `repairs.py` shows a confirm step, and on submit `async_remove_legacy_entries()` checks the same rule again, folder included, and removes those entries. Removing an entry also removes the rows that did not move. An entry removed this way cannot come back, so going back to 4.x then means setting it up again.

After the platforms are set up, `async_remove_unprovided_entities()` removes the moved rows that got no entity, for a device that is bound. 4.x created every switch, also for features the unit does not have.

Everything is safe to run again. A row that already moved is not found under `gree` any more.

Limits:

- For a VRF unit only the climate entity moves. 4.x used the controller MAC in the unique IDs of all other entities, so the sub-devices cannot be told apart.
- Home Assistant writes the registries during startup with a delay of 180 seconds. If Home Assistant is killed before that, the next start moves the rows again, which gives the same result.

### The record for 4.x

Before the rows move, phase 2 writes a record into the options (not the data) of the 4.x entry, under the key `gree_custom_migration` (`LEGACY_RECORD_KEY`):

```json
{
  "version": 1,
  "entities": {"<entity_id>": "<old unique_id of that row under platform gree>"},
  "devices": {"<device registry id>": [["gree", "<identifier value>"]]}
}
```

- `entities` holds every row that this run moves with `async_update_entity_platform()`.
- `devices` holds the 4.x device row that moves, with its identifiers as they were before the move. The list is sorted.
- The record is merged with the one already there, so a row that was recorded before is never dropped. The 4.x entry is only updated when the record changed. Other option keys stay as they are.
- 4.x ignores option keys it does not know, so the record does no harm to an older 4.x release.

The record is a contract with 4.x 4.0.12 and later. Do not change its shape without a matching change in 4.x.

### Going back to 4.x

The 4.x release from 4.0.12 reads the record when `gree_custom` is not installed. For each recorded 4.x entry it:

1. Moves the recorded entity rows back to platform `gree`, with their old unique IDs.
2. Moves the device row back: its old identifiers and the 4.x entry. A device has one config entry, so the link to the `gree_custom` entry goes.
3. Clears the record and enables the entry.

Home Assistant only sets up `gree` when it has an enabled entry or a `gree:` YAML key. The 4.x entries are disabled, so the user starts it: enable one disabled 4.x entry, or un-comment the `gree:` block. The user steps are in [installation.md](installation.md#going-back-to-4x).

What to expect:

- Rows that this version removed, the switches a unit does not provide, are still in the record. 4.x creates their rows again with the old entity ID, so it does not give them a new one.
- While this integration is still loaded, 4.x refuses to set up an entry that holds a record (`ConfigEntryError`). Enabling an entry before the restart therefore shows that error until the restart.
- Home Assistant removes the entities that only exist in this version and are linked to a device that moves back, because their entry no longer owns the device.
- Installing this version again moves the rows again, the same as a first migration, and writes a new record.
- Entries removed through the `legacy_entries` repair cannot come back.
- A migration done by an older alpha wrote no record, so its rows are not moved back.

## Changing the shape

If you change this shape:

1. Bump `CURRENT_CONF_VERSION` in `const.py`.
2. Add `async_migrate_entry` in `__init__.py`. There is no migration code yet, and Home Assistant refuses to load an entry whose version is older than the flow's version unless that function exists.
3. Update the example above and `manual-configuration.yaml`.

## Discovery preferences

The extra networks and hosts entered in the local setup step are stored outside the entry, in `.storage/gree_custom_discovery_prefs`, so the next setup flow can offer them again.
