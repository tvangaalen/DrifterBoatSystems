# Mastervolt Web App v1.4.22

- Detects whether each individual DALY BMS interprets MOS payload `1` as ON or OFF.
- Determines Charge and Discharge encoding independently because firmware variants may differ.
- Accepts an encoding only after the requested MOS state has been read back successfully.
- Remembers verified encodings in `data/bms_mos_encoding.json` across application restarts.
- Retains the v1.4.21 protection that preserves and verifies the unrelated MOS state.
