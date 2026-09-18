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

## Older entries

Releases 4.x used the domain `gree` and a flat entry: one device per entry, all fields at the top level. Those entries are not compatible with this shape and there is no migration. Users set the integration up again.

## Changing the shape

If you change this shape:

1. Bump `CURRENT_CONF_VERSION` in `const.py`.
2. Add `async_migrate_entry` in `__init__.py`. There is no migration code yet, and Home Assistant refuses to load an entry whose version is older than the flow's version unless that function exists.
3. Update the example above and `manual-configuration.yaml`.

## Discovery preferences

The extra networks and hosts entered in the local setup step are stored outside the entry, in `.storage/gree_custom_discovery_prefs`, so the next setup flow can offer them again.
