[![HACS](https://img.shields.io/badge/HACS-Default-orange.svg)](https://hacs.xyz)
[![Home Assistant](https://img.shields.io/badge/Compatible-Home_Assistant_2026.3+-blue.svg)](https://www.home-assistant.io)

# HomeAssistant-GreeClimateComponent

Gree integration for Home Assistant written in Python 3.

The integration supports controlling Gree devices locally (preferred) and through the Gree cloud.
You can read more about that [below](#connection-methods-and-configuration).

For a comprehensive list of tested devices, see [Supported Devices](supported-devices.md).
Feel free to open a new issue reporting working or non working devices.

**If you are experiencing issues, please read the [Debugging](#debugging) section.**


Official mobile applications:
- [Gree+ Android App](https://play.google.com/store/apps/details?id=com.gree.greeplus)
- [Gree+ iOS App](https://apps.apple.com/app/gree/id1167857672)
- [EWPE Smart Android App](https://play.google.com/store/apps/details?id=com.gree.ewpesmart)
- [EWPE Smart iOS App](https://apps.apple.com/app/ewpe-smart/id1189467454)

To configure HVAC wifi (without the mobile app): https://github.com/arthurkrupa/gree-hvac-mqtt-bridge#configuring-hvac-wifi


## Installation

### HACS (recommended)

This integration is added to the HACS default repository list. Search for 'Gree' in the HACS dashboard to find and install it.

### Manual

Copy the `custom_components` folder to your own hassio `/config` folder.


## Configuration

### UI Configuration - Config Flow (recommended)

The integration can be added from the Home Assistant UI.

1. Navigate to **Settings** > **Devices & Services** and click **Add Integration**.
2. Search for **Gree Climate**
3. Choose Cloud and/or Local setup and fill in the requested details. See [more](#connection-methods-and-configuration) on how these work
4. After a successful discovery, you will be asked which devices to add.
5. Select the devices and iterate through their configurations.

You can also **Reconfigure** a entry by changing its options. Saving any changes in the options dialog automatically reloads the integration, so new settings take effect immediately without restarting Home Assistant.
While reconfiguring, devices not selected will be removed from the entry.

### Manual - YAML Configuration

You can set the integration up in `configuration.yaml` instead of the UI.

Minimal example with one local device:
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

Home Assistant reads the YAML at every start. It creates the config entry when it is missing and updates it when the YAML changed. An unchanged YAML causes no reload. A device you remove from the YAML is removed from the config entry, so do not change a YAML managed entry in the UI: the next restart puts the YAML values back.

Every item in the list is one config entry. An item with a `cloud` block is the entry for that Gree account, and the one item without a `cloud` block is the entry for all local-only devices. A device that is already in another config entry is skipped, with an error in the log and a repair issue.

A `cloud` block logs in to the Gree account only on the first import, and again when you change the email, region or password. Every login ends the other sessions of that account, so the Gree app logs you out at that moment. An unchanged `cloud` block reuses the stored session.

See [`manual-configuration.yaml`](manual-configuration.yaml) for a complete configuration example with all available options and detailed comments.

## Connection Methods and Configuration

The integration supports both the local UDP protocol and the MQTT cloud protocol to communicate with the devices. It also supports enhancing local devices with cloud info during discovery.

During configuration, you can select which of the methods are used to discover and connect to devices.

**For better organization, multiple config entries are required!**
There is a config entry for all local-only devices and a config entries for each of the configured Gree Accounts.

In a device page you can check which communication protocol is being used.

### Local Configuration

If you perform a local-only setup, the integration will automatically search for devices using the UDP protocol in the networks connected to your HA instance using a broadcast.
You can specify additional VLANs or hosts that will be scanned using a unicast.

You will then see a list of discovered devices to select which ones to add to HA. This list excludes devices already configured.

After successfully configuring the devices, they will be added to the _Local-only_ config entry.

### Cloud Configuration

If you perform a cloud-only setup, the integration will retrieve the devices bound to your Gree account.

You will then see a list of discovered devices to select which ones to add to HA.
If a configured local-only device that matches the cloud devices is found, it will be merged with the cloud-device and default to local control.

After successfully configuring the devices, they will be added to a config entry exclusive to the cloud account.

### Mixed Cloud + Local Configuration

If you perform a setup using both methods, the integration will retrieve the devices bound to your Gree account and automatically discovered the local devices as in the [Local Configuration](#local-configuration).

The list of discovered devices will be constrained to the cloud devices and you will see if they were also found locally. If a configured local-only device that matches the cloud devices is found, it will be merged with the cloud-device and default to local control.

If a device responds to local commands, the cloud is only used to improve the discovered info (e.g., device name). This behaviour can be overriden in the Cloud Connection Settings of each device, where you can set it to use the MQTT connection instead.

After successfully configuring the devices, they will be added to a config entry exclusive to the cloud account.


## Obtaining the Encryption Key

The integration has the capability of automatically retrieve the encryption version and key of a device from the cloud account or using the Gree local protocol, which has been reverse-engineered.

However, if your HVAC device was previously set up for remote access using a mobile app, the integration may fail to retrieve the encryption key automatically using the local protocol.

#### Method 1: From Gree's cloud server

To extract encryption keys from an account on Gree’s cloud server, follow the instructions in https://github.com/luc10/gree-api-client

#### Method 2: From the Android app

One way is to pull the sqlite db from an Android device, as described here:

https://stackoverflow.com/questions/9997976/android-pulling-sqlite-database-android-device

```bash
adb backup -f ~/backup.ab -noapk com.gree.ewpesmart
dd if=data.ab bs=1 skip=24 | python -c "import zlib,sys;sys.stdout.write(zlib.decompress(sys.stdin.read()))" | tar -xvf -
sqlite3 data.ab 'select privateKey from db_device_20170503;' # but table name can differ a little bit.
```

> [!TIP]
> If you are getting a UTF-8  error (like: "UnicodeDecodeError: 'utf-8' codec can't decode byte 0xda in position 1: invalid continuation byte"), see https://github.com/RobHofmann/HomeAssistant-GreeClimateComponent/issues/318.

Optionally, you can also sniff the `uid` parameter. This is not needed for all devices.


## Debugging

If you are having problems with your device, whenever you write a bug report, be sure to provide details about your device, Home Assistant version, and what exactly went wrong.

It also helps tremendously if you include debug logs directly in your issue (otherwise, we will just ask for them, and it will take longer). So please enable debug logs in the integration UI, or like this:

```yaml
logger:
   default: error
   logs:
      custom_components.gree_custom: debug
```

## Device Sensors

The integration supports sensors if your Gree device has them:

### Indoor Temperature

If your AC unit has a built-in room temperature sensor, it will be automatically detected and exposed as:
- **Separate sensor entity**: `sensor.your_ac_indoor_temperature`
- **Climate entity attribute**: `current_temperature` (accessible via `{{ state_attr('climate.your_ac', 'current_temperature') }}`).

### Outdoor Temperature

If your AC unit has an outdoor temperature sensor, it will be automatically detected and exposed as:
- **Separate sensor entity**: `sensor.your_ac_outdoor_temperature`
- **Climate entity attribute**: `outside_temperature` (accessible via `{{ state_attr('climate.your_ac', 'outside_temperature') }}`)

### Indoor Humidity

If your AC unit has a built-in room humidity sensor, it will be automatically detected and exposed as:
- **Separate sensor entity**: `sensor.your_ac_room_humidity`
- **Climate entity attribute**: `current_humidity` (accessible via `{{ state_attr('climate.your_ac', 'current_humidity') }}`).

### Sensor Overrides

The indoor _temperature_ (`current_temperature`) and _humidity_ (`current_humidity`) values exposed by the Climate entity (`climate.your_ac`) can be overridden during configuration by another HA entity. This is helpful for obtaining a more comprehensive climate entity when the AC does not provide the respective sensors. However, please note that the AC operation is not driven by these values, as they are only exposed for information purposes.

## Available Switches and Controls

Depending on the device configuration, specific Gree AC model, and firmware version, the integration exposes various entities to configure additional features of your Gree AC unit. Entity availability depends on the current HVAC mode and status. These controls allow you to toggle special modes and adjust settings:

### Features

- **Health**: Enables or disables the Health mode for air ionization and purification
- **Power Save**: Enables or disables the power saving mode for energy efficiency. Only available in cooling mode
- **Smart 8°C Heat**: Enables or disables the 8°C heating mode for frost protection. Only available in heating mode
- **Sleep**: Enables or disables the sleep mode for comfortable overnight operation. Only available in cooling or heating mode
- **Fresh Air**: Enables or disables the fresh air circulation mode
- **X-Fan**: Enables or disables the X-Fan mode that keeps the fan working for a few moments after turning the device off in cooling and dry modes, preventing condensation in the unit
- **Anti Direct Blow**: Prevents direct air flow from blowing on people by adjusting the air deflector position
- **Humidity Control**: Control the room humidity to a set target or inteligently. Only available in cooling and dry modes

### Configuration Controls

- **Beeper**: Controls the beeper sounds from the air conditioner unit. When enabled, the unit will make sounds for button presses and status changes
- **Lights**: Controls the display lights on the air conditioner unit
- **Auto Light**: Automatically controls the display lights based on HVAC operations. When enabled, lights will turn on/off with the AC unit. *Note: This is an integration feature, not an actual AC unit state*
- **Light Sensor**: Enables or disables light sensor for automatic brightness. Requires lights to be enabled
- **Auto X-Fan**: Automatically controls the X-Fan mode based on HVAC operations. When enabled, X-Fan will automatically turn on in cooling and dry modes. *Note: This is an integration feature, not an actual AC unit state*
- **Temperature Step**: Sets the increment step for adjusting the target temperature. This allows you to configure how much the temperature changes when using the up/down controls in Home Assistant

### Diagnostics

- **Fault Detection**: Sensor that shows if there is a problem with the device's operation

## Credits

Portions of the code development, debugging, and documentation were performed by Large Language Models (LLMs)

This project is based on the work of several contributors and projects:

- [greeclimate-js](https://github.com/davo22/greeclimate-js) - TypeScript library for controlling Gree-based mini-split air conditioning systems
- [greeclimate](https://github.com/davo22/greeclimate) - A fully async Python3 based package for controlling Gree based ACs and heat pumps
- [gree-remote](https://github.com/tomikaa87/gree-remote) - Gree air conditioner remote control protocol
- [greeclimate](https://github.com/cmroche/greeclimate) - Python package for controlling Gree based minisplit systems
- [gree-api-client](https://github.com/luc10/gree-api-client) - Python client for the Gree API
- [Home Assistant Developer Documentation](https://developers.home-assistant.io) - Official development guidelines and best practices
