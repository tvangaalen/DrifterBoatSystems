# v0.17.1 — charger state display

Adds a display-only `State: Bulk / Absorption / Float` line to:
- Charger House
- Charger Start
- Charger Bowthruster

No existing measurement or control mapping was changed.

The state display uses the already exposed MasterBus `Charger state` field 1:
- 2 = Bulk
- 3 = Absorption
- 4 = Float
