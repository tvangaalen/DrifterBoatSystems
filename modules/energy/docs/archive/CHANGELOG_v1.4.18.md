# Mastervolt Web App v1.4.18

- Replaced the two-level Bluetooth gate with a deterministic priority queue.
- Priority order is: user controls, manual BMS refresh/reconnect, automatic reconnect, automatic BMS reads, balancer traffic.
- Manual `Refresh all` reads can no longer wait behind a newly queued automatic read or balancer operation.
- Setting writes and verification requests retry once before failing.
- `Set all` errors identify the failed battery, completed batteries, and batteries not changed.
- Failure dialogs remain open until the user presses OK.
- Waiting dialogs identify the currently finishing radio operation and confirm the user action is next.
- BMS status exposes manual refresh progress and the complete queue state for diagnostics.
- Updated application and service-worker cache versions to v1.4.18.
