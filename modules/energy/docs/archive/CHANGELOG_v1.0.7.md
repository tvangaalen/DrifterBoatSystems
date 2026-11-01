# Mastervolt Web App v1.0.7

- Added an Alternator tile under Loads using Alpha Pro field 6 (`Battery voltage`) and field 8 (`Field current`).
- Alternator load watts are calculated as field 6 × field 8 and included in Total DC load. Field current is subtracted from the residual Other DC Loads first, preventing double counting.
- The new load tile shares the same verified Alpha Pro ON/OFF control as the Sources Alternator tile.
- Switching the alternator off from either tile now requires a custom confirmation popup before Stop Charge is applied.
- Solar now shows `PV ###V` beside its source state, using the existing diagnostic panel-voltage field 4.
- Updated application/footer version and PWA cache to v1.0.7.

The Sources Alternator output current remains the existing DC-balance calculation. Alpha field 8 remains correctly identified as field/excitation current and is used only for the new regulator-load tile.
