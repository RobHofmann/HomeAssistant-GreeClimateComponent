# HomeAssistant-GreeClimateComponent
Custom Gree climate component written in Python3 for Home Assistant. Controls AC's supporting the Gree protocol.

**NOTE: This is my first ever Python script. Don't expect any mind blowing architectures in this code. Actually dont expect anything :)**

**Sources used:**
https://github.com/tomikaa87/gree-remote
https://github.com/vpnmaster/homeassistant-custom-components

## TODO
I still need to create a script which fetches the Encryption Key from your Gree AC Device. Will do later.

## Component Installation
1. In the root of your /config folder, create a file called climate.yaml

   ```yaml
   - platform: gree
     name: First AC
     host: <ip of your first AC>
     port: 7000
     mac: '<mac address of your first AC>'
     encryption_key: '<encryptionkey of your first AC>'
     min_temp: 16
     max_temp: 30
     target_temp: 21
     target_temp_step: 1
   
   - platform: gree
     name: Second AC
     host: <ip of your second AC>
     port: 7000
     mac: '<mac address of your second AC>'
     encryption_key: '<encryptionkey of your second AC>'
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
