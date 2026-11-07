"""python -m enginelog: the engine log on http://127.0.0.1:8097 (ENGINELOG_BIND may name another private address). Started
by drifterd, which gives it DRIFTER_DATA and DRIFTER_TOKEN; the log is <DRIFTER_DATA>\\enginelog\\log.json (or ./data).
The live engine data and hours come from the Orca Core at ENGINELOG_CORE (default 192.168.1.124), read-only; the engine
alarms from the YDEN-02 at ENGINELOG_YDEN (default 192.168.1.110), listen only. "off" = without that one."""
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
    store = Store(data / "log.json")
    host = lambda name, default: None if (v := os.environ.get(name, default).strip()).lower() == "off" else v
    engine = Engine(store)
    engine.start(host("ENGINELOG_CORE", "192.168.1.124"), host("ENGINELOG_YDEN", "192.168.1.110"))
    run(create_app(store, engine), 8097, "ENGINELOG_BIND")
