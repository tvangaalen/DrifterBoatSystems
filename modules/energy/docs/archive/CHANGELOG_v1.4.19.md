# Mastervolt Web App v1.4.19

- Fixed a false `BMS update failed` after the final battery already reported `verification complete`.
- The former 25-second per-battery watchdog was shorter than the valid write plus nine verification requests with retries.
- Individual write and verification timeouts remain authoritative for real failures.
- The outer deadlock watchdog is now 120 seconds and reports the last active phase if it ever expires.
- A successfully completed verification can no longer be cancelled by the former 25-second boundary.
- Updated application and service-worker cache versions to v1.4.19.
