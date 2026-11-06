"""python -m enginelog: the engine log on http://127.0.0.1:8097 (ENGINELOG_BIND may name another private address). Started
by drifterd, which gives it DRIFTER_DATA and DRIFTER_TOKEN; the log is <DRIFTER_DATA>\\enginelog\\log.json (or ./data)."""
import os
from pathlib import Path

from enginelog import VERSION        # first: it puts the repository root (common/) on sys.path
from common import logs
from common.service import run
from enginelog.api import create_app
from enginelog.store import Store

if __name__ == "__main__":
    logs.setup()
    data = Path(os.environ["DRIFTER_DATA"]) / "enginelog" if os.environ.get("DRIFTER_DATA") else Path(__file__).resolve().parents[1] / "data"
    print(f"Engine log {VERSION}: API on port 8097 for the Drifter gateway; log in {data}", flush=True)
    run(create_app(Store(data / "log.json")), 8097, "ENGINELOG_BIND")
