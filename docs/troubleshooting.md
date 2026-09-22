# Troubleshooting

## Time out and cannot connect errors

Due to the many issues being created revolving "TimeOut"/"Cannot connect" errors, I will be closing these. Feel free to make a PR fixing your TimeOut/Cannot connect error.
More information on the "why" can be found here: https://github.com/RobHofmann/HomeAssistant-GreeClimateComponent/issues/405#issuecomment-4300110823

In short: a time out means the device did not answer a UDP packet. In almost every case the cause is in the network or on the device, not in the integration. The checks below find most of them.

1. **Can Home Assistant reach the device?** Ping the IP from the Home Assistant host. A device that does not answer a ping is asleep, on another network, or has a new IP.
2. **Is UDP port 7000 open on the way?** Devices on another VLAN need a firewall rule that allows UDP 7000 from Home Assistant to the device. See [Local discovery](configuration.md#local-discovery).
3. **Does the device still have the same IP?** Give it a fixed IP in your router. The integration updates the IP by itself after a DHCP change, but only when it can reach the device with a broadcast. See [Automatic IP updates](configuration.md#automatic-ip-updates).
4. **Is something else talking to the device?** Two clients that bind to one unit fight over the session key. Stop other integrations, bridges or scripts that use the same device.
5. **Does the device answer the app?** If the Gree app cannot control the device locally either, the device or its Wi-Fi module is the problem.
6. **Does the device refuse the key exchange?** Then the error is **Unable to bind the device**, not a time out. See [encryption-key.md](encryption-key.md).

When Home Assistant runs in a Docker container on a bridge network, the discovery broadcast stays inside that network. Use host networking, or add the device IP under **Extra Hosts**, which sends a unicast packet instead.

## Enable debug logging

Debug logs show every packet in both directions, with the keys redacted. Turn them on before you reproduce a problem.

In the UI: open the integration under **Settings** > **Devices & Services**, click the three dots and choose **Enable debug logging**. Reproduce the problem, then choose **Disable debug logging**. Home Assistant then downloads the log.

Or in `configuration.yaml`:

```yaml
logger:
  default: error
  logs:
    custom_components.gree_custom: debug
```

Debug level writes about 50 lines a minute per device. Turn it off when you are done.

## Repair issues

The integration raises repair issues under **Settings** > **System** > **Repairs**.

| Issue | Meaning | What to do |
|---|---|---|
| Device connection failed | The device did not answer during setup of the entry. | Work through the time out checks above. The issue clears when the device answers again. |
| YAML import failed | An item in the `gree_custom:` block could not be imported. The text says why. | Fix the YAML and restart. Common causes: a device that is already in another entry, a wrong MAC, a failed cloud login. |
| Reauthentication required | The device refused the key exchange, or the cloud session is no longer valid. | For a cloud account, log in again. For a local device, check the key. See [encryption-key.md](encryption-key.md). |

## Messages in the setup flow

| Message | Meaning |
|---|---|
| Unable to connect to the device | No answer on UDP 7000. See the time out checks. |
| Unable to bind the device | The device answered but refused the key exchange, or no encryption version worked. See [encryption-key.md](encryption-key.md). |
| No new devices discovered | Every device that was found is already configured, or nothing answered the broadcast. Add the device IP under **Extra Hosts**. |
| A device with this MAC address is already configured | The device is in another entry. Remove it there first, or reconfigure that entry. |
| Login failed | Wrong email, password or region for the Gree account. |
| Invalid CIDR, Invalid IP address, Network exceeds the maximum | A value in the local discovery options is wrong or too large. See [Local discovery](configuration.md#local-discovery). |

## Common situations

**Entities go unavailable now and then.** One missed poll makes the entities unavailable until the next good poll. A device with a weak Wi-Fi signal does this often. Move the device or the access point, raise **Max Connection Attempts**, or turn on **Disable Available Check** to keep stale values instead. See [Availability](entities.md#availability).

**A switch is unavailable.** Many features only exist in some HVAC modes. X-Fan needs Cool or Dry, Power Save needs Cool, Smart Heat 8°C needs Heat, Sleep needs Cool or Heat, Humidity Control needs Cool or Dry. See [entities.md](entities.md#switches).

**The unit ignores Turbo or Quiet.** The unit does that while Power Save or Smart Heat 8°C is on. Turn those off first.

**A feature I expect is missing.** The device did not answer the property behind it at setup, or the feature is not enabled. Reconfigure the entry and check **Device Features and Modes**. Use the `get_prop_values` action to see what the device answers. See [actions.md](actions.md).

**The unit shows only default values, or every entity has the same value after every restart.** Some firmwares refuse a status request with too many columns. The integration measures the limit right after it binds and stays below it, so this should not happen. If it does, run `tools/probe_status_limit.py --host <ip>` from a checkout of the repo. Attach the output to an issue. See [development.md](development.md#tools).

**Changes made in the UI are undone after a restart.** The entry is managed by the `gree_custom:` block in `configuration.yaml`. The YAML wins at every start. Change the YAML instead, or remove the block to manage the entry in the UI. See [YAML configuration](configuration.md#yaml-configuration).

**The Gree app logs me out.** Gree allows one session per account. Every login by the integration ends the app session. The integration logs in at setup, when the cloud block in the YAML changes, and when you reauthenticate. Not at every restart.

**The device is on another VLAN and is not found.** Broadcasts do not cross VLANs. Add the network or the IP under **Extra Networks** or **Extra Hosts**, and allow UDP 7000 in the firewall.

**Two Gree integrations show up.** Home Assistant ships its own `gree` integration. This one is called **Gree Climate** in the setup dialog and has the domain `gree_custom`. Both can be installed, but do not add the same device to both.

## How to report a bug

Time out and cannot connect reports are closed, see the top of this page. For everything else, open an issue with:

1. The device brand, model and firmware version. The firmware is on the device page in Home Assistant.
2. The Home Assistant version and the integration version, from HACS or `manifest.json`.
3. Whether the device is controlled locally or through the cloud.
4. What you did, what you expected, and what happened.
5. The diagnostics download of the config entry or the device. See [actions.md](actions.md#diagnostics-download). Keys and passwords are redacted for you.
6. A debug log of the moment the problem happened. See [Enable debug logging](#enable-debug-logging). Remove anything personal before you paste it.

A report without a log usually gets a request for one first, which costs a round trip.

## Reporting a working device

If your unit works, add it to [supported-devices.md](../supported-devices.md) with a pull request. Or open an issue with the brand, model, encryption version and anything special you had to do.
