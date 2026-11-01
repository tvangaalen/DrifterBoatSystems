# Mastervolt Web App v1.4.17

- Added explicit 8-second timeout to every BMS setting write.
- Added explicit 4-second timeout to each verification request.
- Reduced the per-battery outer timeout to 25 seconds and cancel the underlying task when exceeded.
- The Bluetooth radio is no longer released while a timed-out background control may still be running.
- Progress now identifies `sending setting`, `waiting for BMS confirmation`, and all nine verification reads.
- Failures identify the battery, operation, and timeout instead of returning only `BMS control failed`.
- Updated application and service-worker cache versions to v1.4.17.
