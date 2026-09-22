# Actions and diagnostics

## Actions

The integration provides two actions, called services in older Home Assistant versions. Both read raw properties from a device and return the answer. They change nothing on the device. Use them under **Developer tools** > **Actions**, or in a script.

A property is one named value in the Gree protocol, such as `Pow` for power or `SetTem` for the target temperature. The device decides which properties it knows.

### `gree_custom.get_prop_values`

Reads the properties you name.

| Field | Meaning |
|---|---|
| `device_id` | The Home Assistant device. Pick it in the UI, or use the device ID from the device page URL. |
| `prop_list` | A list of property names. |

Example:

```yaml
action: gree_custom.get_prop_values
data:
  device_id: 1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d
  prop_list:
    - Pow
    - Mod
    - SetTem
```

### `gree_custom.get_prop_values_all`

Reads every property the integration knows, one request per property. That is about 300 requests, so it takes a few minutes. A property the device never answers costs one timeout. The action stops early when five requests in a row get no answer, which means the device stopped talking.

```yaml
action: gree_custom.get_prop_values_all
data:
  device_id: 1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d
```

### The response

Both actions return a response, so use `response_variable` in a script.

```yaml
states:
  Pow: "1"
  Mod: "1"
  SetTem: "22"
missing:
  - ElcDatDte
```

`states` holds the values the device returned, as strings. `missing` lists the properties you asked for but did not get back. That happens when the device does not support the property, or when it does not answer at all.

### Errors

- **An invalid device was selected.** The device ID is not a Gree device of this integration.
- **The configuration entry for the device is not loaded.** The entry is disabled or failed to start. Look at the repair issues and the log.

## Diagnostics download

Every config entry and every device has a **Download diagnostics** item in its three dot menu. The download is a JSON file with the configuration and the last known state of each device. Keys and passwords are redacted.

The device diagnostics also list the properties the integration polls and the values the device sent that the integration does not know. Attach the file to a bug report. See [troubleshooting.md](troubleshooting.md#how-to-report-a-bug).
