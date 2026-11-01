# Mastervolt Web App v1.3.2

## Changes

- Rebuilt the BMS page as a comparison matrix with one shared label column and one value column per battery.
- Added Storage-style SOC circles with one decimal place.
- Shows remaining capacity with one decimal place.
- Added per-battery `Set SOC 100%`, Charge ON/OFF, and Discharge ON/OFF controls.
- Every control asks for confirmation, saves a timestamped pre-change status backup, applies the confirmed DALY command, and performs a complete parallel refresh of all batteries.
- Charge and discharge buttons show the currently reported MOS state.
- Updated the application version, footer, and service-worker cache to v1.3.2.

## DALY commands

- SOC calibration: confirmed command `0x21`, value `100.0%` encoded as `1000` in the final two payload bytes.
- Charge MOSFET: confirmed command `0xDA` with `0x01`/`0x00`.
- Discharge MOSFET: confirmed command `0xD9` with `0x01`/`0x00`.
- Write frames use the confirmed DALY legacy `0xA5` protocol and write source byte `0x80` from the supplied Windows Bluetooth project.

## Safety

- Protection-threshold registers remain inaccessible.
- Existing hardware-validated MasterBus mappings and control sequences are unchanged.
