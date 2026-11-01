# v0.17.10 — Mass Charger OFF state

Mass Charger field 1 raw value `0` now displays as `Off`.

Decoder:
- 0 = Off
- 2 = Bulk
- 3 = Absorption
- 4 = Float
- 5 = Constant voltage

This fixes Charger Bowthruster showing `State: Unknown (0)` when switched off.
No measurement or control mappings changed.
