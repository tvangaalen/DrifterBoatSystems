"""Reads modules.json and the active locations: where each module runs from, with which command and environment.

Used by run_module.py, start_all.ps1 (through `py tools/modules.py plan`) and switch_module.ps1, later by the supervisor.
    py tools/modules.py plan             JSON: per module name, port, location, folder, command, environment
    py tools/modules.py set <m> <loc>    record that module <m> now runs from <loc> (legacy | drifter)
"""
from __future__ import annotations

import json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = json.loads((ROOT / "modules.json").read_text(encoding="utf-8"))
LIVE, DATA = Path(os.path.expandvars(SPEC["live"])), Path(os.path.expandvars(SPEC["data"]))
LOCATIONS = DATA / "locations.json"


def locations() -> dict:
    try: return json.loads(LOCATIONS.read_text(encoding="utf-8"))
    except (OSError, ValueError): return {}


def resolve(name: str, location: str | None = None) -> dict:
    m = SPEC["modules"][name]; loc = location or locations().get(name, "legacy")
    if loc not in ("legacy", "drifter"): raise ValueError(f"{name}: unknown location {loc!r}")
    legacy = Path(os.path.expandvars(m["legacy"]))
    if loc == "legacy":
        folder, env, args, data = legacy, {}, [], legacy
    else:
        folder = (LIVE / m["dir"]).resolve(); env = {"DRIFTER_DATA": str(DATA)}
        data = folder if m.get("runtime_in_code") else DATA / name
        args = [a.replace("{data}", str(data)) for a in m.get("data_args", [])]
    return {"name": name, "title": m["name"], "port": m["port"], "location": loc, "folder": str(folder), "legacy": str(legacy),
            "data": str(data), "command": m["command"] + args, "env": env, "console": bool(m.get("console")), "task": m.get("task"),
            "runtime": m.get("runtime", []), "code_runtime": m.get("code_runtime", []), "requires": m.get("requires", []), "venv": m.get("venv"), "precheck": m.get("precheck")}


def set_location(name: str, location: str) -> None:
    resolve(name, location); loc = locations(); loc[name] = location
    DATA.mkdir(parents=True, exist_ok=True); tmp = LOCATIONS.with_suffix(".tmp")
    tmp.write_text(json.dumps(loc, indent=2), encoding="utf-8"); os.replace(tmp, LOCATIONS)


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["plan"]: print(json.dumps({"live": str(LIVE), "data": str(DATA), "modules": [resolve(n) for n in SPEC["modules"]]}, indent=1))
    elif a[:1] == ["set"] and len(a) == 3: set_location(a[1], a[2]); print(f"{a[1]} -> {a[2]}")
    else: sys.exit(__doc__)
