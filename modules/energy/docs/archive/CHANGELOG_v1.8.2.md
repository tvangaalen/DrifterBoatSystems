# Mastervolt Energy v1.8.2

## History time selection

- Replaced Zoom (hrs) with a shared two-handle time-range slider below the History tabs.
- The slider spans the oldest through newest available measurements and filters every History tab.
- Start/end labels include date and 24-hour time; the selected duration is shown in hours.
- Update refreshes the full server history and extends a range that was positioned at the latest measurement.

## Charts

- Renamed Storage `Load (A)` to `Charge/discharge (A)`.
- All horizontal chart-axis dates now use `Day/Month` (`DD/MM`).
- Selecting an individual BMS cell changes the left voltage axis to 2.5–4.0 V; Total remains 0–15 V.

## Validation

- JavaScript syntax check
- Python compile and project self-check
- Active API and browser UI verification
- Release ZIP integrity check
