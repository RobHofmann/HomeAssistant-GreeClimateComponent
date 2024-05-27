[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)

# HomeAssistant-GreeClimateComponent
Custom Gree climate component written in Python3 for Home Assistant. Controls AC's supporting the Gree protocol.

Tested on the following hardware:
- Innova HVAC
- Cooper & Hunter (CH-S12FTXE(WI-FI)-NG)
- AC Pioneer Fortis Series with WI-FI module CS532AE
- AC Gree GWH12ACC-K6DNA1D
- Inventor Life Pro WiFi
- Toyotomi Izuru TRN/TRG-828ZR
- Sinclair ASH-13BIF2
- TOSOT BORA-GWH09AAB
- CASCADE BORA-CWH09AAB
- EWT S-090 GDI-HRFN1, EWT S-120 GDI-HRFN1 (WI-FI module CS532AEH)
- Tadiran Alpha Expert Inverter
- Copmax Air-Air Heatpump GWH12QC-K6DNA5F 3.5kW

Tested on these Home Assistant versions:
- 0.96.x+ (for older versions, please see the releases tab)
- 0.10X+
- 0.11X+
- 2023.x.x
- 2024.x.x

**If you are experiencing issues please be sure to provide details about your device, Home Assistant version and what exactly went wrong.**

 If your HVAC has already been configured to be controlled remotely by an android app, the encryption key might have changed.

 To configure HVAC wifi (without the android app): https://github.com/arthurkrupa/gree-hvac-mqtt-bridge#configuring-hvac-wifi

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
     encryption_key: <OPTIONAL: custom encryption key. Integration will try to get key from device if empty>
     encryption_version: <OPTIONAL: should be set to 2 for V1.21>
     uid: <some kind of device identifier. NOTE: for some devices this is optional>
     temp_sensor: <entity id of the EXTERNAL temperature sensor. For example: sensor.bedroom_temperature>
     lights: <OPTIONAL: input_boolean to switch AC lights mode on/off. For example: input_boolean.first_ac_lights>
     xfan: <OPTIONAL: input_boolean to switch AC xfan mode on/off. For example: input_boolean.first_ac_xfan>
     health: <OPTIONAL: input_boolean used to switch the Health option on/off of your first AC. For example: input_boolean.first_ac_health>
     sleep: <OPTIONAL: input_boolean to switch AC sleep mode on/off. For example: input_boolean.first_ac_sleep>
     powersave: <OPTIONAL: input_boolean to switch AC powersave mode on/off. For example: input_boolean.first_ac_powersave>
     eightdegheat: <OPTIONAL: input_boolean used to switch 8 degree heating on/off on your first AC>
     air: <OPTIONAL: input_boolean used to switch air/scavenging on/off on your first AC>
     target_temp: <OPTIONAL: input_number used to set the temperature of your first AC. This is usefull if you want to use dashboards with custom frontend components>
     auto_xfan: <OPTIONAL: boolean (true/false); this feature will always turn on xFan in cool and dry mode to avoid mold & rust created from potential water buildup in the AC>
     auto_light: <OPTIONAL: boolean (true/false); this feature will always turn light on when power on and turn light light off when power off automatically> 
   
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

## Optional Features
NOTE: Your AC has to support these features for it to be used.
```
     temp_sensor: This attaches an external temperature sensor to your AC. Gree unfortunately doesnt support a "current temperature" on its own.
     lights: This switches the backlight of the AC Display on or off
     xfan: This dries the AC after being used. This is to avoid nasty smells from usage.
     health: The air goes through a filter to "clean the air".
     sleep: This will enable a comfortable sleep mode. The AC won't make a lot of noise using this.
     powersave: It seems this mode should be an efficient way of approximately reaching the desired temperature (temperatures will vary using this).
     eightdegheat:  This feature maintains the room temperature steadily at 8°C and prevents the room from freezing by activating the heating operation automatically when nobody is at home over a longer period during severe winter
     air: This feature will extract air from the room. This is to remove hot air or nasty smells from the room.
```
