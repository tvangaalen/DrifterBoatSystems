"""The SQLite measurement history: one table, one row per sample, JSON payloads.

Every sample is stored as it was measured (`dashboard` every 10 s, `bms` and `balancer` once per new Bluetooth
reading). WAL mode lets the reader paths (status, export) use connections of their own without ever stalling the recorder.
Everything the Settings page shows is answered from the (source, id) index - never by scanning payloads, which would
read the whole (about 1 GB) file.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

EXPORT_BATCH = 2000  # rows per batch while streaming the export: memory stays flat however large the history is


class HistoryStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self._status_cache = None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                "CREATE TABLE IF NOT EXISTS measurements (id INTEGER PRIMARY KEY, captured_at TEXT NOT NULL, source TEXT NOT NULL, device TEXT, payload TEXT NOT NULL)"
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_measurements_time ON measurements(captured_at DESC)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_measurements_source_id ON measurements(source, id)")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            yield db
            db.commit()
        finally:
            db.close()

    # ---- writing ------------------------------------------------------------------------------------------------
    def record(self, source: str, payload, device: str | None = None, captured_at: str | None = None) -> None:
        stamp = captured_at or datetime.now(UTC).isoformat()
        encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False, default=str)
        with self.lock, self._connect() as db:
            db.execute("INSERT INTO measurements(captured_at,source,device,payload) VALUES(?,?,?,?)", (stamp, source, device, encoded))

    def prune(self, retention_days: int) -> int:
        """Delete measurements older than the rolling retention period; returns how many rows went."""
        days = max(1, min(int(retention_days), 365))
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        with self.lock, self._connect() as db:
            return db.execute("DELETE FROM measurements WHERE captured_at < ?", (cutoff,)).rowcount

    # ---- reading ------------------------------------------------------------------------------------------------
    def latest(self, limit: int = 100) -> list[dict]:
        limit = max(1, min(int(limit), 1000))
        with self.lock, self._connect() as db:
            rows = db.execute("SELECT id,captured_at,source,device,payload FROM measurements ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{"id": row[0], "captured_at": row[1], "source": row[2], "device": row[3], "values": json.loads(row[4])} for row in rows]

    def count(self) -> int:
        with self.lock, self._connect() as db:
            return db.execute("SELECT COUNT(*) FROM measurements").fetchone()[0]

    def rows_after(self, source: str, after_id: int) -> tuple[tuple[int | None, int | None], list[tuple]]:
        """((first id, last id) of the source, rows with id > after_id as (id, captured_at, device, payload)), in id order."""
        with self.lock, self._connect() as db:
            bounds = db.execute("SELECT MIN(id),MAX(id) FROM measurements WHERE source=?", (source,)).fetchone()
            rows = db.execute(
                "SELECT id,captured_at,device,payload FROM measurements WHERE source=? AND id>? ORDER BY id",
                (source, max(0, int(after_id))),
            ).fetchall()
        return bounds, rows

    def json_lines(self):
        """The whole history as JSON lines, streamed in batches on a connection of its own (WAL: it never blocks the recorder)."""
        db = sqlite3.connect(self.path, timeout=10)
        try:
            last = 0
            while True:
                rows = db.execute(
                    "SELECT id,captured_at,source,device,payload FROM measurements WHERE id>? ORDER BY id LIMIT ?", (last, EXPORT_BATCH)
                ).fetchall()
                if not rows:
                    return
                for row in rows:
                    yield json.dumps(
                        {"id": row[0], "captured_at": row[1], "source": row[2], "device": row[3], "values": json.loads(row[4])},
                        ensure_ascii=False,
                    ) + "\n"
                last = rows[-1][0]
        finally:
            db.close()

    def db_status(self, retention_days: int, max_age: float = 60.0) -> dict:
        """Database size and record statistics for the Settings page, cached for `max_age` seconds and read on a connection of
        its own, so opening Settings can never stall recording or the chart cache."""
        now = time.monotonic()
        cached = self._status_cache
        if cached and now - cached[0] < max_age and cached[2] == retention_days:
            return cached[1]
        db = sqlite3.connect(self.path, timeout=10)
        try:
            counts = dict(db.execute("SELECT source,COUNT(*) FROM measurements GROUP BY source").fetchall())
            first, last = [], []
            for source in counts:
                first.append(db.execute("SELECT captured_at FROM measurements WHERE source=? ORDER BY id LIMIT 1", (source,)).fetchone()[0])
                last.append(
                    db.execute("SELECT captured_at FROM measurements WHERE source=? ORDER BY id DESC LIMIT 1", (source,)).fetchone()[0]
                )
            page_size = db.execute("PRAGMA page_size").fetchone()[0]
            page_count = db.execute("PRAGMA page_count").fetchone()[0]
            free_pages = db.execute("PRAGMA freelist_count").fetchone()[0]
        finally:
            db.close()
        wal_path = str(self.path) + "-wal"
        oldest, newest = (min(first) if first else None), (max(last) if last else None)
        span_days = None
        if oldest and newest:
            try:
                span_days = (datetime.fromisoformat(newest) - datetime.fromisoformat(oldest)).total_seconds() / 86400
            except ValueError:
                pass
        records = sum(counts.values())
        enough = bool(span_days and span_days >= 0.5)
        bytes_per_day = (page_count - free_pages) * page_size / span_days if enough else None
        status = {
            "file": self.path.name,
            "size_bytes": os.path.getsize(self.path),
            "wal_bytes": os.path.getsize(wal_path) if os.path.exists(wal_path) else 0,
            "reusable_bytes": free_pages * page_size,
            "disk_free_bytes": shutil.disk_usage(self.path.parent).free,
            "records": records,
            "by_source": counts,
            "oldest": oldest,
            "newest": newest,
            "span_days": span_days,
            "retention_days": retention_days,
            "records_per_day": records / span_days if enough else None,
            "projected_bytes_at_retention": bytes_per_day * retention_days if bytes_per_day else None,
        }
        self._status_cache = (now, status, retention_days)
        return status
