# Mastervolt Web App v1.3.11

- Aligned `All charge ON` and `All discharge ON` with the corresponding per-battery control rows.
- Moved `All charge OFF` and `All discharge OFF` to a separate full-width bottom row.
- Changed the Bulk-resume delta from SOC percentage points to an absolute House Battery discharge-current threshold in amperes.
- Indented the three Float protection settings and added a visual guide line to show their relationship.
- Made the Float protection ON/OFF button as wide as the setting inputs.
- Placed setting units directly beside their input fields.
- Restored every vertical Measurement-table separator using explicit row-end markers instead of position counting.
- Increased DALY discovery time, added a longer pause between sequential persistent connections, and moved Battery 3 ahead of Battery 2 so a stalled Battery 2 handshake cannot starve Battery 3.
- Updated the application footer and service-worker cache to v1.3.11.
