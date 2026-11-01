# v0.18.4 — Solar OFF command fix

Observed on hardware:
- SCM Solar field 12 is the `On/Off` control.
- The previous implementation wrote field 12 only.
- An OFF request did not actually switch the Solar controller off.

The SCM writable metadata shows field 12 followed by unnamed writable field 13,
matching the companion/commit register pattern seen on other MasterBus controls.

Change:
- write field 12 (0 = OFF, 1 = ON)
- wait 50 ms
- send the MasterBus commit token to field 13
- verify OFF by reading field 12 back and requiring 0

ON remains permissive because the SCM may legitimately return to OFF immediately
when there is insufficient PV.

No dashboard measurement mappings changed.
