# Mastervolt Web App v1.3.15

- Fixed Float protection to use the same live DALY House Battery SOC shown on the Dashboard.
- Float protection now waits while DALY House Battery SOC is unavailable, preventing a conflicting MasterShunt value from triggering Float during Bluetooth startup.
- Added the active SOC source to the Float policy status for diagnostics.
- Aligned every Settings input and the Float protection toggle to the same horizontal control column.
- Increased Measurement-table and BMS-button font sizes without increasing cell or button heights.
- Preserved the isolated per-battery Bluetooth workers from v1.3.13.
- Updated the application footer and service-worker cache to v1.3.15.
