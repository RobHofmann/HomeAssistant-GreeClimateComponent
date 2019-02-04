# HomeAssistant-GreeClimateComponent
Custom Gree climate component written in Python3 for Home Assistant. Controls AC's supporting the Gree protocol.

**NOTE: This is my first ever Python script. Don't expect any mind blowing architectures in this code. Actually dont expect anything :)**

**Sources used:**
 - https://github.com/tomikaa87/gree-remote
 - https://github.com/vpnmaster/homeassistant-custom-components
 - https://developers.home-assistant.io/

## Component Installation
1. In the root of your /config folder, create a file called climate.yaml

   ```yaml
   - platform: gree
     name: First AC
     host: <ip of your first AC>
     port: 7000
     mac: '<mac address of your first AC>'
     min_temp: 16
     max_temp: 30
     target_temp: 21
     target_temp_step: 1
     encryption_key: <custom encryption key if wifi already configured>
     uid: <some kind of device identifier>  
   
   - platform: gree
     name: Second AC
     host: <ip of your second AC>
     port: 7000
     mac: '<mac address of your second AC>'
     min_temp: 16
     max_temp: 30
     target_temp: 21
     target_temp_step: 1
   ```

2. In your configuration.yaml add the following:
  
   ```yaml
   climate: !include climate.yaml
   ```

3. OPTIONAL: Add info logging to this component (to see if/how it works)
  
   ```yaml
   logger:
     default: error
     logs:
       custom_components.climate.gree: info
   ```
4. OPTIONAL: Provide encryption key if HVAC's wifi is already configured. 

One way is to pull the sqlite db from android device like described here:

https://stackoverflow.com/questions/9997976/android-pulling-sqlite-database-android-device

```
adb backup -f ~/backup.ab -noapk com.gree.ewpesmart
dd if=data.ab bs=1 skip=24 | python -c "import zlib,sys;sys.stdout.write(zlib.decompress(sys.stdin.read()))" | tar -xvf -
sqlite3 data.ab 'select privateKey from db_device_20170503;' # but table name can differ a little bit.
```

Write it down in climate.yaml `encryption_key: <key>`. This solves Issue#1.

5. OPTIONAL: Provide the `uid` parameter (can be sniffed)
