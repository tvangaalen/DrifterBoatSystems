# Mastervolt Web App v1.4.21

- BMS Charge and Discharge controls now verify the requested MOS state after every write.
- A command that is acknowledged over Bluetooth but not applied is retried once and then reported with the actual Charge/Discharge states.
- Changing one MOS preserves the other MOS state. If a DALY unit changes both switches as a side effect, the unrelated switch is restored and verified.
- The same verified behavior is used by the per-battery and all-battery controls.
