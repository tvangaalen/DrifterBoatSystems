"""Reads modules.json: per server its port, folder, command, environment, data folder and health check.

Used by drifterd.py and the tests.
    python tools/modules.py plan     JSON: everything drifterd needs per server
"""
from __future__ import annotations

import json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = json.loads((ROOT / "modules.json").read_text(encoding="utf-8"))
LIVE, DATA = Path(os.path.expandvars(SPEC["live"])), Path(os.path.expandvars(SPEC["data"]))
NAMES = tuple(SPEC["modules"])                       # gateway first: drifterd starts it before the modules
MODULES = tuple(n for n in NAMES if n != "gateway")


def resolve(name: str, live: Path | None = None, data: Path | None = None) -> dict:
    m = SPEC["modules"][name]; live = Path(live or LIVE); base = Path(data or DATA)
    folder = (live / m["dir"]).resolve()
    data_dir = folder if m.get("runtime_in_code") else base / name
    args = [a.replace("{data}", str(data_dir)) for a in m.get("data_args", [])]
    scheme, _, path = (m.get("health") or "none").partition(":")
    return {"name": name, "title": m["name"], "port": m["port"], "folder": str(folder), "data": str(data_dir),
            "command": m["command"] + args, "env": {"DRIFTER_DATA": str(base)}, "requires": m.get("requires", []),
            "health": None if scheme == "none" else (scheme, path), "precheck": m.get("precheck"),
            "log": str(data_dir / "logs" / f"{name}.console.log")}


if __name__ == "__main__":
    if sys.argv[1:] == ["plan"]: print(json.dumps({"live": str(LIVE), "data": str(DATA), "modules": [resolve(n) for n in NAMES]}, indent=1))
    else: sys.exit(__doc__)
