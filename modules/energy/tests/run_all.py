"""Run every hardware-free test and print one line per test.

    py -m tests.run_all            # all of them (about two minutes)
    py -m tests.run_all quick      # skip the slow simulations (workers, balancers)

Each test module is run in its own process (`py -m tests.test_x`), exactly as it would be by hand, so a hang or a crash in
one cannot affect another; ENERGY_TEST_JOBS of them side by side (default 4; 1 = one after the other), the slowest first,
at below-normal priority so a live server on the same PC keeps the processor. The exit code is the number of failed tests. None of these tests touches hardware: the MasterBus
USB Link, Bluetooth and the live database are simulated or temporary.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
SLOW = {"test_bms_workers", "test_balancers", "test_report_service"}
SLOWEST_FIRST = ("test_history", "test_bms_workers", "test_misc_golden", "test_balancers", "test_report_service", "test_app_integration")
LOW = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)  # Windows; elsewhere the normal priority


def _run(name: str):
    began = time.monotonic()
    result = subprocess.run(
        [sys.executable, "-W", "ignore", "-B", "-m", f"tests.{name}"],
        cwd=HERE.parent,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=LOW,
    )
    return name, result, time.monotonic() - began


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    quick = "quick" in argv
    modules = sorted(path.stem for path in HERE.glob("test_*.py") if not (quick and path.stem in SLOW))
    modules.sort(key=lambda n: SLOWEST_FIRST.index(n) if n in SLOWEST_FIRST else len(SLOWEST_FIRST))
    failures = 0
    started = time.monotonic()
    with ThreadPoolExecutor(max(1, int(os.environ.get("ENERGY_TEST_JOBS") or 4))) as pool:
        for job in as_completed([pool.submit(_run, name) for name in modules]):
            name, result, took = job.result()
            output = (result.stdout + result.stderr).strip().splitlines()
            last = output[-1] if output else ""
            status = "ok  " if result.returncode == 0 else "FAIL"
            print(f"{status} {name:<28} {took:5.1f} s  {last[:100]}", flush=True)
            if result.returncode:
                failures += 1
                print("\n".join("     " + line for line in output[-15:]))
    print(f"\n{len(modules) - failures}/{len(modules)} test modules passed in {time.monotonic() - started:.0f} s")
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
