# Mastervolt Web App v1.5.0

- Replaced the raw History list with three time-series charts for BMS voltage, current/load, and remaining capacity.
- Each chart shows Battery 1, Battery 2, Battery 3, and a calculated total (average voltage; summed current and capacity).
- Charts cover the complete retained BMS history, starting at the earliest available measurement.
- Added a persistent IndexedDB chart cache in the browser so reopening History renders saved charts without rebuilding them from the server.
- Added an Update button that retrieves and stores only measurements recorded since the previous update.
- Added a compact incremental BMS history API and synchronized cache pruning with the configured server retention period.
- Updated application and service-worker cache versions to v1.5.0.

Note: DALY reports remaining capacity in amp-hours, so the Remaining graph is labelled Ah.
