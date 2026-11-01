# Mastervolt Web App v1.4.26

- Removed confirmation dialogs from individual-battery BMS controls only.
- Retained confirmation dialogs for every all-battery control.
- The clicked individual control now shows `Waiting for Bluetooth` while queued.
- The same button changes to `Action in progress` during writing and background validation.
- BMS controls remain disabled until the action completes, then return to their live normal state.
- Failures still produce a persistent error pop-up.
