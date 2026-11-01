# Mastervolt Web App v1.4.10

- Removed the fixed Balancer 1 → 2 → 3 polling bias.
- A balancer that timed out is attempted first during the next cycle.
- Healthy balancers rotate through the first, second and third connection positions.
- Increased the post-disconnect Windows Bluetooth settling interval from two to four seconds.
- Retained shared discovery, known-device reuse, explicit GATT cleanup and sequential read/disconnect behavior from v1.4.9.
- Updated application, footer and service-worker cache version to v1.4.10.
