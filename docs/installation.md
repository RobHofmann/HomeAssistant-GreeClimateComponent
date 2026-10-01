# Installation

## Requirements

- Home Assistant 2026.3 or newer. This release was the first that runs on Python 3.14, which the code needs.
- A Gree device that speaks the Gree protocol. Many brands use it. See [supported devices](../supported-devices.md) for units that are known to work.
- For local control: the device and Home Assistant on the same network, or a route between them that allows UDP port 7000.
- For cloud control: a Gree account with the device bound to it.

## HACS (recommended)

The integration is in the HACS default repository list.

1. Open HACS in Home Assistant.
2. Search for **Gree** and open the **Gree A/C** integration.
3. Click **Download**.
4. Restart Home Assistant.

HACS also offers updates when a new version is published.

## Manual

1. Download the repository.
2. Copy the folder `custom_components/gree_custom` into the `custom_components` folder of your Home Assistant config directory. Create `custom_components` if it does not exist.
3. Restart Home Assistant.

The folder name must stay `gree_custom`. Home Assistant matches the folder name with the `domain` in `manifest.json` and refuses to load the integration when they differ.

## Setting up the device Wi-Fi

The device must be on your Wi-Fi network before Home Assistant can find it. The normal way is one of the official apps:

- [Gree+ Android App](https://play.google.com/store/apps/details?id=com.gree.greeplus)
- [Gree+ iOS App](https://apps.apple.com/app/gree/id1167857672)
- [EWPE Smart Android App](https://play.google.com/store/apps/details?id=com.gree.ewpesmart)
- [EWPE Smart iOS App](https://apps.apple.com/app/ewpe-smart/id1189467454)

To set up the Wi-Fi without an app, see the guide in [gree-hvac-mqtt-bridge](https://github.com/arthurkrupa/gree-hvac-mqtt-bridge#configuring-hvac-wifi).

## Coming from a 4.x release

Releases 4.x used the domain `gree`. This version uses the domain `gree_custom`, because Home Assistant ships its own `gree` integration and the two cannot share a name.

Your devices move to this version by themselves. Their entity IDs, areas, names and history stay, so your automations, scripts and dashboards keep working.

1. Update through HACS and restart Home Assistant.
2. The devices move at that start. If you came from a 4.x release older than the last one, nothing happens yet. Then go to **Settings** > **Devices & Services** > **Add Integration**, pick **Gree A/C**, and the move starts. You do not have to fill in anything.
3. HACS leaves the old `custom_components/gree` folder in place. A repair issue asks you to delete it. Delete the folder and restart. The old 4.x entries stay, disabled, so you can go back to 4.x. A second repair issue, **Remove the old Gree 4.x config entries**, lets you remove them when you are sure you will not go back.
4. If you used a `gree:` block in `configuration.yaml`, it keeps working for now. A repair issue shows the `gree_custom:` block that replaces it. See [Legacy gree: block](configuration.md#legacy-gree-block).

What changes:

- The number entity for the temperature step and the selects for the external sensors are gone. Their values become the options **Temperature Step**, **External Temperature Sensor** and **External Humidity Sensor**.
- Switches for features your unit does not have are removed. 4.x created them for every unit.
- `temp_sensor_offset` is gone. This version detects the offset itself.
- The swing modes have other names. The migration picks the name that moves the louvers to the same position as before.
- New entities, such as the indoor temperature sensor, get new entity IDs.

## Going back to 4.x

You can go back to 4.x without setting it up again, and keep your entity IDs, areas and device names. This needs **4.0.12 or later**. Older 4.x releases do not move your devices back.

1. In HACS, install 4.0.12 or later of the 4.x line.
2. Delete the folder `custom_components/gree_custom`. HACS leaves it in place.
3. If you have a `gree_custom:` block in `configuration.yaml`, comment it out.
4. If you had a `gree:` block, un-comment it. Otherwise go to **Settings** > **Devices & services**, and enable one of the disabled Gree 4.x entries. Until the restart in the next step, that entry shows an error that this version is still installed. That is expected.
5. Restart Home Assistant.

4.x then moves your devices and entities back and enables its entries.

Good to know:

- If you removed the old 4.x entries through the repair issue, they cannot come back. Then you set 4.x up again.
- If you moved to this version with an early alpha, your devices are not moved back.
- Switches that this version removed come back with 4.x.
- Entities that only exist in this version are removed. They come back when you install this version again.
- If you install this version again later, your devices move again, like the first time.

## Next step

Set the integration up: [configuration.md](configuration.md).
