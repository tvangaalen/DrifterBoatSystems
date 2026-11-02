"""VIOMI W1 washer controller: the API behind the Washer module of the Drifter app (status, controls, diagnostics and a
server-side schedule). FastAPI on 127.0.0.1:8080 with Drifter's module contract (common/service.py).

    config.py       viomi_config.json, checked against a schema
    device.py       the washer over MIoT (python-miio): properties, actions, the maps of programs and states
    events.py       the controller's event list and the washer's state changes
    schedule.py     the server-side schedule: start or finish at a time, followed until the washer finishes
    diagnostics.py  the startup checks (configuration, network, identity, an authenticated read)
    api.py          the HTTP API (the routes, answers and messages of the Flask controller 3.8, test_api_contract.py)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # the repository root: common/ (shared with the Drifter gateway)

VERSION = "4.0.1"
EXPECTED_MODEL = "viomi.washer.w1"
