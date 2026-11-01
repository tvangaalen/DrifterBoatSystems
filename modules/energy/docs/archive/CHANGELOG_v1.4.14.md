# Mastervolt Web App v1.4.14

- Replaced `Set SOC accurate` with separate `Set SOC - charge` and `Set SOC - discharge` controls.
- Added equivalent all-battery SOC charge/discharge controls.
- Both write paths use exactly the same interpolation curves as the corresponding measurement rows.
- BMS setting changes now reserve the Bluetooth radio for the entire write, acknowledgement delay, and verification read.
- Connection attempts, periodic reads, balancer traffic, and user writes can no longer overlap a BMS setting change.
- Updated application and service-worker cache versions to v1.4.14.
