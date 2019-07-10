# HomeAssistant-GreeClimateComponent
Custom Gree climate component written in Python3 for Home Assistant. Controls AC's supporting the Gree protocol.

Tested on:
* Innova HVAC, Cooper & Hunter HVAC
* Home-Assistant 
    - 0.89
    - 0.90.2
    - 0.91.3
    - 0.92.2
    - 0.93.1
    - 0.94.x
    - 0.95.x

 **If you are experiencing issues please be sure to provide details about your device, Home Assistant version and what exactly went wrong.**

 If your HVAC has already been configured to be controled remotely by an android app, the encryption key might have changed.

**Sources used:**
 - https://github.com/tomikaa87/gree-remote
 - https://github.com/vpnmaster/homeassistant-custom-components
 - https://developers.home-assistant.io/

## Component Installation
1. Copy the custom_components folder to your own hassio /config folder.

2. In the root of your /config folder, create a file called climate.yaml

   ```yaml
   - platform: gree
     name: First AC
     host: <ip of your first AC>
     port: 7000
     mac: '<mac address of your first AC>'
     target_temp_step: 1
     encryption_key: <OPTIONAL: custom encryption key if wifi already configured>
     uid: <some kind of device identifier. NOTE: for some devices this is optional>
     temp_sensor: <entity id of the temperature sensor. For example: sensor.bedroom_temperature>
     lights: <OPTIONAL: input_boolean to switch AC lights mode on/off. For example: input_boolean.first_ac_lights>
     xfan: <OPTIONAL: input_boolean to switch AC xfan mode on/off. For example: input_boolean.first_ac_xfan>
     health: <OPTIONAL: input_boolean used to switch the Health option on/off of your first AC. For example: input_boolean.first_ac_health>
     sleep: <OPTIONAL: input_boolean to switch AC sleep mode on/off. For example: input_boolean.first_ac_sleep>
     powersave: <OPTIONAL: input_boolean to switch AC powersave mode on/off. For example: input_boolean.first_ac_powersave>
   
   - platform: gree
     name: Second AC
     host: <ip of your second AC>
     port: 7000
     mac: '<mac address of your second AC>'
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

5. OPTIONAL: Provide encryption key if HVAC's wifi is already configured. 

   One way is to pull the sqlite db from android device like described here:
  
   https://stackoverflow.com/questions/9997976/android-pulling-sqlite-database-android-device

   ```
   adb backup -f ~/backup.ab -noapk com.gree.ewpesmart
   dd if=data.ab bs=1 skip=24 | python -c "import zlib,sys;sys.stdout.write(zlib.decompress(sys.stdin.read()))" | tar -xvf -
   sqlite3 data.ab 'select privateKey from db_device_20170503;' # but table name can differ a little bit.
   ```
   
   Write it down in climate.yaml `encryption_key: <key>`. This solves Issue#1.

6. OPTIONAL: Provide the `uid` parameter (can be sniffed) NOTE: This is not needed for all devices

7. OPTIONAL: Provice input_boolean's to set lights, xfan, sleep and powersave mode on/off.
