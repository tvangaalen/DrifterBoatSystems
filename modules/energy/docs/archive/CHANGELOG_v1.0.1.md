# Mastervolt Web App v1.0.1

- Storage tiles now obtain battery type and configured capacity from MasterShunt metadata/configuration when those device-provided fields can be identified safely. Numeric field IDs are never guessed; the previous LiFePO4/AGM labels remain as defensive fallback.
- Storage labels render as `Type: XXX NNNA` when capacity is available.
- Increased spacing between AC/DC, voltage, current and power columns.
- Moved AC limit into the Shore Power tile between its label and electrical columns.
- Moved inverter control to the right side of the Shore Power tile and labelled it `INV`; active state remains visually indicated.
- Engine ECU power retains the same tile ON/OFF control as both auxiliary chargers, including the safety confirmation before OFF.
- Removed the redundant standalone inverter and shore-power controls.
- Updated application/footer version and PWA cache to v1.0.1.

Hardware-verified Solar, Alpha Pro, alternator, MasterShunt measurement, charger and Engine ECU control mappings and safety sequences are unchanged.
