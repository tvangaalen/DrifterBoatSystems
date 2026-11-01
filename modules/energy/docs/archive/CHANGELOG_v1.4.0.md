# Mastervolt Web App v1.4.0

- Added a third live data page, **Balance**, for `DL-BAL1`, `DL-BAL2` and `DL-BAL3`.
- Added staggered, persistent Bluetooth connections so the established BMS links get time to settle first.
- Shows connection state and every readable or notifying GATT characteristic per balancer.
- Sends only DALY's documented read-only status requests and retains the received raw notification frames for hardware-based protocol mapping.
- Standard Bluetooth values receive a human-readable label; undocumented DALY values retain their UUID and raw value rather than using an uncertain mapping.
- Added manual Refresh all and automatic background updates.
- Updated the application version, footer and service-worker cache to v1.4.0.
