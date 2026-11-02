"""common/proc.py's kill-on-close job objects: when the process holding the job is killed (drifterd, or the fallback runner), the
server it started, and whatever that server started, must die with it. Task Scheduler runs a task inside a job that
lets children break away silently; the test builds such a job around the runner. Throw-away Python processes only."""
import subprocess, sys, tempfile, time, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNNER = f"""
import ctypes, subprocess, sys, time
from ctypes import wintypes
sys.path.insert(0, r"{ROOT}")
from common import proc
k = ctypes.WinDLL("kernel32"); k.CreateJobObjectW.restype = wintypes.HANDLE; k.GetCurrentProcess.restype = wintypes.HANDLE
if sys.argv[2] == "silent":                      # like Task Scheduler: an outer job with JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK
    outer = k.CreateJobObjectW(None, None); info = proc._Extended(); info.BasicLimitInformation.LimitFlags = 0x1000
    k.SetInformationJobObject(wintypes.HANDLE(outer), 9, ctypes.byref(info), ctypes.sizeof(info))
    k.AssignProcessToJobObject(wintypes.HANDLE(outer), wintypes.HANDLE(k.GetCurrentProcess()))
job = proc.new_job(); proc.join_job(job)
server = ("import subprocess, sys, time; g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']);"
          "open(sys.argv[1], 'w').write(str(g.pid)); time.sleep(60)")
p = proc.start_in_job(job, [sys.executable, "-c", server, sys.argv[1] + ".g"])
open(sys.argv[1], "w").write(f"{{p.pid}} {{bool(job)}}")
time.sleep(60)
"""


def alive(pid):
    return str(pid) in subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout


def wait_file(f):
    for _ in range(100):
        if f.exists() and f.read_text(): return f.read_text()
        time.sleep(0.1)
    raise AssertionError(f"{f.name} not written")


class JobTest(unittest.TestCase):
    def check(self, mode):
        with tempfile.TemporaryDirectory() as d:
            info = Path(d) / "child.txt"
            runner = subprocess.Popen([sys.executable, "-c", RUNNER, str(info), mode])
            pid, joined = wait_file(info).split(); grandchild = wait_file(Path(str(info) + ".g"))
            self.assertEqual(joined, "True", "this Windows refused the job object")
            self.assertTrue(alive(pid) and alive(grandchild))
            runner.kill(); runner.wait()                   # TerminateProcess, like Task Scheduler
            for _ in range(50):
                if not alive(pid) and not alive(grandchild): break
                time.sleep(0.1)
            self.assertFalse(alive(pid), "the server outlived its runner")
            self.assertFalse(alive(grandchild), "what the server started outlived the runner")

    def test_plain(self): self.check("plain")
    def test_under_a_silent_breakaway_job_like_task_scheduler(self): self.check("silent")

    def test_venv_launcher(self):
        """The modules run through .venv\\Scripts\\pythonw.exe, a launcher that starts the real python itself. With only an
        inherited job the real python outlived the runner (BoatGuard, 2026-11-01); start_in_job must catch it."""
        with tempfile.TemporaryDirectory() as d:
            subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(Path(d) / "venv")], check=True)
            venv_py, out = str(Path(d) / "venv" / "Scripts" / "pythonw.exe"), Path(d) / "real.txt"
            runner_code = (f"import sys, time; sys.path.insert(0, r'{ROOT}'); from common import proc; job = proc.new_job(); proc.join_job(job);"
                           f"proc.start_in_job(job, [r'{venv_py}', '-c', \"import os, sys, time; open(sys.argv[1], 'w').write(str(os.getpid())); time.sleep(60)\", r'{out}']); time.sleep(60)")
            runner = subprocess.Popen([sys.executable, "-c", runner_code])
            real = wait_file(out); self.assertTrue(alive(real))
            runner.kill(); runner.wait()
            for _ in range(50):
                if not alive(real): break
                time.sleep(0.1)
            self.assertFalse(alive(real), "the real python behind the venv launcher outlived the runner")


if __name__ == "__main__":
    unittest.main()
