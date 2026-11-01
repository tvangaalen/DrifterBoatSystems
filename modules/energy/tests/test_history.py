"""Non-hardware self-test for EnergyTotals.contributions() (the History-page pie charts).

Synthetic hour with known powers, so every expected energy can be worked out by hand:
- Solar 100 W all hour, alternator 50 W for the first 30 min, charger house 0 W.
- Inverter 20 W and other DC 10 W all hour.
- 10 minutes (minute 40-50) of missing dashboard data: must be excluded, not interpolated.
- Battery 1 discharges 10 A at 13.2 V (132 W), Battery 2 charges 5 A (66 W), Battery 3 is idle
  with three separate alarm episodes (6 alarm samples).
"""

import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mastervolt.history.service import HistoryService

BASE = datetime.now(UTC).replace(microsecond=123456) - timedelta(hours=2)


def close(actual, expected, tolerance, label):
    assert abs(actual - expected) <= tolerance, f"{label}: {actual:.3f} != {expected:.3f} (+/-{tolerance})"


def main():
    with tempfile.TemporaryDirectory(prefix="hist svc ") as tmp:  # folder name with a space, like Google Drive
        history = HistoryService(Path(tmp) / "history.sqlite3")
        for second in range(0, 3601, 10):
            if 2400 < second < 3000:
                continue  # dashboard data missing for minutes 40-50
            stamp = (BASE + timedelta(seconds=second)).isoformat()
            history.record(
                "dashboard",
                {
                    "sources": {
                        "shore": {"power": 0},
                        "charger_house": {"power": 0.0},
                        "alternator": {"power": 50.0 if second <= 1800 else 0.0},
                        "solar": {"power": 100.0},
                    },
                    "consumers": {
                        "inverter": {"power": 20.0},
                        "charger_start": {"power": None},
                        "charger_bow": {"power": 0.0},
                        "engine_ecu": {"power": 1.0},
                        "alternator_field": {"power": 0.0},
                        "other_dc": {"power": 10.0},
                    },
                },
                captured_at=stamp,
            )
        for second in range(0, 3601, 30):
            stamp = (BASE + timedelta(seconds=second)).isoformat()
            index = second // 30
            for name, current, alarms in (
                ("BATTERY 1", -10.0, []),
                ("BATTERY 2", 5.0, []),
                ("BATTERY 3", 0.0, ["Cell voltage high â€“ level 2"] if index in (10, 11, 30, 50, 51, 52) else []),
            ):
                history.record(
                    "bms",
                    {
                        "state": "connected",
                        "battery": name,
                        "captured_at": stamp,
                        "pack_voltage_v": 13.2,
                        "current_a": current,
                        "cells_mv": [3300, 3300, 3300, 3300],
                        "alarms": alarms,
                        "remaining_capacity_ah": 200.0,
                        "cell_spread_mv": 0,
                        "charge_mosfet_on": True,
                        "discharge_mosfet_on": True,
                    },
                    device=name,
                    captured_at=stamp,
                )

        whole = history.contributions(BASE.isoformat(), (BASE + timedelta(hours=1)).isoformat())
        source = {row["key"]: row for row in whole["sources"]}
        # 3000 s of coverage (the 600 s gap is excluded), so solar = 100 W * 3000 s
        close(whole["sources_covered_seconds"], 3000, 1, "dashboard coverage")
        close(source["solar"]["wh"], 100 * 3000 / 3600, 0.01, "solar Wh")
        close(source["solar"]["avg_w"], 100, 0.01, "solar average W")
        close(source["alternator"]["wh"], 50 * 1800 / 3600 + 50 / 2 * 10 / 3600, 0.01, "alternator Wh (first 30 min)")
        assert source["charger_house"]["wh"] == 0
        consumer = {row["key"]: row for row in whole["consumers"]}
        close(consumer["inverter"]["wh"], 20 * 3000 / 3600, 0.01, "inverter Wh")
        close(consumer["other_dc"]["wh"], 10 * 3000 / 3600, 0.01, "other DC Wh")
        assert consumer["charger_start"]["wh"] == 0, "missing power (None) must count as 0"
        print("Sources and consumers: energy, average power and the excluded 10 min gap: OK")

        battery = {row["key"]: row for row in whole["batteries"]}
        close(battery["BATTERY 1"]["discharge_wh"], 132, 0.05, "battery 1 delivered Wh")
        close(battery["BATTERY 1"]["charge_wh"], 0, 0.01, "battery 1 received Wh")
        close(battery["BATTERY 2"]["charge_wh"], 66, 0.05, "battery 2 received Wh")
        close(battery["BATTERY 2"]["discharge_wh"], 0, 0.01, "battery 2 delivered Wh")
        close(battery["BATTERY 1"]["avg_discharge_w"], 132, 0.1, "battery 1 average W")
        print("Batteries: delivered and received energy from the cell-voltage sum: OK")

        alarm = {row["key"]: row for row in whole["alarms"]}
        assert (alarm["BATTERY 3"]["episodes"], alarm["BATTERY 3"]["samples"]) == (3, 6), alarm["BATTERY 3"]
        assert alarm["BATTERY 1"]["episodes"] == 0 and alarm["BATTERY 2"]["samples"] == 0
        print("Alarm episodes (3) and samples (6) per battery: OK")

        half = history.contributions(BASE.isoformat(), (BASE + timedelta(minutes=30)).isoformat())
        close({row["key"]: row for row in half["batteries"]}["BATTERY 1"]["discharge_wh"], 66, 0.1, "first 30 min")
        assert {row["key"]: row for row in half["alarms"]}["BATTERY 3"]["episodes"] == 3  # all three are within the first 30 min
        ten = history.contributions(BASE.isoformat(), (BASE + timedelta(minutes=10)).isoformat())
        assert {row["key"]: row for row in ten["alarms"]}["BATTERY 3"]["episodes"] == 1  # only the episode at samples 10-11 is inside
        close(half["span_seconds"], 1800, 0.01, "span")
        z = history.contributions(
            (BASE + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            (BASE + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.999Z"),
        )
        close({row["key"]: row for row in z["batteries"]}["BATTERY 1"]["discharge_wh"], 66, 0.1, "second 30 min (Z timestamps)")
        print("Sub-periods and 'Z' timestamps: OK")

        for bad in (("garbage", BASE.isoformat()), (BASE.isoformat(), "nope"), ((BASE + timedelta(hours=1)).isoformat(), BASE.isoformat())):
            try:
                history.contributions(*bad)
                raise AssertionError(f"accepted {bad}")
            except ValueError:
                pass
        empty = history.contributions((BASE + timedelta(days=5)).isoformat(), (BASE + timedelta(days=6)).isoformat())
        assert empty["sources_covered_seconds"] == 0 and all(row["wh"] == 0 for row in empty["sources"])
        print("Invalid input rejected, empty period returns zeros: OK")

    # Whole-hour totals must add up exactly to a direct calculation, at any start/end, over several hours.
    with tempfile.TemporaryDirectory(prefix="hist hours ") as tmp:
        history = HistoryService(Path(tmp) / "history.sqlite3")
        origin = (datetime.now(UTC) - timedelta(hours=9)).replace(minute=17, second=3, microsecond=250000)
        for step in range(0, 6 * 3600 + 1, 20):
            second = step
            stamp = (origin + timedelta(seconds=second)).isoformat()
            wave = 1 + (second // 600) % 5
            history.record(
                "dashboard",
                {
                    "sources": {
                        "charger_house": {"power": 10.0 * wave},
                        "alternator": {"power": 0.0},
                        "solar": {"power": 3.0 * (second % 900) / 9},
                    },
                    "consumers": {"inverter": {"power": 7.0 * wave}, "other_dc": {"power": 40.0}},
                },
                captured_at=stamp,
            )
            if second % 30 == 0 and not 9000 < second < 9600:  # a Bluetooth gap of 10 minutes
                for name, sign in (("BATTERY 1", -1), ("BATTERY 2", 1), ("BATTERY 3", -1)):
                    history.record(
                        "bms",
                        {
                            "state": "connected",
                            "battery": name,
                            "captured_at": stamp,
                            "cells_mv": [3320] * 4,
                            "current_a": sign * (2.0 + wave),
                            "alarms": ["x"] if second % 1800 in (0, 30) else [],
                        },
                        device=name,
                        captured_at=stamp,
                    )
        history.refresh_chart_cache()
        index = history.totals._index()
        checked = 0
        for begin_min, length_min in ((0, 360), (7, 251), (61, 60), (30, 45), (100, 5), (0, 61), (119, 122), (59, 2)):
            a = origin + timedelta(minutes=begin_min, seconds=11)
            b = a + timedelta(minutes=length_min)
            composed = history.contributions(a.isoformat(), b.isoformat())
            energy, covered, batteries = history.totals._raw_energy(index, a.timestamp(), b.timestamp())
            keys = (
                "charger_house",
                "alternator",
                "solar",
                "inverter",
                "charger_start",
                "charger_bow",
                "engine_ecu",
                "alternator_field",
                "other_dc",
            )
            got = {row["key"]: row["wh"] for row in composed["sources"] + composed["consumers"]}
            for key, wh in zip(keys, energy):
                close(got[key], wh, 1e-9, f"{key} composed vs direct ({begin_min}+{length_min} min)")
            for row in composed["batteries"]:
                out, into, cover = batteries[row["key"]]
                close(row["discharge_wh"], out, 1e-9, "battery out composed vs direct")
                close(row["charge_wh"], into, 1e-9, "battery in composed vs direct")
                close(row["covered_seconds"], cover, 1e-9, "battery coverage composed vs direct")
            close(composed["sources_covered_seconds"], covered, 1e-9, "dashboard coverage composed vs direct")
            checked += 1
        assert index["hours"], "finished hours were not remembered"
        assert history.totals._index() is index, "the index was rebuilt although the data did not change"
        print(f"Hourly totals add up exactly to the direct calculation ({checked} periods, {len(index['hours'])} hours remembered): OK")
    print("All history contribution checks: OK")


def chart_data_test():
    """chart_data(hours=...) must return exactly the points within that window (bisect cutoff, changelog 1.18.1)
    and stay fast regardless of total cache size - it used to rescan the whole cache on every call (all_points=
    bms+dashboard, two full-list filters), which cost 400-750 ms once it held a few weeks of real history and
    made every History preset/zoom change sluggish."""
    import time

    with tempfile.TemporaryDirectory(prefix="hist chart ") as tmp:
        history = HistoryService(Path(tmp) / "history.sqlite3")
        now = datetime.now(UTC).replace(microsecond=0)
        total = 150_000
        # Build the caches directly, exactly as refresh_chart_cache() would leave them (append-only, id order),
        # without the overhead of writing/reading 300k+ rows through SQLite.
        history.cache.bms = [
            {
                "id": i + 1,
                "captured_at": (now - timedelta(seconds=(total - i) * 10)).isoformat(),
                "battery": "BATTERY 1",
                "voltage": 13.2,
                "current": 0.0,
                "remaining": 200.0,
                "cells": "3300 3300 3300 3300",
                "cell_spread": 0,
                "alarms": "",
                "charge_mos": True,
                "discharge_mos": True,
            }
            for i in range(total)
        ]
        history.cache.dashboard = [
            {
                "id": i + 1,
                "captured_at": (now - timedelta(seconds=(total - i) * 10)).isoformat(),
                "source_power": [0.0, 0.0, 0.0],
                "source_current": [0.0, 0.0, 0.0],
                "shore_voltage": 0.0,
                "shore_connected": False,
                "solar_panel_voltage": 0.0,
                "alternator_temperature": 0.0,
                "alternator_running": False,
                "load_power": [0.0] * 6,
                "load_current": [0.0] * 6,
                "ac_power": 0.0,
                "ac_frequency": 0.0,
                "inverting": False,
                "supporting": False,
            }
            for i in range(total)
        ]
        # Correctness: the bisect cutoff must match a plain, independent linear scan at every zoom level.
        for hours in (0.25, 1, 4, 24, 100, 10_000):
            data = history.chart_data(hours)
            cutoff = (datetime.fromisoformat(data["latest"]) - timedelta(hours=max(0.25, hours))).isoformat()
            expected_bms = sum(1 for p in history.cache.bms if p["captured_at"] >= cutoff)
            expected_dash = sum(1 for p in history.cache.dashboard if p["captured_at"] >= cutoff)
            assert data["bms_count"] == expected_bms, f"bms_count mismatch at hours={hours}: {data['bms_count']} != {expected_bms}"
            assert (
                data["dashboard_count"] == expected_dash
            ), f"dashboard_count mismatch at hours={hours}: {data['dashboard_count']} != {expected_dash}"
        print(f"chart_data() cutoff matches a direct linear scan, {total:,} points per cache, at every zoom level: OK")

        # Performance: a short window must stay fast regardless of total cache size (bisect, not a full scan).
        start = time.perf_counter()
        for _ in range(20):
            history.chart_data(4)
        elapsed_ms = (time.perf_counter() - start) * 1000 / 20
        assert (
            elapsed_ms < 50
        ), f"chart_data(4) averaged {elapsed_ms:.1f} ms over {total:,}-point caches - the cutoff may be scanning the whole cache again"
        print(f"chart_data(4) over {total:,}-point caches: {elapsed_ms:.2f} ms average (was 400-750 ms live before the bisect fix): OK")


def refresh_chart_cache_trim_test():
    """refresh_chart_cache()'s retention trim must only rebuild the cached list when something was actually
    pruned (skipped via an O(1) check, bisect otherwise, instead of an unconditional full rebuild every ~60 s -
    changelog 1.18.1), and still end up with exactly the rows that survived pruning."""
    with tempfile.TemporaryDirectory(prefix="hist trim ") as tmp:
        history = HistoryService(Path(tmp) / "history.sqlite3")
        now = datetime.now(UTC)
        old_stamp = (now - timedelta(days=2)).isoformat()
        for _ in range(5):
            history.record("dashboard", {"sources": {}, "consumers": {}}, captured_at=old_stamp)
        recent_stamps = [(now - timedelta(seconds=s)).isoformat() for s in (40, 30, 20, 10, 0)]
        for stamp in recent_stamps:
            history.record("dashboard", {"sources": {}, "consumers": {}}, captured_at=stamp)

        history.refresh_chart_cache()
        assert len(history.cache.dashboard) == 10, "all 10 rows should be cached before anything is pruned"

        deleted = history.prune(1)  # the minimum retention is 1 day
        assert deleted == 5, f"expected the 5 two-day-old rows to be pruned, deleted {deleted}"

        before = history.cache.dashboard
        history.refresh_chart_cache()
        after = history.cache.dashboard
        assert after is not before, "the cache must be rebuilt the one time something was actually pruned"
        assert len(after) == 5 and all(p["captured_at"] in recent_stamps for p in after), "only the 5 surviving rows should remain"
        print("refresh_chart_cache() trims exactly the rows retention pruning removed: OK")

        unchanged = history.cache.dashboard
        history.refresh_chart_cache()  # nothing new to prune this time
        assert history.cache.dashboard is unchanged, "the cache must not be rebuilt when nothing was pruned"
        print("refresh_chart_cache() skips the trim rebuild when nothing was pruned: OK")


def db_status_test():
    """db_status() (Settings page): totals, per-source counts, oldest/newest, sizes, and a short-lived cache."""
    with tempfile.TemporaryDirectory(prefix="hist status ") as tmp:
        history = HistoryService(Path(tmp) / "history.sqlite3")
        empty = history.db_status(31, max_age=0)
        assert empty["records"] == 0 and empty["oldest"] is None and empty["span_days"] is None and empty["by_source"] == {}
        now = datetime.now(UTC)
        for day in range(3):
            stamp = (now - timedelta(days=2 - day)).isoformat()
            history.record("dashboard", {"x": day}, captured_at=stamp)
            history.record("bms", {"x": day}, device="BATTERY 1", captured_at=stamp)
        history.record("bms", {"x": 9}, device="BATTERY 2", captured_at=now.isoformat())
        status = history.db_status(31, max_age=0)
        assert status["records"] == 7 and status["by_source"] == {"dashboard": 3, "bms": 4}, status
        assert status["oldest"] == (now - timedelta(days=2)).isoformat() and status["newest"] == now.isoformat()
        assert abs(status["span_days"] - 2) < 1e-6 and status["retention_days"] == 31
        assert status["size_bytes"] > 0 and status["disk_free_bytes"] > 0 and status["records_per_day"] == 3.5
        assert status["projected_bytes_at_retention"] is None or status["projected_bytes_at_retention"] > 0
        assert status["chart_cache"] == {"bms": 0, "dashboard": 0}
        history.record("dashboard", {"x": 10})
        cached = history.db_status(31, max_age=3600)
        assert cached["records"] == 7, "within max_age the earlier result is served, not a fresh count"
        assert history.db_status(31, max_age=3600) == cached, "a second call within max_age must return the cached status"
        assert history.db_status(31, max_age=0)["records"] == 8, "max_age=0 must re-read the database"
    print("db_status(): totals, per-source counts, oldest/newest, sizes and caching: OK")


def shore_intake_test():
    """The shore power intake: energy over a period summed on the server from the full-resolution dashboard samples."""
    with tempfile.TemporaryDirectory(prefix="hist shore ") as tmp:
        history = HistoryService(Path(tmp) / "history.sqlite3")
        start = datetime(2026, 10, 1, 8, 0, 0, tzinfo=UTC)

        def sample(seconds, watts, amps):
            payload = {"sources": {"shore": {"power": watts, "current": amps, "voltage": 230.0, "connected": True}}, "consumers": {}}
            history.record("dashboard", payload, None, (start + timedelta(seconds=seconds)).isoformat())

        for minute in range(0, 121):  # two hours at a steady 1000 W (4.35 A), one sample a minute
            sample(minute * 60, 1000.0, 4.35)
        # shore power drops out: no samples from minute 121 to 149 (longer than the 120 s gap limit)
        for minute in range(150, 181):  # then half an hour at 500 W
            sample(minute * 60, 500.0, 2.17)
        history.refresh_chart_cache()
        points = history.chart_data(12)["dashboard"]
        assert (
            points[0]["shore_power"] == 1000.0 and points[0]["shore_current"] == 4.35
        ), "chart points must carry the shore current and power"
        whole = history.contributions(start.isoformat(), (start + timedelta(hours=3)).isoformat())
        shore = whole["shore"]
        # 2 h x 1000 W + 0.5 h x 500 W = 2.25 kWh; the 30-minute gap is not integrated and shows in the covered time
        assert abs(shore["wh"] - 2250.0) < 1.0, shore
        assert abs(whole["sources_covered_seconds"] - (2 * 3600 + 1800)) < 1.0, whole["sources_covered_seconds"]
        assert abs(shore["avg_w"] - 900.0) < 1.0, shore  # averaged over the recorded 2.5 h, not the 3 h selected
        # a sub-period inside the steady stretch, and the parts add up exactly
        first_hour = history.contributions(start.isoformat(), (start + timedelta(hours=1)).isoformat())["shore"]["wh"]
        second_hour = history.contributions((start + timedelta(hours=1)).isoformat(), (start + timedelta(hours=2)).isoformat())["shore"][
            "wh"
        ]
        assert abs(first_hour - 1000.0) < 1.0 and abs(second_hour - 1000.0) < 1.0 and abs(first_hour + second_hour - 2000.0) < 1e-6
        # shore power must not leak into the DC source or consumer lists (the donut totals are DC)
        assert [row["key"] for row in whole["sources"]] == ["charger_house", "alternator", "solar"]
        assert len(whole["consumers"]) == 6 and all(row["wh"] == 0 for row in whole["sources"] + whole["consumers"])
        # a point without shore data (older samples, a disconnected feed) counts as zero
        history.record("dashboard", {"sources": {}, "consumers": {}}, None, (start + timedelta(hours=4)).isoformat())
        history.refresh_chart_cache()
        assert history.contributions(start.isoformat(), (start + timedelta(hours=5)).isoformat())["shore"]["wh"] >= 2250.0 - 1.0
    print("Shore power intake: kWh over a period from the full-resolution samples, gaps excluded, parts add up: OK")


def export_test():
    """The export streams in batches (on a connection of its own) instead of loading the whole history into memory."""
    from mastervolt.history import store as history_store

    with tempfile.TemporaryDirectory(prefix="hist export ") as tmp:
        history = HistoryService(Path(tmp) / "history.sqlite3")
        for index in range(450):
            history.record(
                "bms" if index % 3 else "dashboard",
                {"n": index},
                device="BATTERY 1" if index % 3 else None,
                captured_at=f"2026-10-01T10:{index // 60:02d}:{index % 60:02d}+00:00",
            )
        history_store.EXPORT_BATCH = 100
        lines = history.json_lines()
        first = next(lines)  # a generator: nothing beyond the first batch has been read yet
        assert json.loads(first)["id"] == 1
        history.record("dashboard", {"n": "while exporting"})  # recording is not blocked by a running export
        rest = list(lines)
        ids = [json.loads(line)["id"] for line in [first] + rest]
        assert ids == sorted(ids) and len(ids) == 451 and ids[0] == 1 and ids[-1] == 451, (len(ids), ids[-3:])
        assert json.loads(first)["values"] == {"n": 0}
    print("Export: streamed in batches, ordered, records can be added while it runs: OK")


if __name__ == "__main__":
    main()
    chart_data_test()
    refresh_chart_cache_trim_test()
    db_status_test()
    shore_intake_test()
    export_test()
