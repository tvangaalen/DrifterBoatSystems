"""The server-side chart cache: normalised history points in memory, so a History page never waits for SQLite.

Both lists are append-only in id order (and therefore in time order): `refresh` only adds rows newer than the last one and
drops what retention pruning removed from the front. Anything that filters them by time or id MUST bisect
(`bisect_left(cache, cutoff, key=...)`), never scan: a linear scan once cost 400-750 ms per call once the cache held weeks
of history, and the cache only grows with the retention period (CHANGELOG 1.18.1).
"""

from __future__ import annotations

import threading
from bisect import bisect_left
from datetime import UTC, datetime, timedelta

from ..bluetooth.daly_protocol import BATTERY_NAMES
from .series import bms_point, dashboard_point
from .store import HistoryStore

DASHBOARD_POINTS = 2500  # points per chart sent to the browser (for drawing only: totals come from the full-resolution cache)
BMS_POINTS_PER_BATTERY = 1200
MIN_HOURS = 0.25


def _series(store: HistoryStore, source: str, after_id: int, make) -> dict:
    (first, last), rows = store.rows_after(source, after_id)
    points = []
    for row in rows:
        point = make(row)
        if point is not None:
            points.append(point)
    return {"earliest_id": first or 0, "latest_id": last or 0, "points": points}


def bms_series(store: HistoryStore, after_id: int = 0) -> dict:
    """Compact, chronological BMS samples for incremental chart updates."""
    return _series(store, "bms", after_id, lambda row: bms_point(row[0], row[1], row[2], row[3]))


def dashboard_series(store: HistoryStore, after_id: int = 0) -> dict:
    """Compact dashboard samples used by the Sources and Loads charts."""
    return _series(store, "dashboard", after_id, lambda row: dashboard_point(row[0], row[1], row[3]))


def sample(points: list, maximum: int) -> list:
    """At most `maximum` points, evenly spread (always including the first and last)."""
    if len(points) <= maximum:
        return points
    step = (len(points) - 1) / (maximum - 1)
    return [points[round(index * step)] for index in range(maximum)]


def sample_bms(points: list, maximum: int) -> list:
    """Uniform detail plus every alarm neighbourhood and MOSFET transition: safety events are never sampled away."""
    if len(points) <= maximum:
        return points
    selected = {point["id"]: point for point in sample(points, maximum)}
    previous_charge = previous_discharge = None
    for index, point in enumerate(points):
        transition = (previous_charge is not None and point.get("charge_mos") != previous_charge) or (
            previous_discharge is not None and point.get("discharge_mos") != previous_discharge
        )
        if point.get("alarms") or transition:
            for nearby in points[max(0, index - 2) : min(len(points), index + 3)]:
                selected[nearby["id"]] = nearby
        previous_charge, previous_discharge = point.get("charge_mos"), point.get("discharge_mos")
    return sorted(selected.values(), key=lambda point: point["id"])


class ChartCache:
    def __init__(self, store: HistoryStore):
        self.store = store
        self.lock = threading.RLock()
        self.bms: list[dict] | None = None
        self.dashboard: list[dict] | None = None

    @property
    def loaded(self) -> bool:
        return self.bms is not None and self.dashboard is not None

    def sizes(self) -> dict:
        return {"bms": len(self.bms or ()), "dashboard": len(self.dashboard or ())}

    def refresh(self) -> int:
        """Bring the cache in line with SQLite: append the new rows, trim what retention pruning removed. Returns rows added."""
        with self.lock:
            bms = bms_series(self.store, self.bms[-1]["id"] if self.bms else 0)
            dashboard = dashboard_series(self.store, self.dashboard[-1]["id"] if self.dashboard else 0)
            if self.bms is None:
                self.bms = []
            if self.dashboard is None:
                self.dashboard = []
            self.bms.extend(bms["points"])
            self.dashboard.extend(dashboard["points"])
            # Pruning only removes rows once the oldest cached point falls outside the kept window (with a 31-day default
            # that had not happened once in the first three weeks): skip the trim when there is nothing to trim, and use the
            # same O(log n) bisect as chart_data() when there is (CHANGELOG 1.18.1).
            if self.bms and self.bms[0]["id"] < bms["earliest_id"]:
                self.bms = self.bms[bisect_left(self.bms, bms["earliest_id"], key=lambda p: p["id"]) :]
            if self.dashboard and self.dashboard[0]["id"] < dashboard["earliest_id"]:
                self.dashboard = self.dashboard[bisect_left(self.dashboard, dashboard["earliest_id"], key=lambda p: p["id"]) :]
            return len(bms["points"]) + len(dashboard["points"])

    def chart_data(self, hours: float, refresh: bool = False) -> dict:
        """The last `hours` of history, sampled for drawing (each battery separately, keeping every safety event)."""
        with self.lock:
            if refresh or not self.loaded:
                self.refresh()
            bms_cache, dashboard_cache = self.bms, self.dashboard
            # Both caches are append-only in time order, so the cut-off is found by bisecting, not scanning.
            latest = (
                max(cache[-1]["captured_at"] for cache in (bms_cache, dashboard_cache) if cache)
                if (bms_cache or dashboard_cache)
                else datetime.now(UTC).isoformat()
            )
            cutoff = (datetime.fromisoformat(latest) - timedelta(hours=max(MIN_HOURS, float(hours)))).isoformat()
            bms_full = bms_cache[bisect_left(bms_cache, cutoff, key=lambda p: p["captured_at"]) :]
            dashboard_full = dashboard_cache[bisect_left(dashboard_cache, cutoff, key=lambda p: p["captured_at"]) :]
            bms = []
            for battery in BATTERY_NAMES:
                bms.extend(sample_bms([p for p in bms_full if p["battery"] == battery], BMS_POINTS_PER_BATTERY))
            bms.sort(key=lambda p: p["id"])
            return {
                "bms": bms,
                "dashboard": sample(dashboard_full, DASHBOARD_POINTS),
                "bms_count": len(bms_full),
                "dashboard_count": len(dashboard_full),
                "latest": latest,
                "cutoff": cutoff,
            }
