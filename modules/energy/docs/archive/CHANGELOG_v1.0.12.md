# Mastervolt Web App v1.0.12

## Changes

- Restricted **AC limit (A)** to whole numbers from 3 through 15 in both the user interface and server-side validation.
- Added an OK dialog with the exact message **Enter a value between 3 and 15** for invalid AC-limit input; after closing it, the field is selected again for immediate correction.
- Positioned the **AC limit (A)** label above the input and vertically aligned the input with the Volt, Amps, and Watts values.
- Added a green-bullet **Active** / **Inactive** status to AC Loads, based on whether its power is greater than zero.
- Styled **Output frequency #hz** in AC Loads like Shore Power input frequency: grey secondary information without a bullet.
- Updated the application version, footer, and service-worker cache to v1.0.12.

## Validation

- Python syntax compilation and project self-check.
- JavaScript syntax validation.
- Release ZIP integrity check.
- Active server and version endpoint verification after deployment.
