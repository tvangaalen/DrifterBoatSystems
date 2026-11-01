# Mastervolt Web App v1.0.13

## Changes

- Changed the automatic House Battery high-SOC Float threshold from 98% to 95%.
- Added a one-time information dialog when the high-SOC policy actually switches an active Charger House, Alternator, or Solar charger to Float.
- The dialog is driven by a server-side event counter, so normal three-second status refreshes do not repeatedly show it.
- Updated the application version, footer, and service-worker cache to v1.0.13.

## Information message

`House Battery SOC >= 95%. Charger House. Alternator, and Solar have been switched to Float.`
