# v0.17.6 — source-tile controls

Changes:
- Moves the verified CombiMaster Charger ON/OFF button from the lower control
  strip to the Charger House source tile.
- Adds ON/OFF button positions to the Solar and Alternator source tiles.
- Renames `Total Output` in LOADS to `Total DC load`.

Safety / verification:
- Solar field 12 is known from the device snapshot as RW `On/Off`, but its write
  semantics have not yet been tested on the hardware. The Solar tile therefore
  shows the control but keeps it disabled (`N/A`) until verified.
- The Alpha Pro ON/OFF control field has not yet been identified. Its tile also
  shows the disabled control position rather than inventing a write mapping.

Existing verified controls and all measurement mappings are unchanged.
