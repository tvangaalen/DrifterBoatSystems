# v0.17.8 — Alternator OFF button = Float request

The Alpha Pro tile no longer pretends to have a normal ON/OFF control.

A dedicated `OFF` button is shown on the Alternator tile. Pressing it sends:
- Alpha Pro field 37 (`Float`) = 1.0
- companion/commit field 38

The software then watches the actual Alpha Pro charger state (field 5) for up
to 2.5 seconds. If it reaches raw state 3, the tile displays `State: Float`.

This is a one-way action. There is intentionally no matching ON action because
MasterView exposes no Alpha Pro ON/OFF control.

All existing measurement mappings remain unchanged.
