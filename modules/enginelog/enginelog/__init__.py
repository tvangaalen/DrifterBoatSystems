"""Engine log: diesel fuel fills and engine maintenance, the API behind the Engine log module of the Drifter app.
FastAPI on 127.0.0.1:8097 with Drifter's module contract (common/service.py).

    store.py    the log (data/log.json): fuel fills and maintenance entries, validated, written atomically
    lookup.py   country and the nearest marina for a position (OpenStreetMap: Nominatim and Overpass), on request only
    api.py      the HTTP API: read the log, create, change and delete entries, look up a position
"""
import sys
from pathlib import Path

VERSION = "1.0.0"
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # the repository root: common/ (shared with the Drifter gateway)
