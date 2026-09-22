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

The config entries of 4.x are not compatible with this version and there is no migration. To move:

1. Note your device settings, so you can enter them again.
2. Remove the old Gree entries under **Settings** > **Devices & Services**.
3. Remove the old `custom_components/gree` folder.
4. Install this version and set it up again. See [configuration.md](configuration.md).

Entity IDs change too, because the new entities belong to a new integration. Check your automations, scripts and dashboards after the move.

## Next step

Set the integration up: [configuration.md](configuration.md).
