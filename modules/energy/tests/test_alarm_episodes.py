"""The Alarms chart's episodes (GET /api/history/alarms): a run of samples per battery and alarm type, the level its highest,
ending at the first sample without it; a Bluetooth gap ends it at its last sample; totals per battery and type."""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

from mastervolt.history.totals import EnergyTotals, alarm_type

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


class FakeCache:
    def __init__(self, bms):
        self.dashboard, self.bms, self.lock, self.loaded = [], bms, threading.Lock(), True


def point(i, seconds, battery, alarms):
    return {"id": i, "captured_at": (T0 + timedelta(seconds=seconds)).isoformat(), "battery": battery, "voltage": 13.2, "current": 1.0, "alarms": alarms}


def main():
    assert alarm_type("Cell voltage high – level 2") == ("Cell voltage high", 2)
    assert alarm_type("Fault code 3") == ("Fault code 3", 1)
    high1, high2, temp = "Cell voltage high – level 1", "Cell voltage high – level 2", "Charge temperature low – level 1"
    rows = [
        (0, "BATTERY 1", []), (30, "BATTERY 1", [high1]), (60, "BATTERY 1", [high2, temp]), (90, "BATTERY 1", [high1]), (120, "BATTERY 1", []),
        (150, "BATTERY 1", [high1]), (900, "BATTERY 1", [high1]),      # a 750 s gap: the first episode ends at 150 s, a new one starts
        (930, "BATTERY 1", []), (0, "BATTERY 2", []), (40, "BATTERY 2", []),
    ]
    totals = EnergyTotals(FakeCache([point(i, s, b, a) for i, (s, b, a) in enumerate(rows)]))
    out = totals.alarm_episodes(T0.isoformat(), (T0 + timedelta(hours=1)).isoformat())
    eps = [(e["battery"], e["type"], e["level"], e["start"][11:19], e["end"][11:19]) for e in out["episodes"]]
    assert eps == [
        ("BATTERY 1", "Cell voltage high", 2, "12:00:30", "12:02:00"),
        ("BATTERY 1", "Charge temperature low", 1, "12:01:00", "12:01:30"),
        ("BATTERY 1", "Cell voltage high", 1, "12:02:30", "12:02:30"),
        ("BATTERY 1", "Cell voltage high", 1, "12:15:00", "12:15:30"),
    ], eps
    b1 = out["batteries"][0]
    assert b1["key"] == "BATTERY 1" and b1["episodes"] == 4 and b1["seconds"] == 90 + 30 + 0 + 30, b1
    assert out["batteries"][1]["episodes"] == 0
    assert [(t["type"], t["episodes"]) for t in out["types"]] == [("Cell voltage high", 3), ("Charge temperature low", 1)]
    part = totals.alarm_episodes((T0 + timedelta(seconds=100)).isoformat(), (T0 + timedelta(seconds=140)).isoformat())
    assert [e["type"] for e in part["episodes"]] == ["Cell voltage high"] and part["batteries"][0]["seconds"] == 20, part
    try:
        totals.alarm_episodes(T0.isoformat(), T0.isoformat())
        raise AssertionError("an empty period must be refused")
    except ValueError:
        pass
    print("Alarm episodes per battery and type (levels, ends, Bluetooth gaps, totals, a part of the period): OK")


if __name__ == "__main__":
    main()
