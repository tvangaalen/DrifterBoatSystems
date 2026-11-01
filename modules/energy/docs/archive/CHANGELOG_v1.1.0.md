# Mastervolt Web App v1.1.0

## Changes

- Added a functional Settings page through the bottom-right Settings icon.
- Added persistent **Default AC limit (A)**, validated from 3 through 15 A and applied by Marina mode.
- Added persistent **Float protection** ON/OFF control.
- Added configurable **House Battery SOC%** threshold from 50 through 100% when Float protection is enabled.
- Added configurable **Show warning pop-duration** from 1 through 60 seconds.
- Settings are stored atomically in local `user_settings.json` and survive app/server restarts.
- The Float warning text and timeout now use the configured threshold and duration.
- The existing defaults remain 15 A, Float protection ON, 95%, and 8 seconds.
- Updated the application version, footer, and service-worker cache to v1.1.0.
