"""Mastervolt Energy: a private web app that monitors and controls a boat's Mastervolt and DALY equipment.

Package layout (see docs/MANUAL.md, chapter "Architecture"):

* `masterbus`  - the Mastervolt MasterBus USB Link: protocol, device I/O, controls, energy model, Float protection
* `bluetooth`  - DALY BMS and balancer links over Bluetooth LE, and the radio arbitration between them
* `history`    - the SQLite measurement history, its server-side chart cache and the energy totals
* `reports`    - the battery health report
* `api`        - the FastAPI routes
* `soc`        - House SOC and cell-voltage helpers that feed Float protection
"""

__version__ = "2.1.2"
