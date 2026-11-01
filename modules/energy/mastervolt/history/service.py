"""The measurement history, assembled: SQLite store, server-side chart cache and energy totals behind one object."""

from __future__ import annotations

from pathlib import Path

from .chart_cache import ChartCache, bms_series, dashboard_series
from .store import HistoryStore
from .totals import EnergyTotals


class HistoryService:
    def __init__(self, path: Path):
        self.store = HistoryStore(path)
        self.cache = ChartCache(self.store)
        self.totals = EnergyTotals(self.cache)

    # recording and housekeeping
    def record(self, source: str, payload, device: str | None = None, captured_at: str | None = None) -> None:
        self.store.record(source, payload, device, captured_at)

    def prune(self, retention_days: int) -> int:
        return self.store.prune(retention_days)

    # raw access
    def latest(self, limit: int = 100) -> list[dict]:
        return self.store.latest(limit)

    def count(self) -> int:
        return self.store.count()

    def json_lines(self):
        return self.store.json_lines()

    def db_status(self, retention_days: int, max_age: float = 60.0) -> dict:
        return {**self.store.db_status(retention_days, max_age), "chart_cache": self.cache.sizes()}

    def bms_series(self, after_id: int = 0) -> dict:
        return bms_series(self.store, after_id)

    def dashboard_series(self, after_id: int = 0) -> dict:
        return dashboard_series(self.store, after_id)

    # charts and totals
    def refresh_chart_cache(self) -> int:
        return self.cache.refresh()

    def chart_data(self, hours: float, refresh: bool = False) -> dict:
        return self.cache.chart_data(hours, refresh)

    def contributions(self, start, end) -> dict:
        return self.totals.contributions(start, end)
