# v0.18.5 — Solar tile voltage correction

Verified SCM Solar fields:
- field 4 = PV / panel voltage
- field 5 = charge current
- field 6 = battery / charger output voltage

Change:
- The Solar tile now displays field 6 as Voltage.
- Field 4 is retained in the backend response as `panel_voltage`.
- Solar current remains field 5.
- Solar power remains field 6 × field 5.

No control mappings changed.
