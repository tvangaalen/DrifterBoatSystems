"""Runs one module from its active location (modules.json + locations.json) without a window and waits for it.

For scheduled tasks and start_all.ps1:  pyw tools\\run_module.py <module>
Sets DRIFTER_DATA in the Drifter location, so the module keeps its runtime files in <data>\\<module>. Output goes to
<data folder>\\logs\\<module>.console.log. Exit code = the module's, so a task can restart it.
"""
import os, subprocess, sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import modules  # noqa: E402

m = modules.resolve(sys.argv[1])
logs = Path(m["data"]) / "logs"; logs.mkdir(parents=True, exist_ok=True)
with open(logs / f"{m['name']}.console.log", "a", encoding="utf-8") as out:
    out.write(f"\n--- {datetime.now():%Y-%m-%d %H:%M:%S} start {m['location']}: {' '.join(m['command'])} in {m['folder']}\n"); out.flush()
    cmd = m["command"][:]; exe = Path(m["folder"]) / cmd[0]
    if exe.exists(): cmd[0] = str(exe)              # .venv\Scripts\python.exe relative to the module folder
    r = subprocess.run(cmd, cwd=m["folder"], env={**os.environ, **m["env"]}, stdout=out, stderr=subprocess.STDOUT,
                       stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
sys.exit(r.returncode)
