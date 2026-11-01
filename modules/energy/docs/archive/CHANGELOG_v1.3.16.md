# Mastervolt Web App v1.3.16

- Dashboard House Battery SOC is now the average of every available DALY BMS SOC reading. One valid battery is sufficient; unavailable batteries are omitted.
- Dashboard Start Battery and Bow Battery SOC again come exclusively from their own MasterShunts.
- Renamed the Float protection thresholds to **Switch to Float when SOC** and **Switch to Bulk when SOC**.
- Replaced the former current-based Bulk delta with an absolute SOC threshold and require at least 5 percentage points of hysteresis.
- Added matching client and server validation, including an explanatory pop-up for invalid threshold combinations.
- The theoretical Cell average SOC curve now uses 3.60 V per cell as the 100% charging endpoint from the supplied table.
- Updated the application version, footer and service-worker cache to v1.3.16.
