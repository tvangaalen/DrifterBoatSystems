# Mastervolt Web App v1.4.9

- Changed the actual default `BMS refresh interval` to 30 seconds; existing saved user settings remain unchanged.
- Balancer reconnects now reuse the last known Windows Bluetooth identity before scanning again.
- All missing balancers are discovered with one shared 12-second scan rather than a separate scan per device.
- Failed and stale GATT clients are explicitly disconnected before retrying, preventing half-open Windows Bluetooth sessions.
- Balancers are connected, read and cleanly disconnected one at a time with a two-second settling interval, while all three BMS links remain persistent. This avoids requiring Windows to maintain six simultaneous DALY GATT sessions.
- Subscriptions are limited to DALY's FFF1 data channel instead of every notifying characteristic.
- Balancer refresh and reconnect timing now follow the saved BMS refresh and connection-retry settings.
- Added connection diagnostics to the Balancer API and updated application/cache version to v1.4.9.
