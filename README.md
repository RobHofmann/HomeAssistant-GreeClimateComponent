[![HACS](https://img.shields.io/badge/HACS-Default-orange.svg)](https://hacs.xyz)
[![Home Assistant](https://img.shields.io/badge/Compatible-Home_Assistant_2025.9.4-blue.svg)](https://www.home-assistant.io)

# HomeAssistant-GreeClimateComponent

Custom Gree inetgration for Home Assistant written in Python3. Controls ACs supporting the Gree protocol.

This integration connects directly to your HVAC devices via their IP address on the local network, unlike the official mobile app, which establish a direct connection only during initial setup and subsequently operate through Gree’s servers.

The integration attempts to obtain the encryption key by the initial setup protocol, which has been reverse-engineered.

> [!WARNING]
> If your HVAC device was previously set up for remote access using a mobile app, the integration may fail to retrieve the encryption key automatically. Find out more on methods of obtaining your device key bellow.


For a comprehensive list of tested devices, see [Supported Devices](supported-devices.md).

**If you are experiencing issues please read the [Debugging](#debugging) section**


Official mobile applications:
- [Gree+ Android App](https://play.google.com/store/apps/details?id=com.gree.greeplus)
- [Gree+ iOS App](https://apps.apple.com/app/gree/id1167857672)
- [EWPE Smart Android App](https://play.google.com/store/apps/details?id=com.gree.ewpesmart)
- [EWPE Smart iOS App](https://apps.apple.com/app/ewpe-smart/id1189467454)

To configure HVAC wifi (without the mobile app): https://github.com/arthurkrupa/gree-hvac-mqtt-bridge#configuring-hvac-wifi


## Installation

### HACS (recommended)

This integration is added to HACS default repository list. Search for 'Gree' in the HACS dashboard to find and install it.

### Manual

Copy the `custom_components` folder to your own hassio `/config` folder.


## Configuration

### UI Configuration - Config Flow (recommended)

The integration can be added from the Home Assistant UI.

1. Navigate to **Settings** > **Devices & Services** and click **Add Integration**.
2. Search for **Gree Climate**
3. Choose automatic discovery or manual setup and fill in the desired `name`, `host` and `MAC address`.
4. After a successfull connection with the device, you will be asked to configure the device options.

Your can also **Reconfigure** a device by changing its options. Saving any changes in the options dialog automatically reloads the integration, so new settings take effect immediately without restarting Home Assistant.

### Manual - YAML Configuration

See [`manual-configuration.yaml`](manual-configuration.yaml) for a complete configuration example with all available options and detailed comments.

   Basic example:
   ```yaml
   gree:
     - name: "First AC"
       host: "192.168.1.101"
       mac: "20-FA-BB-12-34-56"
       encryption_version: 2
   ```

### Obtaining the Encryption Key

The integration has the capability of automatically retrieve the encryption version and key of a device using the gree protocol which has been reverse-engineered.

However, if your HVAC device was previously set up for remote access using a mobile app, the integration may fail to retrieve the encryption key automatically.

#### Method 1: From Gree's cloud server

To extract encryption keys from an account on Gree’s cloud server, follow the instructions in https://github.com/luc10/gree-api-client

#### Method 2: From the Android app

One way is to pull the sqlite db from android device like described here:

https://stackoverflow.com/questions/9997976/android-pulling-sqlite-database-android-device

```bash
adb backup -f ~/backup.ab -noapk com.gree.ewpesmart
dd if=data.ab bs=1 skip=24 | python -c "import zlib,sys;sys.stdout.write(zlib.decompress(sys.stdin.read()))" | tar -xvf -
sqlite3 data.ab 'select privateKey from db_device_20170503;' # but table name can differ a little bit.
```

> [!TIP]
> If you are getting an UTF-8  error (like: "UnicodeDecodeError: 'utf-8' codec can't decode byte 0xda in position 1: invalid continuation byte"), see https://github.com/RobHofmann/HomeAssistant-GreeClimateComponent/issues/318.

Optionally, you can also sniff the `uid` parameter. This is not needed for all devices.

### Icon configuration

You can set custom icons for the climate enity by modifying the icon translation file `icons.json`. Refer to this documentation: https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/icon-translations/

## Debugging

If you are having problems with your device, whenever you write a bug report, be sure to provide details about your device, Home Assistant version and what exactly went wrong.

It also helps tremendously if you include debug logs directly in your issue (otherwise we will just ask for them and it will take longer). So please enable debug logs in the integration UI or like this:

```yaml
logger:
   default: error
   logs:
      custom_components.gree: debug
      custom_components.gree.climate: debug
```

## Additional Sensors

The integration supports additional sensors if your Gree device has them:

### Outside Temperature Sensor
If your AC unit has an outside temperature sensor, it will be automatically detected and exposed as:
- **Climate entity attribute**: `outside_temperature` (accessible via `{{ state_attr('climate.your_ac', 'outside_temperature') }}`)
- **Separate sensor entity**: `sensor.your_ac_outside_temperature`

### Humidity Sensor  
If your AC unit has a built-in room humidity sensor, it will be automatically detected and exposed as:
- **Climate entity attribute**: `room_humidity` (accessible via `{{ state_attr('climate.your_ac', 'room_humidity') }}`)
- **Separate sensor entity**: `sensor.your_ac_room_humidity`

## Available Switches and Controls

The integration exposes various entities to configure additional features of your Gree AC unit. All entities are created by default when the integration is set up, but their availability depends on the current HVAC mode and status. Entity availability may also vary depending on your specific Gree AC model and firmware version. These controls allow you to toggle special modes and adjust settings:

### Basic Control Switches
- **X-Fan**: Enables or disables the X-Fan mode for extra drying when turning off
- **Lights**: Controls the display lights on the air conditioner unit  
- **Health**: Enables or disables the Health mode for air ionization and purification
- **Beeper**: Controls the beeper sounds from the air conditioner unit. When enabled, the unit will make sounds for button presses and status changes

### Energy and Comfort Switches
- **Power Save**: Enables or disables the power saving mode for energy efficiency. Only available in cooling mode
- **8°C Heat**: Enables or disables the 8°C heating mode for frost protection. Only available in heating mode
- **Sleep**: Enables or disables the sleep mode for comfortable overnight operation. Only available in cooling or heating mode
- **Air**: Enables or disables the fresh air circulation mode

### Advanced Control Switches
- **Anti Direct Blow**: Prevents direct air flow from blowing on people by adjusting the air deflector position
- **Light Sensor**: Enables or disables light sensor for automatic brightness. Requires lights to be enabled

### Configuration Controls
- **Auto X-Fan**: Automatically controls the X-Fan mode based on HVAC operations. When enabled, X-Fan will automatically turn on in cooling and dry modes. *Note: This is an integration feature, not an actual AC unit state*
- **Auto Light**: Automatically controls the display lights based on HVAC operations. When enabled, lights will turn on/off with the AC unit. *Note: This is an integration feature, not an actual AC unit state*
- **Temperature Step**: Sets the increment step for adjusting the target temperature. This allows you to configure how much the temperature changes when using the up/down controls in Home Assistant
- **External Temperature Sensor**: Select a temperature sensor entity to use instead of the built-in AC sensor. Choose 'None' to use the built-in sensor. This is useful if you have a more accurate room temperature sensor that you want the AC to use for temperature readings

## Credits

This project is based on the work of several contributors and projects:

- [gree-remote](https://github.com/tomikaa87/gree-remote) - Gree air conditioner remote control protocol
- [Home Assistant Developer Documentation](https://developers.home-assistant.io/) - Official development guidelines and best practices
