# Mastervolt Web App v1.3.7

- Removed the redundant Charge MOS and Discharge MOS rows from the BMS matrix.
- Added configurable Float-to-Bulk hysteresis and an informational Bulk pop-up.
- Added bidirectional touch navigation between Dashboard and BMS.
- Improved BLE reconnect reliability by caching discovered devices and avoiding disruptive scans while persistent GATT connections are open; a fresh scan is retried after repeated failures.
- Updated application and service-worker versions to v1.3.7.
