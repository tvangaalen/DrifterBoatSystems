# Mastervolt Web App v1.4.7

- Added `SOC - Charging` and `SOC - Discharging` rows to the BMS measurement matrix.
- Both estimates use the live average cell voltage, bounded linear interpolation and independent LiFePO4 reference curves.
- Charging reference points are derived from Renogy's four-cell LiFePO4 charging-voltage table; discharging points use its resting/discharge SOC table.
- These voltage-derived values are comparison indicators and do not replace the DALY BMS coulomb-counted SOC.
- Updated application version, footer and service-worker cache to v1.4.7.
