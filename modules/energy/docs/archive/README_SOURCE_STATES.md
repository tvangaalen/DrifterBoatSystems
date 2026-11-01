# v0.17.4 — Solar and Alternator state indicators

Implemented directly in the respective source tiles.

No verified field mappings or controls changed.

Solar state
- Charging: verified Solar charge current (field 5) > 0.10 A
- Idle: charge current <= 0.10 A

Alternator state
- Stopped: verified shaft fields indicate stopped
- Charging: shaft fields indicate running and derived alternator current > 0.50 A
- Running: shaft fields indicate running and derived current <= 0.50 A

The states are deliberately derived from already verified measurements rather
than assigning meanings to unverified internal enum fields.
