"""Every hardware-free test of Drifter Boat Systems: the gateway and each module's own suite, each in its own folder.

Usage: py tests/run_all.py [quick] [suite ...]   (quick = MasterVolt without its slow simulations; suites: the names below,
default all; tools/ship.py picks them from what changed)
Exit code = number of failed suites. No test touches the boat: fake MasterBus/Bluetooth, simulated Core data, no network.

The suites run side by side (DRIFTER_TEST_JOBS at a time, default 4; 1 = one after the other), the slowest first, each
in its own process at below-normal priority, so the live servers on the boat PC keep the processor when they need it.
No two suites share a fixed port or a file.
"""
import os, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUICK = "quick" in sys.argv[1:]
ONLY = [a for a in sys.argv[1:] if a != "quick"]


def python(module: str) -> str:
    """The module's own .venv when it has one (not in git), else this interpreter."""
    venv = ROOT / "modules" / module / ".venv" / "Scripts" / "python.exe"
    return str(venv) if venv.exists() else sys.executable


SUITES = [  # (name, folder, command)
    ("gateway", ROOT, [sys.executable, "tests/test_gateway.py"]),
    ("supervisor", ROOT, [sys.executable, "tests/test_supervisor.py"]),
    ("common", ROOT, [sys.executable, "tests/test_common.py"]),
    ("privacy-scan", ROOT, [sys.executable, "tests/test_privacy_scan.py"]),
    ("proc", ROOT, [sys.executable, "tests/test_proc.py"]),
    ("drifterd", ROOT, [sys.executable, "tests/test_drifterd.py"]),
    ("verify-live", ROOT, [sys.executable, "tests/test_verify_live.py"]),
    ("watchdog", ROOT, [sys.executable, "tests/test_watchdog.py"]),
    ("backup", ROOT, [sys.executable, "tests/test_backup.py"]),
    ("ship", ROOT, [sys.executable, "tests/test_ship.py"]),
    ("energy", ROOT / "modules/energy", [python("energy"), "-m", "tests.run_all"] + (["quick"] if QUICK else [])),
    ("anchor", ROOT / "modules/anchor", [python("anchor"), "-m", "unittest", "test_anchor_watch", "test_anchor"]),
    ("guard", ROOT / "modules/guard", [python("guard"), "test_core.py"]),
    ("guard-api", ROOT / "modules/guard", [python("guard"), "-m", "unittest", "test_guard"]),
    ("washer", ROOT / "modules/washer", [python("washer"), "-m", "unittest", "test_washer"]),
    ("enginelog", ROOT / "modules/enginelog", [python("enginelog"), "-m", "unittest", "test_enginelog"]),
]

unknown = set(ONLY) - {n for n, _, _ in SUITES}
if unknown: sys.exit(f"unknown suite(s): {', '.join(sorted(unknown))}")
if ONLY: SUITES = [s for s in SUITES if s[0] in ONLY]

SLOWEST_FIRST = {"energy": 0, "anchor": 1, "drifterd": 2, "gateway": 3, "supervisor": 4, "washer": 5}
JOBS = max(1, int(os.environ.get("DRIFTER_TEST_JOBS") or 4))
LOW = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)      # Windows; elsewhere the normal priority


def run(suite):
    name, cwd, cmd = suite; t0 = time.monotonic()
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=LOW)
    return name, r, time.monotonic() - t0


failed, t_all = [], time.monotonic()
with ThreadPoolExecutor(JOBS) as pool:
    for job in as_completed([pool.submit(run, s) for s in sorted(SUITES, key=lambda s: SLOWEST_FIRST.get(s[0], 9))]):
        name, r, took = job.result(); ok = r.returncode == 0
        last = next((ln for ln in reversed((r.stdout + r.stderr).strip().splitlines()) if ln.strip()), "")
        print(f"{'ok  ' if ok else 'FAIL'} {name:10} {took:6.1f} s  {last[:110]}", flush=True)
        if not ok: failed.append(name); print((r.stdout + r.stderr)[-3000:])
for p in ROOT.rglob("__pycache__"):          # the project folders are synced/shared: leave no bytecode behind
    if ".venv" not in p.parts: subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(p)], capture_output=True)
print(f"\n{len(SUITES) - len(failed)}/{len(SUITES)} suites passed in {time.monotonic() - t_all:.0f} s" + (f"; failed: {', '.join(failed)}" if failed else ""))
sys.exit(len(failed))
