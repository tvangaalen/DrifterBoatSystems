# Mastervolt Web App v1.4.6

- Decodes every active DALY 0x98 alarm bit into readable text, one alarm per line.
- Adds directional swipe navigation: Dashboard → BMS → Balance and back.
- Adds a durable SQLite measurement history with full Dashboard snapshots every 10 seconds and each new decoded BMS/balancer reading.
- Activates the History page with recent records, expandable JSON values and a JSON Lines export.
- Prioritizes disconnected balancers, retries them every 5 seconds and caches known Bluetooth device identities.
- Clears a stale cached identity after repeated failures so the device can be rediscovered.
