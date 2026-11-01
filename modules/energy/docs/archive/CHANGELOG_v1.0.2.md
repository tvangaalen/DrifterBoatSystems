# Mastervolt Web App v1.0.2

- Shore Power now places `AC limit (A)` directly to the left of its amp input.
- Engine ECU power now displays an ON/OFF state indicator directly below its tile label, while retaining its verified right-side control and mandatory OFF safety dialog.
- Added Motor mode: inverter OFF, Charger House OFF, alternator ON, Solar ON, Charger Start ON, Charger Bowthruster ON and Engine ECU power ON.
- Added Anchor mode: inverter OFF, Charger House OFF, alternator OFF, Solar ON, Charger Start OFF and Charger Bowthruster OFF.
- Added Marina mode: Charger House ON, alternator OFF, Solar ON, Charger Start ON and Charger Bowthruster ON.
- Anchor and Marina modes deliberately leave Engine ECU power unchanged; no mode can switch this safety-critical supply off.
- Mode operations use only existing verified control methods and report any partial failure.
- Updated application/footer version and PWA cache to v1.0.2.

All previously hardware-verified mappings, alternator sequences and Engine ECU OFF confirmation behavior remain unchanged.
