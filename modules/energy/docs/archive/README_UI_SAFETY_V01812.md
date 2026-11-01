# v0.18.12 — Mobile readability, alignment and ECU safety

Based on v0.18.11. No MasterBus mappings, alternator balance equations, or alternator ON/OFF behavior were changed.

## UI
- Increased iPhone typography across device names, electrical readings, headers, status and controls.
- Device rows use fixed aligned columns: device, AC/DC, voltage, current, watts, control/SoC.
- Tabular numeric figures are used to keep voltage/current decimals vertically aligned.
- Watts are right-aligned in a fixed-width column.
- Storage rows explicitly show `DC`.
- Storage SoC bars were replaced by circular ring indicators with the percentage in the center.
- Storage header now shows signed House battery watts instead of House voltage.
- Storage-row watts are also signed.
- Inverter and AC-limit controls are laid out horizontally with their input/button to the right of the label.

## Engine ECU safety
- Switching Engine ECU OFF now requires an explicit browser confirmation.
- The warning states that OFF can stop a running engine.
- Cancelling leaves the ECU ON; the application does not automatically switch the ECU off.

## PWA
- Cache bumped to `mastervolt-v0.18.12-shell`.
