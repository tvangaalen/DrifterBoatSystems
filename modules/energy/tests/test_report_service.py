"""Non-hardware self-test for the report service: runs the battery health report module on a synthetic history."""

import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mastervolt.reports import service as rs
from tests.test_battery_health import HOURS, build


def wait(reports, timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        if reports.status()["state"] != "running":
            return reports.status()
        time.sleep(0.2)
    raise AssertionError("report did not finish")


def make_project(root, with_data=True):
    root.mkdir(parents=True)
    if with_data:
        (root / "data").mkdir()
        build(root / "data" / "history.sqlite3", t0=datetime.now(UTC) - timedelta(hours=HOURS + 1))
    return root


def main():
    with tempfile.TemporaryDirectory(prefix="report svc ") as tmp:  # folder name with a space, like Google Drive
        tmp = Path(tmp)
        good = make_project(tmp / "good")
        reports = rs.BatteryHealthReports(good)
        assert reports.status()["state"] == "idle"

        for bad in (0, 366, -1, "7", None, 1.5, True):
            try:
                reports.start(bad)
                raise AssertionError(f"accepted invalid days {bad!r}")
            except ValueError:
                pass
        print("Invalid day counts rejected: OK")

        first = reports.start(3)
        assert first["state"] == "running" and first["days"] == 3
        try:
            reports.start(3)
            raise AssertionError("a second report was started while one was running")
        except RuntimeError:
            pass
        done = wait(reports)
        assert done["state"] == "done" and not done["error"], done
        md = done["markdown"]
        assert "\r" not in md, "the report must come back with plain line endings (the page renders headings line by line)"
        for needle in ("# Battery health report", "## Verdict", "BATTERY 1", "BATTERY 3"):
            assert needle in md, needle
        assert done["duration_seconds"] is not None and done["finished_at"]
        print(f"Report generated in a separate process ({done['duration_seconds']} s), only one at a time: OK")

        again = reports.start(1)  # the next report can be started after one finishes
        assert again["state"] == "running" and again["markdown"] is None
        assert wait(reports)["state"] == "done"
        print("Second report after the first: OK")

        empty = make_project(tmp / "empty", with_data=False)  # no database -> a clear error, not a crash
        failing = rs.BatteryHealthReports(empty)
        failing.start(7)
        err = wait(failing)
        assert err["state"] == "error" and "History database not found" in err["error"], err
        print("Missing database reported clearly:", err["error"][:60], "... OK")

        missing = rs.BatteryHealthReports(good, script=tmp / "nope.py")
        missing.start(7)
        assert "was not found" in wait(missing)["error"]
        print("Missing script reported clearly: OK")

        slow_script = tmp / "slow.py"
        slow_script.write_text("import time\ntime.sleep(20)\n")
        slow = rs.BatteryHealthReports(good, script=slow_script, timeout_seconds=1)
        slow.start(7)
        assert "longer than 1 s" in wait(slow)["error"]
        print("Timeout stops a runaway report: OK")
    print("All report service checks: OK")


if __name__ == "__main__":
    main()
