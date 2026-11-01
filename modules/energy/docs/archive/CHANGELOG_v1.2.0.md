# Mastervolt Web App v1.2.0

## Changes

- Renamed the bottom navigation **Overview** button to **Dashboard**.
- Replaced **Devices** with a functional **BMS** page.
- Integrated the hardware-confirmed DALY legacy `0xA5` BLE protocol and UUIDs from the existing Windows DALY project.
- Added one-page read-only status for `BATTERY 1`, `BATTERY 2`, and `BATTERY 3`.
- Shows pack voltage, current, SOC, temperatures, remaining capacity, individual cell voltages, cell spread, charge/discharge MOSFET states, balancing, alarms, cycles, device name, and update time.
- Reads the three BMS units sequentially to respect the one-client BLE limitation.
- Added **Refresh all** and automatic first refresh when the BMS page is initially opened.
- BLE failures are isolated per battery; existing last readings remain visible with the current error.
- Write controls remain intentionally excluded until Battery 2 and Battery 3 commands and scaling are independently validated.
- Added `bleak>=2.0,<4` to the project requirements.
- Updated the application version, footer, and service-worker cache to v1.2.0.
