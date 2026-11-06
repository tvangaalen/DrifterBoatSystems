"""Builds the Python environments from uv.lock on the python.org Python 3.12: the gateway's .venv (stdlib only) and
modules/<name>/.venv with that module's dependency group. Exactly the locked versions, nothing else.

    py -3.12 tools/sync_envs.py                      every environment, in place (development; the servers must not run)
    py -3.12 tools/sync_envs.py --into .venv-next    build next to the running ones (live)
    py -3.12 tools/sync_envs.py --swap <module>      live: ask Drifter to restart the module (same pre-checks as the System
                                                     page); between stop and start the supervisor puts .venv-next in place.
                                                     The gateway's own .venv: stop its task, rename, start it.

Needs uv (`py -3.12 -m pip install --user uv`). The Microsoft Store Python is refused: it hung at boot in session 0.
"""
from __future__ import annotations

import os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENVS = {"gateway": (ROOT, None), "energy": (ROOT / "modules/energy", "energy"), "anchor": (ROOT / "modules/anchor", "anchor"),
        "guard": (ROOT / "modules/guard", "guard"), "washer": (ROOT / "modules/washer", "washer"),
        "enginelog": (ROOT / "modules/enginelog", "enginelog")}


def python312() -> str:
    exe = Path(sys.executable).resolve()
    if "WindowsApps" in str(exe) or sys.version_info[:2] != (3, 12):
        raise SystemExit(f"run this with the python.org Python 3.12 (py -3.12), not {exe}")
    return str(exe)


def sync(name: str, into: str = ".venv") -> Path:
    folder, group = ENVS[name]; target = folder / into
    cmd = [sys.executable, "-m", "uv", "sync", "--frozen", "--no-install-project", "--no-default-groups", "--python", python312()]
    if group: cmd += ["--only-group", group]
    env = {**os.environ, "UV_PROJECT_ENVIRONMENT": str(target)}
    print(f"{name:8} -> {target}", flush=True)
    subprocess.run(cmd, cwd=ROOT, env=env, check=True)
    return target


def swap(name: str) -> None:
    """Live: restart the module through the gateway; the supervisor swaps .venv-next in between stop and start (it runs
    in the servers' session, which another logon session may not stop)."""
    import json, ssl, urllib.error, urllib.request
    if name == "gateway": raise SystemExit("the gateway's .venv is swapped while its task is stopped (README, Python environments)")
    if not (ENVS[name][0] / ".venv-next").exists(): raise SystemExit(f"{ENVS[name][0] / '.venv-next'} missing: build it first with --into .venv-next")
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    ctx = ssl.create_default_context(cafile=cfg.get("ca_file")) if cfg.get("certfile") else None
    url = f"{'https' if ctx else 'http'}://{cfg['bind']}:{cfg['port']}/api/supervisor/restart"
    req = urllib.request.Request(url, data=json.dumps({"module": name}).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Drifter-Request": "1"})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=20) as r: print(f"{name}: restart requested ({r.status}); watch the System page")
    except urllib.error.HTTPError as e: raise SystemExit(f"{name}: refused: {json.loads(e.read() or b'{}').get('error', e.code)}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["--swap"]: swap(a[1]); sys.exit()
    into = a[a.index("--into") + 1] if "--into" in a else ".venv"
    only = [x for x in a if x in ENVS]
    for n in only or ENVS: sync(n, into)
