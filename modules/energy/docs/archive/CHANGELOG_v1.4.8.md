# Mastervolt Web App v1.4.8

- Removed the derived SOC percentage from the `Average` voltage row.
- All voltage-derived `Set SOC accurate` actions now use the `SOC - Discharging` curve; fixed `Set SOC 100%` actions remain exactly 100%.
- Confirmed and exposed Float Protection as a server-side background policy that checks every three seconds without a connected browser.
- Changing `Switch to Float when SOC` automatically initializes `Switch to Bulk when SOC` five percentage points lower. Users may then only choose an equal or lower Bulk threshold.
- Added `Save history period` with a seven-day default and automatic rolling deletion of older measurements.
- Serialized every BMS refresh and control operation per battery so Bluetooth reads and writes cannot overlap.
- Updated application version, footer and service-worker cache to v1.4.8.
