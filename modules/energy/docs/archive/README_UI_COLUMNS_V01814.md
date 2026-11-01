# v0.18.14 – electrical column spacing and Storage flow label

- Removed inter-column gaps between AC/DC, voltage, current and watts.
- Kept a small separation after the device-name column and before the control/SoC column.
- Tightened numeric column widths on iPhone while retaining the larger v0.18.12 typography.
- Storage header now labels signed House battery power dynamically:
  - positive: Charging
  - negative: Discharging
  - zero: Idle
- No MasterBus control logic, safety behavior or DC-current calculations changed.
