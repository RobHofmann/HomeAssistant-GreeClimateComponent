# Configuration

You can set the integration up in the UI or in YAML. The UI is the normal way. YAML is for people who keep their whole configuration in files.

## UI setup

1. Go to **Settings** > **Devices & Services** and click **Add Integration**.
2. Search for **Gree Climate**.
3. Pick one or both discovery methods: **Local network** and **Gree Cloud account**. See [connection-methods.md](connection-methods.md) for what each one means.
4. Fill in the cloud login, the local discovery options, or both.
5. Pick the devices to add from the list of discovered devices.
6. For every device, fill in the connection options and then the device features.

The steps are described below in the order they appear.

### Gree account

Shown when you picked the cloud method.

| Field | Meaning |
|---|---|
| Email, Password | Your Gree account. |
| Region | The region of your account. The integration uses it to pick the right Gree server. |

The login returns a session token. The integration stores the token in the config entry and uses it every time the entry loads. A restart or a reload does not log in again. Only when the stored token stops working does the entry ask for [reauthentication](#reauthentication), which logs in once more and stores the new token.

This matters because Gree allows one session per account. Every login ends the other sessions, so the Gree app on your phone logs out at that moment. A YAML entry works the same way: a matching entry keeps its token, and a changed email, region or password triggers a new login.

### Local discovery

Shown when you picked the local method. The integration sends a discovery broadcast on every network Home Assistant is connected to. Routers do not forward broadcasts between VLANs, so devices on another subnet are not found that way. For those, fill in one or both of:

| Field | Meaning |
|---|---|
| Extra Networks | Networks in CIDR notation, comma separated. Example: `192.168.20.0/24, 192.168.30.0/24`. |
| Extra Hosts | Single IP addresses, comma separated. Example: `192.168.30.50, 192.168.30.51`. |

Every address is probed with one UDP packet to port 7000. Routing and firewall rules must allow UDP port 7000 from Home Assistant to that subnet.

Limits: one network, and the total of all networks and hosts, may hold at most 65536 addresses, which is a `/16`. Larger ranges must be split or replaced by hosts. A whole `/16` sends tens of thousands of packets and can stress a home router, so use the smallest range you can.

The values you enter are remembered and offered again in the next setup flow.

### Discovered devices

The list holds every device that was found and is not configured yet. Pick the ones to add.

> [!WARNING]
> When you are reconfiguring, the devices you do not pick are removed from the entry.

With a cloud account, the list holds the devices of the account. It shows whether each one was also found on the local network.

### Connection options

One page per device. The integration binds to the device when you click submit. A wrong value shows up right away as **Unable to connect to the device** or **Unable to bind the device**.

| Field | Default | Meaning |
|---|---|---|
| Scan Interval | 60 | Seconds between two polls of the device. Minimum 5. |
| Disable Available Check | off | When on, the entities never become unavailable. See [Availability](entities.md#availability). |
| Encryption Key | empty | Leave empty. The integration gets the key from the device or the cloud. Fill it in only when that fails. See [encryption-key.md](encryption-key.md). |
| User ID | 0 | The `uid` of the device owner. 0 works for most devices. |

Local connection settings:

| Field | Default | Meaning |
|---|---|---|
| IP Address | the discovered IP | Where the device answers. |
| Port | 7000 | The UDP port. Every known unit uses 7000. |
| Connection Timeout | 10 | Seconds to wait for one answer. |
| Max Connection Attempts | 3 | How often one request is retried before the poll counts as failed. |
| Encryption Version | Auto-Detect | V1 or V2. Leave on Auto-Detect unless you know the device needs one version. The detected version is stored after the first bind. |
| MAC of the local controller device | the discovered MAC | Only differs from the device MAC for VRF units. |

Cloud connection settings, shown when the device is in a cloud account:

| Field | Default | Meaning |
|---|---|---|
| Prefer Cloud Connection | off | Control the device through the cloud even when it answers locally. |
| MAC of the cloud controller device | the discovered MAC | Only differs from the device MAC for VRF units. |

### Device features

One page per device. Gree devices do not report reliably which features they have. The integration checks which properties the device answers and offers only those. You then choose what to enable, to the best of your knowledge of the unit.

| Field | Default | Meaning |
|---|---|---|
| Device Name | the name the unit reports | The name of the device in Home Assistant. By default Home Assistant also uses it in the entity IDs. |
| HVAC Modes | all | The modes the climate entity offers: Auto, Cool, Dry, Fan only, Heat, Off. |
| Fan Speeds | all the unit supports | Auto, Low, Medium-Low, Medium, Medium-High, High, and Turbo and Quiet when the unit has them. |
| Vertical Swing Modes | all | The vertical positions and swing ranges. |
| Horizontal Swing Modes | all | The horizontal positions and swing ranges. Only shown when the unit has horizontal swing. |
| Device Features and Modes | all the unit supports | Which switches and selects to create. See [entities.md](entities.md). |
| Temperature Step | 1 | The step of the target temperature, 0.5 to 5 in steps of 0.5. In Fahrenheit the step is rounded to a whole degree. |
| External Temperature Sensor | none | A Home Assistant sensor that replaces the unit's own room temperature in the climate entity. |
| External Humidity Sensor | none | A Home Assistant sensor that replaces the unit's own humidity in the climate entity. |
| Restore Entities | on | After a restart, send the last known Home Assistant state to the device instead of taking over the device state. See [Restoring state](entities.md#restoring-state-after-a-restart). |

The external sensors only change what the climate entity shows. The unit keeps using its own sensor to regulate.

## Reconfigure

Open the entry under **Settings** > **Devices & Services**, click the three dots and choose **Reconfigure**. The flow runs again with your current values filled in. Saving reloads the entry, so the change works right away without a restart.

- On the **Local-only Devices** entry the flow starts at local discovery.
- On an account entry the flow first asks whether to also look for local devices. The account itself cannot be removed from the entry. To make a device local-only, remove it from the account entry and add it again with the local method.

> [!WARNING]
> Devices you do not pick in the device list are removed from the entry.

## Removing a device

Open the device page and choose **Delete** from the three dot menu. The device is removed from its entry. When the **Local-only Devices** entry becomes empty, the entry is removed too.

## Automatic IP updates

Two mechanisms keep the stored IP address current when a device gets a new one from DHCP:

- Home Assistant reports DHCP leases of Gree devices to the integration. When the MAC matches a configured device, the stored IP is updated and the entry is reloaded. This only updates known devices. It does not start a setup flow for new ones.
- When a poll fails, the integration runs a discovery, looks for the device MAC, and retries once with the new IP.

Both need the device to be on a network that Home Assistant can reach with a broadcast. Give the device a fixed IP when it is on another VLAN.

## Reauthentication

A cloud account entry asks for a new login when the stored session stops working. Click **Reconfigure** on the repair, or open the entry and choose **Reauthenticate**, and enter the account details again.

## YAML configuration

You can set the integration up in `configuration.yaml` instead of the UI. Minimal example with one local device:

```yaml
gree_custom:
  - devices:
      "20-FA-BB-12-34-56":
        connection:
          local:
            host: "192.168.1.100"
        options:
          name: "Gree AC"
```

[`manual-configuration.yaml`](../manual-configuration.yaml) in the repo root lists every option with its type, its default and a comment.

How the YAML is applied:

- Home Assistant reads the YAML at every start. It creates the config entry when it is missing and updates it when the YAML changed. An unchanged YAML causes no reload.
- Every item in the list is one config entry. An item with a `cloud` block is the entry for that Gree account. The one item without a `cloud` block is the entry for all local-only devices.
- A device you remove from the YAML is removed from the entry, together with its device registry rows.
- Do not change a YAML managed entry in the UI. The next restart puts the YAML values back. That includes the IP address. An IP found by discovery is replaced by the `host` in the YAML at the next start. Keep the YAML current, or give the unit a fixed IP.
- A device that is already in another entry is skipped, with an error in the log and a repair issue.
- A `cloud` block logs in to the Gree account only on the first import, and again when you change the email, region or password. An unchanged `cloud` block reuses the stored session. Every login logs the Gree app out.

### Legacy gree: block

The `gree:` block of release 4.x still works, only to make the move easy. At every start the integration converts it to the format above and imports it. It raises a repair issue that shows the `gree_custom:` block to use instead, and it writes a warning to the log.

The legacy import will be removed in a later version. Update your configuration now:

1. Open the repair issue under **Settings** > **System** > **Repairs**.
2. Copy the block and replace the `gree:` block with it. If you already have a `gree_custom:` block, add the devices under its `devices:` instead.
3. Restart Home Assistant. The entry does not change and the repair issue goes away.

The block also holds the devices you set up in the UI of 4.x, when a YAML block manages the local devices. Otherwise those devices would only be kept by the old 4.x entries.

### Device keys and MAC addresses

The key of every device is its MAC address. Write it in lower case without separators. Upper case and `:` or `-` separators are accepted and cleaned up.

- A normal unit has a MAC of 12 characters. The controller MACs default to the same value.
- A VRF unit has a MAC of 14 characters. Write it as `<mac>@<controller mac>`, so the integration knows the local controller. Or set `mac_controller_local` in the local connection block. A VRF unit without either is refused.

### Options that differ from the UI defaults

- `features` left out means every feature except `humidity_control`. In the UI the default is every feature the unit supports. Write the list yourself when you want humidity control.
- `fan_modes` left out means every speed except `turbo` and `quiet`.
- `hvac_modes`, `swing_modes` and `swing_horizontal_modes` left out mean all options.
- `encryption_version` left out means `"0"`, auto detect. Because the import does not bind the device, the version is detected at every start. That is fine.
