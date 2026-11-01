"""Scenario runner for the pure/deterministic parts: DALY frame decoding, House SOC helpers and the history service.

Like golden_masterbus.py it produces a JSON-able dict that must be identical for the v1.22.2 code (generated once) and
the current code (verified by tests/test_misc_golden.py).
"""

from __future__ import annotations

import hashlib
import json
import random
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path


def jsonable(value):
    return json.loads(json.dumps(value, default=str))


NEW_POINT_KEYS = ("shore_current", "shore_power")  # added in 2.1.0; the 1.22.2 golden file predates them


def without_new(points):
    return [{k: v for k, v in point.items() if k not in NEW_POINT_KEYS} for point in points]


def digest(value):
    """Large structures are compared by length and checksum so the golden file stays small."""
    encoded = json.dumps(value, sort_keys=True, default=str)
    return {"items": len(value), "sha1": hashlib.sha1(encoded.encode()).hexdigest()}


def make_frame(command: int, data: bytes) -> bytes:
    frame = bytearray((0xA5, 0x01, command, 0x08)) + bytearray(data.ljust(8, b"\0")[:8])
    frame.append(sum(frame) & 0xFF)
    return bytes(frame)


def daly_cases(rng: random.Random):
    frames = []
    for command in range(0x90, 0x99):
        for _ in range(12):
            frames.append(make_frame(command, bytes(rng.randrange(256) for _ in range(8))))
    return frames


def realistic_status_frames(rng: random.Random, cells=4, sensors=2, balancing=(2,), alarm_hex="00 00 00 00 00 00 00 00"):
    def u16(v):
        return int(v).to_bytes(2, "big")

    frames = [
        make_frame(0x90, u16(132) + u16(132) + u16(30000 + rng.randrange(-200, 200)) + u16(rng.randrange(0, 1000))),
        make_frame(0x91, u16(3360) + bytes([2]) + u16(3340) + bytes([4])),
        make_frame(0x92, bytes([66, 1, 64, 1])),
        make_frame(0x93, bytes([0, 1, 1, 0]) + int(rng.randrange(100000, 300000)).to_bytes(4, "big")),
        make_frame(0x94, bytes([cells, sensors, 1, 1, 0]) + u16(rng.randrange(0, 500))),
        make_frame(0x95, bytes([1]) + u16(3340 + rng.randrange(20)) + u16(3350) + u16(3360)),
        make_frame(0x95, bytes([2]) + u16(3345) + u16(0) + u16(0)),
        make_frame(0x96, bytes([1, 66, 65, 0, 0, 0, 0, 0])),
        make_frame(0x97, bytes(sum(1 << (n - 1) for n in balancing).to_bytes(6, "little")) + bytes(2)),
        make_frame(0x98, bytes.fromhex(alarm_hex.replace(" ", ""))),
    ]
    return frames


def run_daly(protocol):
    """`protocol` exposes request, write_frame, decode, decode_alarm_bytes, snapshot_from_frames, soc_from_average_mv, curves."""
    rng = random.Random(21)
    out = {
        "requests": [protocol.request(c).hex() for c in range(0x90, 0x99)],
        "writes": [protocol.write_frame(c, bytes(range(n))).hex() for c in (0x21, 0xD9, 0xDA) for n in (0, 1, 6, 8, 9)],
    }
    out["decode"] = [[command, values] for command, values in (protocol.decode(frame) for frame in daly_cases(rng))]
    out["alarms"] = [
        protocol.decode_alarm_bytes(h)
        for h in ("", "00 00 00 00 00 00 00 00", "FF FF FF FF FF FF FF 05", "01 02 04 08 10 20 40 80", "zz", "80")
    ]
    out["soc"] = [
        [
            mv,
            round(protocol.soc_from_average_mv(mv, protocol.charging_points), 6),
            round(protocol.soc_from_average_mv(mv, protocol.discharging_points), 6),
        ]
        for mv in range(2400, 3700, 25)
    ]
    snapshots = []
    for variant in range(6):
        frames = realistic_status_frames(
            rng,
            cells=4 if variant % 2 else 3,
            balancing=[(1,), (2, 4), ()][variant % 3],
            alarm_hex=["00 00 00 00 00 00 00 00", "01 00 00 00 00 00 00 00", "00 40 00 00 00 00 00 03"][variant % 3],
        )
        snap = protocol.snapshot_from_frames(f"BATTERY {variant % 3 + 1}", "DL-TEST", frames)
        snap.pop("captured_at", None)
        snapshots.append(snap)
    out["snapshots"] = snapshots
    try:
        protocol.snapshot_from_frames("BATTERY 1", "DL", [make_frame(0x95, bytes(8))])
        out["incomplete"] = "no error"
    except RuntimeError as exc:
        out["incomplete"] = str(exc)
    return out


def run_house_soc(module):
    names = ("BATTERY 1", "BATTERY 2", "BATTERY 3")
    now = datetime(2026, 10, 2, 12, 0, 0, tzinfo=UTC).timestamp()
    rng = random.Random(4)
    out = {"max_age": [module.max_age_seconds(v) for v in (5, 30, 60, 300, "x", None)], "soc": [], "cells": [], "float": []}
    for case in range(40):
        batteries = {}
        for name in names:
            if rng.random() < 0.15:
                continue
            age = rng.choice([1, 20, 100, 119, 121, 400, None])
            stamp = None if age is None else datetime.fromtimestamp(now - age, UTC).isoformat()
            cells = [rng.randrange(3200, 3600) for _ in range(rng.choice([0, 4, 4, 4]))]
            batteries[name] = {
                "captured_at": stamp,
                "state_of_charge_percent": rng.choice([None, "x", -1, 50.5, 100, 101, 77.7]),
                "cells_mv": cells,
                "cell_spread_mv": rng.choice([None, 12, 40]),
            }
        out["soc"].append(module.house_soc(batteries, now, module.max_age_seconds(30)))
        out["cells"].append(module.cell_voltage_stats(batteries, now, module.max_age_seconds(30)))
    for enabled in (True, False):
        for latched in (True, False):
            for cell in (None, 3300, 3400, 3420, 3421, 3499, 3500, 3600):
                out["float"].append([enabled, latched, cell, list(module.float_decision(enabled, latched, cell, 3500.0, 3420.0))])
    return jsonable(out)


def run_history(HistoryService):
    tmp = Path(tempfile.mkdtemp()) / "history.sqlite3"
    service = HistoryService(tmp)
    rng = random.Random(9)
    start = datetime(2026, 10, 1, 8, 0, 0, tzinfo=UTC)
    out = {}
    for second in range(0, 3 * 3600, 10):
        stamp = (start + timedelta(seconds=second)).isoformat()
        alt_running = (second // 3600) % 2 == 0
        payload = {
            "sources": {
                "shore": {"power": 0, "voltage": 230.0, "connected": True},
                "charger_house": {"power": max(0.0, 500 + rng.uniform(-50, 50)), "current": 35.0},
                "alternator": {
                    "power": 800.0 if alt_running else 0.0,
                    "current": 60.0 if alt_running else 0.0,
                    "temperature": 28.0,
                    "running": alt_running,
                },
                "solar": {"power": rng.uniform(0, 200), "current": 3.0, "panel_voltage": 100.0},
            },
            "consumers": {
                "inverter": {"power": rng.uniform(0, 300), "current": 20.0, "inverting": True, "supporting": False},
                "charger_start": {"power": 10.0, "current": 0.8},
                "charger_bow": {"power": 5.0, "current": 0.4},
                "engine_ecu": {"power": 4.0, "current": 0.3},
                "alternator_field": {"power": 20.0, "current": 1.5},
                "other_dc": {"power": rng.uniform(50, 150), "current": 8.0},
                "house_ac": {"power": 100.0, "output_frequency": 50.0},
            },
        }
        service.record("dashboard", payload, None, stamp)
        if second % 30 == 0:
            for index, name in enumerate(("BATTERY 1", "BATTERY 2", "BATTERY 3")):
                cells = [3300 + index * 5 + rng.randrange(0, 12) for _ in range(4)]
                alarm = ["Cell voltage difference – level 1"] if (second // 600) % 7 == 3 and index == 1 else []
                service.record(
                    "bms",
                    {
                        "battery": name,
                        "pack_voltage_v": 13.2,
                        "current_a": rng.uniform(-40, 60),
                        "remaining_capacity_ah": 200 + second / 100.0,
                        "cells_mv": cells,
                        "cell_spread_mv": max(cells) - min(cells),
                        "alarms": alarm,
                        "charge_mosfet_on": (second // 900) % 5 != 3,
                        "discharge_mosfet_on": True,
                    },
                    name,
                    stamp,
                )
        if second % 90 == 0:
            service.record("balancer", {"state": "connected", "status": {"cell_delta_mv": 8}, "error": None}, "DL-BAL1", stamp)
    out["count"] = service.count()
    out["latest"] = service.latest(3)
    series = service.bms_series(100)
    out["bms_series"] = {
        "earliest_id": series["earliest_id"],
        "latest_id": series["latest_id"],
        "points": digest(series["points"]),
        "first": series["points"][0],
        "last": series["points"][-1],
    }
    series = service.dashboard_series(2000)
    out["dashboard_series"] = {
        "earliest_id": series["earliest_id"],
        "latest_id": series["latest_id"],
        "points": digest(without_new(series["points"])),
        "first": without_new(series["points"][:1])[0],
        "last": without_new(series["points"][-1:])[0],
    }
    out["refresh"] = service.refresh_chart_cache()
    for hours in (0.25, 1, 3, 12):
        data = service.chart_data(hours)
        out[f"chart_{hours}"] = {
            key: (value if key in ("bms_count", "dashboard_count", "latest", "cutoff") else digest([p["id"] for p in value]))
            for key, value in data.items()
        }
    for first, last in (
        ("2026-10-01T08:00:00Z", "2026-10-01T11:00:00Z"),
        ("2026-10-01T08:30:00Z", "2026-10-01T10:15:30Z"),
        ("2026-10-01T10:00:00+00:00", "2026-10-01T10:00:30+00:00"),
    ):
        totals = service.contributions(first, last)
        totals.pop("shore", None)  # added in 2.1.0 (tests/test_history.py covers it); the 1.22.2 golden file predates it
        out[f"contrib_{first}_{last}"] = totals
    for bad in (("x", "y"), ("2026-10-01T10:00:00Z", "2026-10-01T09:00:00Z")):
        try:
            service.contributions(*bad)
            out[f"bad_{bad[0]}"] = "no error"
        except ValueError as exc:
            out[f"bad_{bad[0]}"] = str(exc)
    status = service.db_status(31)
    out["status"] = {key: status[key] for key in ("records", "by_source", "oldest", "newest", "retention_days", "chart_cache")}
    out["export_head"] = [line for _, line in zip(range(3), service.json_lines())]
    out["export_lines"] = sum(1 for _ in service.json_lines())
    out["pruned"] = service.prune(365)
    return jsonable(out)
