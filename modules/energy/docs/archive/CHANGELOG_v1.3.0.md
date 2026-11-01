# Mastervolt Web App v1.3.0

## Changes

- Keeps persistent Bluetooth Low Energy connections open to BATTERY 1, BATTERY 2, and BATTERY 3.
- Refreshes all connected DALY BMS devices concurrently instead of connecting and reading them sequentially.
- Automatically reconnects a battery when its Bluetooth connection is lost.
- Adds the persistent `BMS refresh interval` setting, in seconds, with an allowed range of 5–300 seconds and a default of 10 seconds.
- Keeps manual `Refresh all` available; it now triggers one parallel update over the existing connections.
- Shows connection/update progress on the read-only BMS page.
- Updated the application version, footer, and service-worker cache to v1.3.0.

## Safety

- DALY integration remains read-only. No BMS write or configuration commands were added.
- Existing hardware-validated MasterBus mappings and control sequences are unchanged.
