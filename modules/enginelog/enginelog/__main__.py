"""python -m enginelog: the engine log on http://127.0.0.1:8097 (ENGINELOG_BIND may name another private address). Started
by drifterd, which gives it DRIFTER_DATA and DRIFTER_TOKEN; the log is <DRIFTER_DATA>\\enginelog\\log.json (or ./data).
The engine data comes from the Orca Core at ENGINELOG_CORE (default 192.168.1.124), read-only; ENGINELOG_CORE=off: none."""
import os
from pathlib import Path

from enginelog import VERSION        # first: it puts the repository root (common/) on sys.path
from common import logs
from common.service import run
from enginelog.api import create_app
from enginelog.engine import Engine
from enginelog.store import Store

if __name__ == "__main__":
    logs.setup()
    data = Path(os.environ["DRIFTER_DATA"]) / "enginelog" if os.environ.get("DRIFTER_DATA") else Path(__file__).resolve().parents[1] / "data"
    print(f"Engine log {VERSION}: API on port 8097 for the Drifter gateway; log in {data}", flush=True)
    store, core = Store(data / "log.json"), os.environ.get("ENGINELOG_CORE", "192.168.1.124").strip()
    engine = Engine(store)
    if core.lower() != "off": engine.start(core)
    run(create_app(store, engine), 8097, "ENGINELOG_BIND")
