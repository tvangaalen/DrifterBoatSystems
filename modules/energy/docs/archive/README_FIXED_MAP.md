# v0.17 — verified fixed measurement map

The dashboard no longer uses heuristic/dynamic measurement-field selection.

All normal dashboard measurements are now read from the field numbers verified
during the device-by-device snapshot audit.

This specifically removes the earlier failure modes where:
- Solar field 4 was incorrectly selected as both voltage and power;
- Alpha Pro field 21 (`Battery current`) was treated as alternator current;
- Mass Charger output fields were treated as house-bus input load fields;
- Yanmar generic fields 6/7/22 were incorrectly selected.

## What remains dynamic

MasterBus discovery code is retained only for explicit diagnostics, schema
inspection, and future device exploration.

It is not executed as part of normal dashboard startup and is not used by
`energy()`.

See:

```text
VERIFIED_FIELD_MAP.txt
```

for the authoritative dashboard map.
