"""Every hardware-free test of Drifter Boat Systems: the gateway and each module's own suite, each in its own folder.

Usage: py tests/run_all.py [quick]   (quick = MasterVolt without its slow simulations)
Exit code = number of failed suites. No test touches the boat: fake MasterBus/Bluetooth, simulated Core data, no network.
"""
import subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUICK = "quick" in sys.argv[1:]


def python(module: str) -> str:
    """The module's own .venv when it has one (not in git), else this interpreter."""
    venv = ROOT / "modules" / module / ".venv" / "Scripts" / "python.exe"
    return str(venv) if venv.exists() else sys.executable


SUITES = [  # (name, folder, command)
    ("gateway", ROOT, [sys.executable, "tests/test_gateway.py"]),
    ("supervisor", ROOT, [sys.executable, "tests/test_supervisor.py"]),
    ("energy", ROOT / "modules/energy", [python("energy"), "-m", "tests.run_all"] + (["quick"] if QUICK else [])),
    ("anchor", ROOT / "modules/anchor", [python("anchor"), "-m", "unittest", "test_anchor_watch"]),
    ("guard", ROOT / "modules/guard", [python("guard"), "boatguard_self_test.py"]),
    ("washer", ROOT / "modules/washer", [python("washer"), "-m", "py_compile", "viomi_web_english_v58.py"]),   # no test suite yet
]

failed = []
for name, cwd, cmd in SUITES:
    t0 = time.monotonic()
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok = r.returncode == 0
    last = next((ln for ln in reversed((r.stdout + r.stderr).strip().splitlines()) if ln.strip()), "")
    print(f"{'ok  ' if ok else 'FAIL'} {name:10} {time.monotonic() - t0:6.1f} s  {last[:110]}")
    if not ok: failed.append(name); print((r.stdout + r.stderr)[-3000:])
for p in ROOT.rglob("__pycache__"):          # the project folders are synced/shared: leave no bytecode behind
    if ".venv" not in p.parts: subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(p)], capture_output=True)
print(f"\n{len(SUITES) - len(failed)}/{len(SUITES)} suites passed" + (f"; failed: {', '.join(failed)}" if failed else ""))
sys.exit(len(failed))
