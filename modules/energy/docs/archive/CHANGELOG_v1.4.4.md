# Mastervolt Web App v1.4.4

- Corrected Balance current to use the standalone balancer's current byte in response 0x93.
- Applies the hardware-observed 0.01 A scale: 0x55 becomes 0.85 A and 0x32 becomes 0.50 A.
- Stops displaying the unrelated 0x90 pack-current field as balance current.
- Keeps the diagnostics expansion-state fix from v1.4.3.
