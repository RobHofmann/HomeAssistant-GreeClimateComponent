[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)

# HomeAssistant-GreeClimateComponent
Custom Gree climate component written in Python3 for Home Assistant. Controls ACs supporting the Gree protocol.

For a comprehensive list of tested devices, see [Supported Devices](supported-devices.md).

Tested on Home Assistant 2025.6.3 

**If you are experiencing issues please be sure to provide details about your device, Home Assistant version and what exactly went wrong.**

 If your HVAC has already been configured to be controlled remotely by an android app, the encryption key might have changed.

 To configure HVAC wifi (without the android app): https://github.com/arthurkrupa/gree-hvac-mqtt-bridge#configuring-hvac-wifi

**Sources used:**
 - https://github.com/tomikaa87/gree-remote
 - https://github.com/vpnmaster/homeassistant-custom-components
 - https://developers.home-assistant.io/

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
If your AC unit has a built-in humidity sensor, it will be automatically detected and exposed as:
- **Climate entity attribute**: `room_humidity` (accessible via `{{ state_attr('climate.your_ac', 'room_humidity') }}`)
- **Separate sensor entity**: `sensor.your_ac_humidity`
