# Mastervolt Web App v1.4.15

- Widened Dashboard voltage, current, and watt columns and reduced the device-name column.
- Restored the lightning icon next to the MASTERVOLT page title.
- Made BMS `Refresh all` generation-based so every connected battery must complete the requested refresh.
- BMS cards now show their real sequential `Updating` state instead of changing all three optimistically.
- Moved `SOC - Charging` and `SOC - Discharging` into the STATUS section.
- BMS controls remain available while a connected battery is being read.
- User writes register high Bluetooth priority immediately and show `Waiting for Bluetooth queue to become available` while queued.
- Made Balancer `Refresh all` generation-based so one request covers all three balancers.
- Added persistent `Balancer refresh interval` setting, default 30 seconds.
- Removed the History Export button.
- Updated application and service-worker cache versions to v1.4.15.
