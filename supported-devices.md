# Supported Devices

Tested on the following hardware:

## Argo
- Argo ECOLIGHT 9000 UI WF - Split Air Conditioner Unit (Pair through EWPE Smart app, default settings in gree are fine)
- Argo ECOLIGHT 12000 UI WiFi - Split Air Conditioner Unit (Pair through EWPE Smart app, default settings in gree are fine)

## EWT
- EWT S-090 GDI-HRFN1, EWT S-120 GDI-HRFN1 (WI-FI module CS532AEH)

## Gree Brand Devices
- AC Gree GWH12ACC-K6DNA1D
- AC Gree 3VIR24HP230V1AH
- Ac Gree Pulsar GWH09AGAXB-K6DNA1B (encryption version 2)
- Gree KFR-26G(26564)FNhAg-B1(WIFI)
- Gree MC31-00/F Central Air Conditioner Remote Control Module
- AC Gree Clivia (encryption version 2)

## Kolin
- Kolin KAG-100WCINV (encryption version 2)
- Kolin KAG-145WCINV (encryption version 2)

## Saunier Duval
- Saunier Duval VivAir Lite SDHB1-025SNWI (encryption version 2)
- Saunier Duval VivAir Lite SDHB1-035SNWI (encryption version 2)
- Saunier Duval VivAir SDH20-025NWI (with EWPE-module) (encryption version 2)
- Saunier Duval VivAir SDH20-065NWI (with EWPE-module) (encryption version 2)

## Sinclair
- Sinclair ASH-12BIV
- Sinclair ASH-13BIF2
- Sinclair SIH-09BITW

## TOSOT
- TOSOT BORA-GWH09AAB
- TOSOT Aoraki Series SU-AORAKI12-230 (encryption version 2)
- TOSOT TW12HXP2A1D

## Others
- Bulex vivair multisplit units; 20-080MC4NO outdoor unit, 20-025 NWI (2,5 kW) indoor unit, 20-035 NWI (3,5 kW) indoor unit
- CASCADE BORA-CWH09AAB
- Cooper & Hunter (CH-S12FTXE(WI-FI)-NG)
- Copmax Air-Air Heatpump GWH12QC-K6DNA5F 3.5kW
- Heiwa Essentiel ZEN+ HMIS2-25P-V2 with WI-FI module GRJWB04-J (encryption version 2)
- Innova HVAC
- Inventor Life Pro WiFi
- Kinghome "Pular" - KW12HQ25SDI (encryption version 2)
- AC Pioneer Fortis Series with WI-FI module CS532AE
- Tadiran Alpha Expert Inverter
- Toyotomi Izuru TRN/TRG-828ZR
- Wilfa Cool9 Connected

## Contributing Device Information

If you have successfully used this integration with a device not listed above, please consider contributing by:

1. **Opening an issue** on the GitHub repository with your device information
2. **Including the following details:**
   - Brand and model number
   - WiFi module information (if known)
   - Required encryption version (1 or 2)
   - Any special configuration notes

This helps other users find compatible devices and improves the integration's documentation.

## Encryption Version Notes

- **Encryption Version 1**: Older devices, typically uses ECB encryption
- **Encryption Version 2**: Newer devices, typically uses GCM encryption
- Most devices require encryption version 2, but some older models use encryption version 1
- If you're unsure, try encryption version 2 first, then fall back to encryption version 1 if connection fails
