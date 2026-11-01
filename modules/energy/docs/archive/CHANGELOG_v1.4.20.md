# Mastervolt Web App v1.4.20

- Fixed a race after a successful BMS verification that could incorrectly end in a watchdog failure.
- Bluetooth queue waits now run outside the battery worker event loop, so a completed control action can always return its result.
- Automatic reads and reconnects pause briefly while a user-initiated BMS setting is being completed.
- The 120-second watchdog remains as a last-resort deadlock guard; it is no longer part of the normal success path.
