"""run_module's kill-on-close job: when the runner is killed (as Task Scheduler does on Stop-ScheduledTask), the
server it started must die with it. Uses only throw-away Python processes."""
import subprocess, sys, tempfile, time, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNNER = f"""
import subprocess, sys, time
sys.path.insert(0, r"{ROOT / 'tools'}")
import run_module
job = run_module.join_kill_on_close_job()
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
open(sys.argv[1], "w").write(f"{{child.pid}} {{bool(job)}}")
time.sleep(60)
"""


def alive(pid):
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
    return str(pid) in out


class JobTest(unittest.TestCase):
    def test_child_dies_with_the_runner(self):
        with tempfile.TemporaryDirectory() as d:
            info = Path(d) / "child.txt"
            runner = subprocess.Popen([sys.executable, "-c", RUNNER, str(info)])
            for _ in range(100):
                if info.exists() and info.read_text(): break
                time.sleep(0.1)
            pid, joined = info.read_text().split()
            self.assertEqual(joined, "True", "this Windows refused the job object")
            self.assertTrue(alive(pid))
            runner.kill(); runner.wait()                   # TerminateProcess, like Task Scheduler
            for _ in range(50):
                if not alive(pid): break
                time.sleep(0.1)
            self.assertFalse(alive(pid), "the child outlived its runner")


if __name__ == "__main__":
    unittest.main()
