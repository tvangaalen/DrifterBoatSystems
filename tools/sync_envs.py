"""Builds the Python environments from uv.lock on the python.org Python 3.12: the gateway's .venv (stdlib only) and
modules/<name>/.venv with that module's dependency group. Exactly the locked versions, nothing else.

    py -3.12 tools/sync_envs.py                      every environment, in place (development; the servers must not run)
    py -3.12 tools/sync_envs.py --into .venv-next    build next to the running ones (live), swapped in by --swap
    py -3.12 tools/sync_envs.py --swap <module>      live: hold, stop the module, .venv -> .venv-old, .venv-next -> .venv,
                                                     release the hold (the supervisor starts it again). gateway: by its task

Needs uv (`py -3.12 -m pip install --user uv`). The Microsoft Store Python is refused: it hung at boot in session 0.
"""
from __future__ import annotations

import os, shutil, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENVS = {"gateway": (ROOT, None), "energy": (ROOT / "modules/energy", "energy"), "anchor": (ROOT / "modules/anchor", "anchor"),
        "guard": (ROOT / "modules/guard", "guard"), "washer": (ROOT / "modules/washer", "washer")}


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
    """Live switch of one module to its freshly built .venv-next (see the module docstring)."""
    folder, _ = ENVS[name]; nxt, cur, old = folder / ".venv-next", folder / ".venv", folder / ".venv-old"
    if not nxt.exists(): raise SystemExit(f"{nxt} missing: build it first with --into .venv-next")
    sys.path.insert(0, str(ROOT / "tools")); import modules as M
    hold = M.DATA / "hold" / name
    if name == "gateway": raise SystemExit("the gateway's .venv is swapped while its task is stopped: see README (Python environments)")
    hold.parent.mkdir(parents=True, exist_ok=True); hold.write_text("swapping Python environment", encoding="utf-8")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "tools/stop_module.ps1"), name],
                           capture_output=True, text=True, timeout=120)
        print(f"{name}: stop: {(r.stdout or r.stderr).strip()}")
        if r.returncode: raise SystemExit(f"{name} did not stop; nothing swapped")
        for _ in range(20):                           # a launcher may hold files for a moment after the server ended
            try:
                if old.exists(): shutil.rmtree(old)
                if cur.exists(): os.replace(cur, old)
                os.replace(nxt, cur); break
            except OSError: time.sleep(1)
        else: raise SystemExit(f"{name}: could not swap the environments (files in use)")
        print(f"{name}: new environment in place ({cur})")
    finally:
        hold.unlink(missing_ok=True); (M.DATA / "starting" / name).unlink(missing_ok=True)
    print(f"{name}: hold released; the supervisor starts it within a few seconds")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["--swap"]: swap(a[1]); sys.exit()
    into = a[a.index("--into") + 1] if "--into" in a else ".venv"
    only = [x for x in a if x in ENVS]
    for n in only or ENVS: sync(n, into)
