# Mastervolt Web App v1.7.0

- Moved normalized graph caching from browser IndexedDB to a shared server-side cache rebuilt from SQLite after restart.
- The server retains every measurement and sends a bounded chronological chart sample per zoom window for fast iPhone rendering, while reporting the full measurement counts.
- Update now synchronizes the server cache through the latest available measurement and immediately redraws every graph.
- Added Zoom (hrs), defaulting to the configured history retention period in hours and capped at that value.
- Changing Zoom updates all graph data and restricts every time axis to the most recent requested hours.
- Reordered History tabs to Sources, Storage, Loads and made Sources the default.
- Extended swipe navigation across Dashboard, BMS, Balance, History and Settings in both directions.
- Limited Generated power to DC sources: Charger House, Alternator and Solar.
- Replaced Shore frequency with Shore Power AC voltage under Source conditions.
- Split Storage voltage into separate Battery 1, Battery 2 and Battery 3 graphs.
- Removed the Loads output-frequency graph.
- Updated application and service-worker cache versions to v1.7.0.
