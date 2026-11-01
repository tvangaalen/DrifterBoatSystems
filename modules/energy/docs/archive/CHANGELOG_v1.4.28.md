# Mastervolt Web App v1.4.28

- After confirmation, the All charge toggle now shows `Queued`, `Waiting for Bluetooth`, and `Action in progress` directly in the button.
- Removed the Bluetooth waiting pop-up for the All charge action.
- Individual Charge controls are disabled while an All charge action is queued or running.
- Charge ON is always available for a connected battery whose Charge MOS is OFF, regardless of current direction.
- Charge OFF is available only while the battery has strictly positive charging current.
- All charge follows the same directional rule: switching all ON is always allowed when connected; switching all OFF requires positive charging current on all three batteries.
