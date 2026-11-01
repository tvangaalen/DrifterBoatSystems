# Mastervolt Web App v1.3.13

- Replaced the shared DALY Bluetooth event loop with three failure-isolated workers, one Windows thread and asyncio loop per battery.
- Restored the logical startup order Battery 1, Battery 2, Battery 3 with one-second staggering.
- A stalled discovery, connection, notification or refresh for one battery can no longer stop refreshes for the other two.
- Healthy persistent Bluetooth connections remain open; only missing batteries retry on their own interval.
- Manual `Updating all batteries` state now has a server-controlled 12-second maximum and can no longer depend indefinitely on receiving a new timestamp.
- Updated the application footer and service-worker cache to v1.3.13.
