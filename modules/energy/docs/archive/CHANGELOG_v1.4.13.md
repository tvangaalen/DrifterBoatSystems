# Mastervolt Web App v1.4.13

- Fixed stale `Waiting for BMS` states after all three batteries were already ready.
- A balancer now holds one radio lease across connect, notification setup, requests, and reading.
- Temporary contention with a BMS read is shown as `Queued` instead of incorrectly blaming BMS readiness.
- Waiting states are cleared as soon as all BMS connections and initial readings are complete.
- Updated application and service-worker cache versions to v1.4.13.
