"""Fallback runner: starts one server without a window and waits for it. Only used by the scheduled task
DrifterBoatSystems that tools/install_service.ps1 puts back when the Drifter service does not work (-Remove, or the
automatic way back during the install); normally drifterd.py runs every server.

    pythonw tools\\run_module.py <module>

Output goes to <data>\\logs\\<module>.console.log. The runner and the server share a kill-on-close job object, so stopping
the task also stops the server. Exit code = the server's.
"""
import os, subprocess, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
import modules  # noqa: E402
from common import proc  # noqa: E402


def main(name):
    m = modules.resolve(name); f = Path(m["log"]); f.parent.mkdir(parents=True, exist_ok=True); proc.rotate(f)
    job = proc.new_job()
    if job: proc.join_job(job)
    with open(f, "a", encoding="utf-8") as out:
        out.write(f"\n--- {datetime.now():%Y-%m-%d %H:%M:%S} start (task): {' '.join(m['command'])} in {m['folder']}\n"); out.flush()
        cmd = m["command"][:]; exe = Path(m["folder"]) / cmd[0]
        if exe.exists(): cmd[0] = str(exe)
        p = proc.start_in_job(job, cmd, cwd=m["folder"], env={**os.environ, **m["env"]}, stdout=out, stderr=subprocess.STDOUT,
                              stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        return p.wait()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
