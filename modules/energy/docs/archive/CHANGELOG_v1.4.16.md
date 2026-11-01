# Mastervolt Web App v1.4.16

- `Set all` BMS actions now reserve the Bluetooth radio once for the complete three-battery batch.
- Prevents reconnects, periodic reads, and balancer traffic from slipping between Battery 1, 2, and 3 writes.
- Added server-side BMS control progress with separate waiting and updating phases.
- The control dialog now reports `Updating Battery 1/3`, `2/3`, and `3/3` instead of showing a queue message during the full operation.
- Individual BMS controls use the same progress reporting.
- Updated application and service-worker cache versions to v1.4.16.
