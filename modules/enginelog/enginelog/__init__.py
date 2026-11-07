"""Engine log: diesel fuel fills and engine maintenance, the API behind the Engine log module of the Drifter app.
FastAPI on 127.0.0.1:8097 with Drifter's module contract (common/service.py).

    store.py    the log (data/log.json): fuel fills, maintenance entries and engine alarms, validated, written atomically
    engine.py   live engine data from the Orca Core 2 (read-only): engine hours and the engine alarms
    api.py      the HTTP API: read the log, create, change and delete entries
"""
import sys
from pathlib import Path

VERSION = "1.0.0"
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # the repository root: common/ (shared with the Drifter gateway)
