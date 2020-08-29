[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg?style=for-the-badge)](https://github.com/custom-components/hacs)

# HomeAssistant-GreeClimateComponent
Custom Gree climate component written in Python3 for Home Assistant. Controls AC's supporting the Gree protocol.

Tested on the following hardware:
- Innova HVAC
- Cooper & Hunter (CH-S12FTXE(WI-FI)-NG)
- AC Pioneer Fortis Series with WI-FI module CS532AE
- AC Gree GWH12ACC-K6DNA1D
- Sinclair ASH-13BIF2

Tested on these Home Assistant versions:
- 0.96.x+ (for older versions, please see the releases tab)
- 0.10X+
- 0.11X+

**If you are experiencing issues please be sure to provide details about your device, Home Assistant version and what exactly went wrong.**

 If your HVAC has already been configured to be controled remotely by an android app, the encryption key might have changed.

**Sources used:**
 - https://github.com/tomikaa87/gree-remote
 - https://github.com/vpnmaster/homeassistant-custom-components
 - https://developers.home-assistant.io/
 
## HACS
This component is added to HACS default repository list.

## Custom Component Installation
!!! PLEASE NOTE !!!: Skip step 1 if you are using HACS.
1. Copy the custom_components folder to your own hassio /config folder.

2. In the root of your /config folder, create a file called climate.yaml

   ```yaml
   - platform: gree
     name: First AC
     host: <ip of your first AC>
     port: 7000
     mac: '<mac address of your first AC. NOTE: Format can be XX:XX:XX:XX:XX:XX or XX-XX-XX-XX-XX-XX depending on your model>'
     target_temp_step: 1
     encryption_key: <OPTIONAL: custom encryption key>
     uid: <some kind of device identifier. NOTE: for some devices this is optional>
     temp_sensor: <entity id of the EXTERNAL temperature sensor. For example: sensor.bedroom_temperature. NOTE: this attaches an external temperature sensor to your AC. Gree unfortunately doesnt support a "current temperature" on its own.>
     lights: <OPTIONAL: input_boolean to switch AC lights mode on/off. For example: input_boolean.first_ac_lights>
     xfan: <OPTIONAL: input_boolean to switch AC xfan mode on/off. For example: input_boolean.first_ac_xfan>
     health: <OPTIONAL: input_boolean used to switch the Health option on/off of your first AC. For example: input_boolean.first_ac_health>
     sleep: <OPTIONAL: input_boolean to switch AC sleep mode on/off. For example: input_boolean.first_ac_sleep>
     powersave: <OPTIONAL: input_boolean to switch AC powersave mode on/off. For example: input_boolean.first_ac_powersave>
     eightdegheat: <OPTIONAL: input_boolean used to switch 8 degree heating on/off on your first AC>
     air: <OPTIONAL: input_boolean used to switch air/scavenging on/off on your first AC>
   
   - platform: gree
     name: Second AC
     host: <ip of your second AC>
     port: 7000
     mac: '<mac address of your second AC. NOTE: Format can be XX:XX:XX:XX:XX:XX or XX-XX-XX-XX-XX-XX depending on your model>'
     target_temp_step: 1
   ```

3. In your configuration.yaml add the following:
  
   ```yaml
   climate: !include climate.yaml
   ```

4. OPTIONAL: Add info logging to this component (to see if/how it works)
  
   ```yaml
   logger:
     default: error
     logs:
       custom_components.gree: debug
       custom_components.gree.climate: debug
   ```

5. OPTIONAL: Provide encryption key if you have it or feel like extracting it. 

   One way is to pull the sqlite db from android device like described here:
  
   https://stackoverflow.com/questions/9997976/android-pulling-sqlite-database-android-device

   ```
   adb backup -f ~/backup.ab -noapk com.gree.ewpesmart
   dd if=data.ab bs=1 skip=24 | python -c "import zlib,sys;sys.stdout.write(zlib.decompress(sys.stdin.read()))" | tar -xvf -
   sqlite3 data.ab 'select privateKey from db_device_20170503;' # but table name can differ a little bit.
   ```
   
   Write it down in climate.yaml `encryption_key: <key>`.

6. OPTIONAL: Provide the `uid` parameter (can be sniffed) NOTE: This is not needed for all devices

7. OPTIONAL: Provice input_boolean's to set lights, xfan, sleep and powersave mode on/off.
