# Mastervolt Web App v1.0.11

- SUP now blinks between its normal green ON state and a translucent red state while CombiMaster field 49 reports actual Supporting.
- Shore Power displays `Connected` with a green bullet and shows `Input frequency ##hz` separately in the same grey style as Alternator temperature; the dash separator was removed.
- Added an Inverter DC-load tile using CombiMaster battery-side field 11 voltage and the absolute field 12 current.
- Inverter V/A/W are exactly zero unless live status field 47 (`Inverting`) or field 49 (`Supporting`) is active.
- Moved the `INV` control from AC Loads to the new Inverter tile.
- The Inverter tile shows green-bullet `On`/`Off` from the configured inverter control and grey actual statuses `Inverting` and/or `Supporting`.
- Actual inverter DC current is treated as a known DC load like Charger Start and Charger Bowthruster: it is subtracted from Other DC Loads and included separately in Total DC load, avoiding double counting.
- Updated application/footer version and PWA cache to v1.0.11.

The high-SoC Float policy and all existing verified control and safety sequences remain unchanged.
