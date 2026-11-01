"""Non-hardware self-test for battery_health.py using a synthetic history database.

Scenario (48 h, one BMS sample every 30 s): Battery 1 has a bad cell-2 connection (6 mOhm excess,
carries only 22% of the bank current) until hour 24, when it is "fixed". Battery 1 also had five
overvoltage/alarm samples at hour 10. Battery 2 loses Bluetooth for one hour. Battery 3 is healthy.
"""

import argparse
import hashlib
import json
import random
import sqlite3
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mastervolt.reports import battery_health as bh

HOURS, FIX_H = 48, 24
T0 = datetime(2026, 9, 10, 0, 0, tzinfo=UTC)


def build(path, t0=T0):
    con = sqlite3.connect(path)
    con.execute(
        "create table measurements (id integer primary key, captured_at text not null, source text not null, device text, payload text not null)"
    )
    rnd = random.Random(1)
    rows = []
    bank = 6.0
    for step in range(HOURS * 120):
        t = t0 + timedelta(seconds=30 * step)
        h = step / 120
        iso = t.isoformat()
        if step % 20 == 0:  # the bank load changes every 10 minutes (real load steps)
            bank = rnd.uniform(-15, 30)
        fixed = h >= FIX_H
        share = {1: 0.33 if fixed else 0.22, 2: 0.335 if fixed else 0.39, 3: 0.335 if fixed else 0.39}
        for b in (1, 2, 3):
            if b == 2 and 30 <= h < 31:
                continue
            i = round(bank * share[b], 1)
            r2 = 0.4 if (b != 1 or fixed) else 6.0
            cells = [round(3300 + i * 0.4 + rnd.uniform(-1, 1)) for _ in range(4)]
            cells[1] = round(3300 + i * r2 + rnd.uniform(-1, 1))
            if b == 2:
                cells[1] -= 17  # static offset, e.g. a cell the balancer keeps bleeding: must not count
            alarms = []
            if b == 1 and 10 <= h < 10 + 5 * 30 / 3600:
                cells[1], alarms = 3700, ["Cell voltage high – level 2"]
            rows.append(
                (
                    iso,
                    "bms",
                    f"BATTERY {b}",
                    json.dumps(
                        {
                            "state": "connected",
                            "battery": f"BATTERY {b}",
                            "captured_at": iso,
                            "pack_voltage_v": 13.2,
                            "current_a": i,
                            "state_of_charge_percent": 60.0,
                            "remaining_capacity_ah": 192.0,
                            "temperatures_c": [25],
                            "cells_mv": cells,
                            "cell_spread_mv": max(cells) - min(cells),
                            "charge_mosfet_on": True,
                            "discharge_mosfet_on": True,
                            "balancing_cells": [],
                            "alarms": alarms,
                            "cycles": 10 + b,
                        }
                    ),
                )
            )
        if step % 2 == 0:
            rows.append(
                (
                    iso,
                    "dashboard",
                    None,
                    json.dumps(
                        {
                            "storage": {
                                "house": {"current": round(bank, 1), "soc": 60.0, "temperature": 25},
                                "start": {"voltage": 12.9, "current": 0.0, "soc": 100},
                                "bow": {"voltage": 26.0, "current": 0.0, "soc": 100},
                            }
                        }
                    ),
                )
            )
            for k in (1, 2, 3):
                rows.append(
                    (
                        iso,
                        "balancer",
                        f"DL-BAL{k}",
                        json.dumps(
                            {
                                "state": "connected",
                                "status": {
                                    "balance_active": False,
                                    "cells_mv": [3300] * 4,
                                    "cell_delta_mv": 3,
                                    "temperatures_c": [35],
                                    "reported_current_a": 0.0,
                                    "alarms": [],
                                },
                            }
                        ),
                    )
                )
    con.executemany("insert into measurements (captured_at, source, device, payload) values (?,?,?,?)", rows)
    con.commit()
    con.close()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    with tempfile.TemporaryDirectory(prefix="bat health ") as tmp:  # folder name with a space, like Google Drive
        db = Path(tmp) / "history.sqlite3"
        build(db)
        before_hash = sha(db)
        data = bh.load_history(db)
        assert set(data["bms"]) == {"BATTERY 1", "BATTERY 2", "BATTERY 3"}
        print("Loading from a path with spaces (read-only URI): OK")

        split = (T0 + timedelta(hours=FIX_H)).timestamp()
        before, after = bh.analyse_window(data, None, split), bh.analyse_window(data, split)

        ex = before["metrics"]["BATTERY 1"]["excess"]
        assert ex["worst"] == 2 and 5.0 <= ex["worst_mohm"] <= 7.0, ex
        for n in ("BATTERY 2", "BATTERY 3"):
            assert before["metrics"][n]["excess"]["worst_mohm"] < 1.0, before["metrics"][n]["excess"]
        assert after["metrics"]["BATTERY 1"]["excess"]["worst_mohm"] < 1.0
        print(
            f"Bad-connection detection: cell {ex['worst']} {ex['worst_mohm']:+.1f} mOhm before, "
            f"{after['metrics']['BATTERY 1']['excess']['worst_mohm']:+.1f} after: OK"
        )

        sb, sa = bh.share_median(before["shares"]), bh.share_median(after["shares"])
        assert abs(sb["BATTERY 1"] - 0.22) < 0.02 and abs(sb["BATTERY 2"] - 0.39) < 0.02, sb
        assert all(abs(v - 1 / 3) < 0.02 for v in sa.values()), sa
        print(f"Current sharing: {sb['BATTERY 1']*100:.0f}% before, {sa['BATTERY 1']*100:.0f}% after: OK")

        m1 = before["metrics"]["BATTERY 1"]
        assert m1["over"] == 5 and m1["alarm_samples"] == 5 and m1["max_cell"] == 3700, (m1["over"], m1["alarm_samples"])
        assert before["verdicts"]["BATTERY 1"][0] == "CRITICAL"
        assert before["verdicts"]["BATTERY 3"][0] == "OK"
        assert after["verdicts"]["BATTERY 1"][0] == "OK", after["verdicts"]["BATTERY 1"]
        print("Verdicts (B1 CRITICAL before / OK after, B3 OK): OK")

        full = bh.analyse_window(data)
        gaps = full["metrics"]["BATTERY 2"]["gaps"]
        assert len(gaps) == 1 and 3500 < gaps[0][1] - gaps[0][0] < 3700, gaps
        assert not full["metrics"]["BATTERY 1"]["gaps"] and not full["metrics"]["BATTERY 3"]["gaps"]
        print("Battery-specific Bluetooth gap found only for Battery 2: OK")

        args = argparse.Namespace(recent_hours=6, split_ts=split)
        text = bh.report(data, [], args)
        for needle in (
            "# Battery health report",
            "## Verdict",
            "CRITICAL",
            "Before / after",
            "Worst cell per day",
            "## Balancers",
            "## Start and Bow",
        ):
            assert needle in text, needle
        out = Path(tmp) / "report.md"
        bh.main(
            [
                "--db",
                str(db),
                "--recent-hours",
                "6",
                "--split",
                (T0 + timedelta(hours=FIX_H)).astimezone().strftime("%Y-%m-%d %H:%M"),
                "--out",
                str(out),
            ]
        )
        assert out.exists() and "Battery health report" in out.read_text(encoding="utf-8")
        print("Report rendering and CLI: OK")

        assert sha(db) == before_hash, "database was modified"
        print("Database untouched (read-only): OK")
    print("All battery health checks: OK")


if __name__ == "__main__":
    main()
