# Changelog

### Unreleased

- The engine alarm log reads the YDEN-02 (YD RAW over UDP 1456, listen only) instead of the Orca Core: the engine's own
  warning lights (PGN 127489 discrete status) are logged now, besides high coolant temperature and low oil pressure.
  The live engine line and the engine hours stay on the Core.

### 1.0.0 (2026-11-06)

- First version: diesel fuel fills and engine maintenance with create, read, change and delete; the time, the boat's
  position and the country and nearest marina (OpenStreetMap) are filled in for a new fill and can all be changed.
