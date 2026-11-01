# Mastervolt Web App v1.0.10

- Added an automatic high-SoC Float policy with a House Battery threshold of 98%.
- When House SoC is at least 98%, active Charger House, Solar and Alternator charging sources are forced to Float unless already in Float.
- Uses the established Float command/commit pairs: CombiMaster 42/43, Solar 18/19 and Alpha Pro 37/38.
- Each Float request verifies the device charger-state field reaches state 3 and retries failures with a 20-second cooldown.
- Inactive, stopped or unavailable sources are not switched on by the policy; Float is enforced as soon as they enter an active Bulk or Absorption state.
- Policy state and per-source results are exposed in `/api/energy` as `high_soc_float_policy`.
- Updated application/footer version and PWA cache to v1.0.10.

All existing hardware-verified ON/OFF sequences, DC-balance calculations and Engine ECU safety behavior remain unchanged.
