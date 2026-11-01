# Mastervolt Web App v1.3.8

- Implemented Concept A styling with compact battery summary cards and grouped comparison-matrix sections.
- Restored immediate `Updating…` feedback for manual refreshes and added a visible latest-refresh time and configured interval.
- Prevented a hanging Windows BLE connection from blocking all future refreshes by adding hard deadlines around connect and notification setup.
- Healthy persistent BMS sessions are refreshed before reconnecting a missing battery.
- Updated application and service-worker versions to v1.3.8.
