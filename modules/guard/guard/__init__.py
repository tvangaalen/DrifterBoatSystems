"""BoatGuard: arms the EZVIZ camera when the owner's phone leaves the boat Wi-Fi, disarms it on return.

    config.py   config.json, checked against a schema
    router.py   presence: the UDR's Wi-Fi station tables over read-only SSH
    camera.py   arming through the EZVIZ cloud (pyezviz) with a saved session
    notify.py   Pushover notifications from a background thread
    core.py     the presence state machine (Guard): only disarms what it armed itself
    api.py      the API for the Drifter app (FastAPI, Drifter's module contract)

    python -m guard run | login | pushover | status | arm | disarm
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # the repository root: common/ (shared with the Drifter gateway)

VERSION = "2.0.0"
