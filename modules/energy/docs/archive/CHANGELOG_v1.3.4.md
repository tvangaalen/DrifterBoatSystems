# Mastervolt Web App v1.3.4

## BMS page

- Replaced the circular SOC gauge with a semicircular analog dial based on the supplied reference: red, amber, and green ranges, a pointer, and the percentage value.
- Corrected DALY cell-balancing bit order: protocol Bit0 now maps to Cell 1 through Bit47 to Cell 48.
- Filters balancing results against the actual cell count reported by command `0x94`.

## Connection recovery

- Added the persistent `Connection retry interval` setting with a default of 5 seconds and an accepted range of 1–300 seconds.
- When any battery is disconnected or not found, connection discovery continues automatically using this interval.
- An unexpected BLE disconnect immediately wakes the reconnect loop; subsequent failed attempts use the configured delay.

## Version

- Updated the application version, footer, and service-worker cache to v1.3.4.
