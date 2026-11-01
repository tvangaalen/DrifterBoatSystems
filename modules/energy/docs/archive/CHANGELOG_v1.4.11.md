# Mastervolt Web App v1.4.11

- Added one process-wide Bluetooth coordinator for the three BMS batteries and three balancers.
- BMS discovery and connection attempts now have priority and are serialized across all Bluetooth workers.
- Balancer polling waits until all three BMS links have remained stable for 10 seconds.
- A lost BMS connection immediately pauses new balancer work until the battery links are stable again.
- Split connection retry settings: BMS defaults to 5 seconds and balancers default to 30 seconds.
- Added a read-only Bluetooth coordinator diagnostics endpoint.
- Updated the application version and service-worker cache to v1.4.11.
