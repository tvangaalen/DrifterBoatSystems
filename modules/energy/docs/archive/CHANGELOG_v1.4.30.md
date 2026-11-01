# Mastervolt Web App v1.4.30

- Added the same in-button queued/waiting/progress flow to All discharge while retaining its confirmation dialog.
- During an All discharge action, only All discharge and the three individual Discharge controls are disabled.
- Removed the queue pop-up from All discharge; only failures produce a pop-up.
- Discharge ON remains available for a connected battery regardless of current direction.
- Discharge OFF is available only when current is zero or negative; positive current disables it.
- Clicking a battery summary card requests a refresh of only that battery.
- All charge and All discharge now send Bluetooth writes only to batteries whose current MOS state differs from the requested target state.
- Added a server endpoint and worker trigger for per-battery refresh.
