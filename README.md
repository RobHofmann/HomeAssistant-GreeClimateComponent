[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)

# HomeAssistant-GreeClimateComponent
Custom Gree climate component written in Python3 for Home Assistant. Controls ACs supporting the Gree protocol.

For a comprehensive list of tested devices, see [Supported Devices](supported-devices.md).

Tested on Home Assistant 2025.6.3 

**If you are experiencing issues please be sure to provide details about your device, Home Assistant version and what exactly went wrong.**

This integration connects directly to your HVAC devices via their IP address on the local network, unlike the official mobile app, which establish a direct connection only during initial setup and subsequently operate through Gree’s servers.
The integration attempts to obtain the encryption key by the initial setup protocol, which has been reverse-engineered.

Official mobile applications:
- [Gree+ Android App](https://play.google.com/store/apps/details?id=com.gree.greeplus)
- [Gree+ iOS App](https://apps.apple.com/app/gree/id1167857672)
- [EWPE Smart Android App](https://play.google.com/store/apps/details?id=com.gree.ewpesmart)
- [EWPE Smart iOS App](https://apps.apple.com/app/ewpe-smart/id1189467454)

If your HVAC device was previously set up for remote access using a mobile app, the integration may fail to retrieve the encryption key automatically.

To extract encryption keys from an account on Gree’s cloud server: https://github.com/luc10/gree-api-client

To configure HVAC wifi (without the mobile app): https://github.com/arthurkrupa/gree-hvac-mqtt-bridge#configuring-hvac-wifi

## HACS
This component is added to HACS default repository list.

## Config Flow - UI Configuration (recommended)
The integration can be added from the Home Assistant UI.
1. Navigate to **Settings** > **Devices & Services** and click **Add Integration**.
2. Search for **Gree Climate** and fill in the desired `name`, `host`, `port` and `MAC address`.
3. After setup you can open the integration options to configure additional parameters.
4. Saving any changes in the options dialog automatically reloads the
   integration, so new settings take effect immediately without
   restarting Home Assistant.

### Cross-VLAN Discovery
Standard discovery relies on UDP broadcast, which routers do not forward between VLANs. If your AC is in a different subnet than Home Assistant, pick **Discover devices on other VLANs/subnets** on the first setup screen and enter one or both of the following:

- **Networks**: comma-separated CIDRs to sweep via unicast, e.g. `192.168.30.0/24` or `10.10.20.0/24, 10.10.30.0/24`.
- **Hosts**: comma-separated individual IPs, e.g. `192.168.30.50, 192.168.30.51`.

Each address is probed directly with a UDP unicast packet on port 7000, so inter-VLAN routing and any firewall between Home Assistant and the target subnet must allow UDP/7000.

Limits and notes:
- A single network (and the combined total across networks + hosts) may contain at most 65,536 addresses — i.e. a `/16` like `192.168.0.0/16`. Anything larger (e.g. `10.0.0.0/8`, `172.16.0.0/12`) must be split into multiple CIDRs or covered by the hosts field. Scanning a whole /16 fires tens of thousands of UDP packets and can stress consumer routers — prefer the narrowest CIDR you can identify.
- Values entered during one setup are remembered for the duration of the Home Assistant session, so adding several devices in a row does not require retyping.
- Broadcast discovery on the local VLAN still runs alongside the unicast scan, so units on the same subnet as Home Assistant are also found.

## Manual Installation


1. *(Skip if using HACS)* Copy the `custom_components` folder to your own hassio `/config` folder.

2. **YAML Configuration:** See [`manual-configuration.yaml`](manual-configuration.yaml) for a complete configuration example with all available options and detailed comments.

   Basic example:
   ```yaml
   gree:
     - name: "First AC"
       host: "192.168.1.101"
       mac: "20-FA-BB-12-34-56"
       encryption_version: 2
   ```

3. In your configuration.yaml add the following:

   ```yaml
   climate: !include your_configuration.yaml
   ```

4. *(Optional)* Add info logging to this component (to see if/how it works)

   ```yaml
   logger:
     default: error
     logs:
       custom_components.gree: debug
       custom_components.gree.climate: debug
   ```

5. *(Optional)* Provide encryption key if you have it or feel like extracting it.

   One way is to pull the sqlite db from android device like described here:

   https://stackoverflow.com/questions/9997976/android-pulling-sqlite-database-android-device

   ```bash
   adb backup -f ~/backup.ab -noapk com.gree.ewpesmart
   dd if=data.ab bs=1 skip=24 | python -c "import zlib,sys;sys.stdout.write(zlib.decompress(sys.stdin.read()))" | tar -xvf -
   sqlite3 data.ab 'select privateKey from db_device_20170503;' # but table name can differ a little bit.
   ```

   Write it down in `climate.yaml`: `encryption_key: <key>`.

   > If you are getting an UTF-8  error (like: "UnicodeDecodeError: 'utf-8' codec can't decode byte 0xda in position 1: invalid continuation byte"), see https://github.com/RobHofmann/HomeAssistant-GreeClimateComponent/issues/318.

6. *(Optional)* Provide the `uid` parameter (can be sniffed). This is not needed for all devices.

7. *(Optional)* You can set custom icons by modifying the icon translation file `icons.json`. Refer to this documentation: https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/icon-translations/

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

## Issues

Due to the many issues being created revolving TimeOut errors, I will be closing these. Feel free to make a PR fixing your TimeOut error.
More information on the "why" can be found here: https://github.com/RobHofmann/HomeAssistant-GreeClimateComponent/issues/405#issuecomment-4300110823
