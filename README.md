[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)

# Gree Climate Component v2 for Home Assistant

This is **v2** of the custom Gree Climate component for Home Assistant, maintained by @CaliLuke. 
It builds upon the original work by Rob Hofmann and the community (see Sources below). 
This version aims to address several known stability issues and bugs found in the original component, 
while also refactoring the codebase for improved structure and long-term maintainability.

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
- Sinclair ASH-12BIV
- TOSOT BORA-GWH09AAB
- CASCADE BORA-CWH09AAB
- EWT S-090 GDI-HRFN1, EWT S-120 GDI-HRFN1 (WI-FI module CS532AEH)
- Tadiran Alpha Expert Inverter
- Copmax Air-Air Heatpump GWH12QC-K6DNA5F 3.5kW
- Bulex vivair multisplit units; 20-080MC4NO outdoor unit, 20-025 NWI (2,5 kW) indoor unit, 20-035 NWI (3,5 kW) indoor unit
- Kinghome "Pular" - KW12HQ25SDI (Requires encryption_version=2)

Tested on Home Assistant 2024.5.4.

**If you are experiencing issues please be sure to provide details about your device, Home Assistant version and what exactly went wrong.**

 If your HVAC has already been configured to be controlled remotely by an android app, the encryption key might have changed.

 To configure HVAC wifi (without the android app): https://github.com/arthurkrupa/gree-hvac-mqtt-bridge#configuring-hvac-wifi

**Sources used:**
 - https://github.com/tomikaa87/gree-remote
 - https://github.com/vpnmaster/homeassistant-custom-components
 - https://developers.home-assistant.io/
 - https://github.com/RobHofmann/HomeAssistant-GreeClimateComponent
 
## Optional Features
NOTE: Your AC has to support these features for it to be used.

- `temp_sensor`: Attaches an external temperature sensor to your AC. Gree unfortunately doesnt support a "current temperature" on its own.
- `lights`: Switches the backlight of the AC Display on or off.
- `xfan`: Dries the AC after being used. This is to avoid nasty smells from usage.
- `health`: The air goes through a filter to "clean the air".
- `sleep`: Enables a comfortable sleep mode. The AC won't make a lot of noise using this.
- `powersave`: An efficient way of approximately reaching the desired temperature (temperatures may vary).
- `eightdegheat`: Maintains the room temperature steadily at 8°C and prevents freezing by activating heating automatically when nobody is home.
- `air`: Extracts air from the room (air scavenging) to remove hot air or smells.
- `target_temp`: Allows using a custom `input_number` entity to set the target temperature (useful for custom dashboards).
- `auto_xfan`: Automatically turns on xFan in cool and dry modes to prevent mold/rust.
- `auto_light`: Automatically turns the AC display light on when powered on and off when powered off.
