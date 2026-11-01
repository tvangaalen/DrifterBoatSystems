# Mastervolt Web App v1.0.8

- Fixed Total DC load so AC Loads watts are excluded; AC consumer power is reported separately in the API.
- Added the shared `INV` inverter switch to the AC Loads tile.
- Added Sail mode: Anchor mode actions plus Engine ECU power ON.
- Engine ECU power state now displays `On` / `Off`.
- Moved System OK and the clock into the MASTERVOLT header row.
- Shore Power shows connection state and input frequency from verified CombiMaster field 4.
- AC Loads shows output frequency from CombiMaster field 6, identified by a live read-only metadata scan.
- Updated application/footer version and PWA cache to v1.0.8.

All existing hardware-verified control sequences, DC-balance logic and Engine ECU safety behavior remain unchanged.
