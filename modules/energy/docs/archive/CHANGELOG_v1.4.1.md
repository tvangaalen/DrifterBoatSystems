# Mastervolt Web App v1.4.1

- Confirmed the three balancers are monitored directly through `DL-BAL1`, `DL-BAL2` and `DL-BAL3`; no BMS UART link is assumed.
- Reassembles and validates DALY notification frames received over each balancer's own FFF1 Bluetooth channel.
- Added semantic Balance cards for status, reported current, position, maximum/minimum/average/difference, temperatures, cell count, cycles and individual cell voltages.
- Keeps raw GATT and frame data available in a collapsed diagnostics section rather than presenting it as the primary UI.
- Device discovery now accepts the configured name as a prefix/substring so firmware-added suffixes do not prevent connection.
- Uses only read-only DALY status requests; no balancer configuration is changed.
