# Mastervolt Web App v1.4.23

- Fixed the adaptive DALY MOS retry: when the previously learned payload does not change the requested MOS state, the second attempt now uses the opposite payload.
- The alternative attempt still controls only the selected MOS command; Charge retries never send a Discharge command.
- The encoding is updated only after the requested state is read back successfully.
- No fallback that cycles or changes Discharge has been introduced.
