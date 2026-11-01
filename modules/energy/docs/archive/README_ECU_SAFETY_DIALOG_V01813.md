# v0.18.13 – Engine ECU safety dialog

- Replaced the native browser confirm dialog with a Mastervolt-styled in-app safety dialog.
- Safe action is **Keep ECU ON** and is focused by default.
- Escape or tapping outside the dialog also cancels and leaves the ECU ON.
- Engine ECU is switched OFF only after the explicit **Switch OFF** action.
- No changes to MasterBus control mappings, alternator control, or DC calculations.
