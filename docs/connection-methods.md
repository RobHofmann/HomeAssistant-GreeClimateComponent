# Connection methods

The integration can talk to a device in two ways.

- **Local.** UDP packets on port 7000, straight to the device on your network. This is the preferred way. It does not depend on the internet or on Gree's servers.
- **Cloud.** MQTT through Gree's servers, with the devices that are bound to your Gree account. This works when Home Assistant cannot reach the device on the network.

The cloud can also improve a local device. During setup it gives the device name and the encryption key, so the integration does not have to guess them.

## Config entries

The integration creates more than one config entry on purpose.

- One entry named **Local-only Devices** holds every device that is set up without a cloud account.
- One entry per Gree account holds the devices of that account, whether they are controlled locally or through the cloud.

A device can be in one entry only. Adding a device that is already configured is refused.

The device page under **Settings** > **Devices & Services** shows which connection a device uses.

## Local-only setup

Choose **Local network** as the discovery method. The integration sends a discovery broadcast on every network that Home Assistant is connected to. You can add more networks and single hosts, for devices on another subnet or VLAN. Those are probed one address at a time. See [Local discovery](configuration.md#local-discovery).

The list of found devices leaves out devices that are already configured. The devices you pick are added to the **Local-only Devices** entry.

## Cloud-only setup

Choose **Gree Cloud account** as the discovery method and log in. The integration lists the devices that are bound to the account. The devices you pick are added to the entry for that account and are controlled through MQTT.

If a device in the list is already configured as a local-only device, it is merged into the account entry. It then keeps local control and gains the cloud information.

Two things to know about the cloud:

- Gree allows one session per account. Every login from Home Assistant ends the other sessions, so the Gree app logs you out. The integration stores the session and logs in again only when it has to.
- Over the cloud the device always uses encryption version 1. The version setting in the local connection options does not apply.

## Mixed setup

Choose both methods. The integration lists the devices of the account and also runs local discovery. The list shows, for every cloud device, whether it was also found on the network.

A device that answers locally is controlled locally. The cloud is then used only to improve the discovered information, such as the device name. To control a device through the cloud anyway, turn on **Prefer Cloud Connection** in its cloud connection settings. See [Connection options](configuration.md#connection-options).

The devices you pick are added to the entry for the account.

## Which one to pick

- Device on the same network as Home Assistant: local.
- Device on another VLAN with a route that allows UDP 7000: local, with the extra networks or hosts.
- Device that Home Assistant cannot reach at all: cloud.
- Device that will not give its key locally: mixed. The cloud provides the key, control stays local. See [encryption-key.md](encryption-key.md).

## VRF units

A VRF system has one controller with several indoor units behind it. Local discovery finds the controller, asks it for its units, and lists the units. The controller itself is not listed.

A VRF unit has a MAC address of 14 characters. The controller has a normal MAC address of 12 characters. Both are filled in for you during discovery. In YAML you write the unit as `<mac>@<controller mac>`, or you set `mac_controller_local`. See [YAML configuration](configuration.md#yaml-configuration).
