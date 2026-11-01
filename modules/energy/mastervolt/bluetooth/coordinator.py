"""Process-wide priority gate for Windows Bluetooth discovery and connections."""

from __future__ import annotations

import asyncio
import threading
import time
from contextlib import asynccontextmanager, contextmanager

from .events import ble_log


class BluetoothCoordinator:
    """Serialize radio work with deterministic user-first priorities.

    * Only one operation owns the radio at a time; the highest priority waiter goes first and waiters
      of equal priority are served in arrival order (FIFO).
    * `acquire` returns a token (truthy) that identifies the lease, or 0 on time-out. A lease that is held longer than
      MAX_HOLD_SECONDS for its kind is taken back (a hung Windows call must never block the radio for ever, not even
      for a user control); a late `release` with the old token is ignored so it cannot free a newer holder.
    * Balancers may run when every BMS is connected and read, or in *degraded mode* when one BMS has been away for
      more than `degraded_after` seconds and the others are healthy."""

    PRIORITY = {
        "bms_control": 0,
        "bms_manual_read": 1,
        "bms_manual_connect": 1,
        "bms": 2,
        "bms_read": 3,
        "balancer": 4,
    }
    # Generous upper bounds, well above the slowest legitimate operation of each kind.
    MAX_HOLD_SECONDS = {
        "bms_control": 180.0,
        "bms_manual_read": 90.0,
        "bms_manual_connect": 90.0,
        "bms": 90.0,
        "bms_read": 90.0,
        "balancer": 150.0,
    }
    DEGRADED_AFTER_SECONDS = 120.0

    def __init__(self, required_bms=3, stable_seconds=0, degraded_after=None, max_hold=None):
        self.condition = threading.Condition()
        self.required_bms = int(required_bms)
        self.stable_seconds = float(stable_seconds)
        self.degraded_after = self.DEGRADED_AFTER_SECONDS if degraded_after is None else float(degraded_after)
        self.max_hold = {**self.MAX_HOLD_SECONDS, **(max_hold or {})}
        self.connected_bms = set()
        self.refreshed_bms = set()
        self.stable_since = None
        self.incomplete_since = time.monotonic()  # no BMS is connected yet
        self.active_kind = None
        self.active_token = 0
        self.active_since = None
        self.forced_releases = 0
        self._tokens = 0
        self._seq = 0
        self.tickets = {}
        self.waiters = {kind: 0 for kind in self.PRIORITY}

    # ---- BMS link state -------------------------------------------------------------------
    def mark_bms(self, name, connected):
        with self.condition:
            if connected:
                self.connected_bms.add(name)
            else:
                self.connected_bms.discard(name)
                self.refreshed_bms.discard(name)
                self.stable_since = None
            if len(self.connected_bms) >= self.required_bms:
                self.incomplete_since = None
            elif self.incomplete_since is None:
                self.incomplete_since = time.monotonic()
            self.condition.notify_all()

    def mark_bms_refreshed(self, name):
        with self.condition:
            if name in self.connected_bms:
                self.refreshed_bms.add(name)
            self.condition.notify_all()

    def _ready_locked(self):
        """(ready, degraded). Every connected BMS must have been read since it (re)connected."""
        now = time.monotonic()
        connected = len(self.connected_bms)
        full = connected >= self.required_bms
        degraded = (
            not full
            and connected >= max(1, self.required_bms - 1)
            and self.incomplete_since is not None
            and now - self.incomplete_since >= self.degraded_after
        )
        if not (full or degraded) or not self.connected_bms <= self.refreshed_bms:
            return False, False
        if self.stable_since is None:
            self.stable_since = now
        return now - self.stable_since >= self.stable_seconds, degraded

    def bms_ready(self):
        with self.condition:
            return self._ready_locked()[0]

    # ---- the radio ------------------------------------------------------------------------
    def _eligible(self, kind):
        return (
            kind in {"bms_control", "bms", "bms_manual_connect"}
            or (kind in {"bms_read", "bms_manual_read"} and bool(self.connected_bms))
            or (kind == "balancer" and self._ready_locked()[0])
        )

    def _next_ticket(self):
        eligible = [(self.PRIORITY[kind], seq) for seq, kind in self.tickets.items() if self._eligible(kind)]
        return min(eligible)[1] if eligible else None

    def _expire_locked(self):
        if self.active_kind is None or self.active_since is None:
            return
        held = time.monotonic() - self.active_since
        if held > self.max_hold.get(self.active_kind, 150.0):
            self.forced_releases += 1
            ble_log.log("coordinator", "lease_expired", f"{self.active_kind} held the radio for {held:.0f} s; taken back", failure=True)
            self.active_kind = None
            self.active_token = 0
            self.active_since = None

    def acquire(self, kind, timeout):
        if kind not in self.PRIORITY:
            raise ValueError(f"Unknown Bluetooth queue kind: {kind}")
        deadline = time.monotonic() + max(0, float(timeout))
        with self.condition:
            self._seq += 1
            seq = self._seq
            self.tickets[seq] = kind
            self.waiters[kind] += 1
            try:
                while True:
                    self._expire_locked()
                    if self.active_kind is None and self._next_ticket() == seq:
                        self._tokens += 1
                        self.active_kind = kind
                        self.active_token = self._tokens
                        self.active_since = time.monotonic()
                        return self.active_token
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return 0
                    self.condition.wait(min(0.5, remaining))
            finally:
                self.tickets.pop(seq, None)
                self.waiters[kind] = max(0, self.waiters[kind] - 1)
                self.condition.notify_all()

    def release(self, kind, token=None):
        with self.condition:
            if self.active_kind == kind and (token is None or token == self.active_token):
                self.active_kind = None
                self.active_token = 0
                self.active_since = None
            self.condition.notify_all()

    @contextmanager
    def lease(self, kind, timeout=30):
        token = self.acquire(kind, timeout)
        try:
            yield token
        finally:
            if token:
                self.release(kind, token)

    @asynccontextmanager
    async def alease(self, kind, timeout=30):
        """Like `lease`, but waits in a thread so the caller's event loop keeps running."""
        token = await asyncio.to_thread(self.acquire, kind, timeout)
        try:
            yield token
        finally:
            if token:
                self.release(kind, token)

    def snapshot(self):
        with self.condition:
            ready, degraded = self._ready_locked()
            stable_for = 0 if self.stable_since is None else max(0, time.monotonic() - self.stable_since)
            waiting_bms = sum(self.waiters[k] for k in ("bms_control", "bms_manual_read", "bms_manual_connect", "bms"))
            return {
                "active": self.active_kind,
                "active_for_seconds": None if self.active_since is None else round(time.monotonic() - self.active_since, 1),
                "waiting_bms": waiting_bms,
                "waiting": dict(self.waiters),
                "connected_bms": len(self.connected_bms),
                "refreshed_bms": len(self.refreshed_bms),
                "bms_stable_seconds": round(stable_for, 1),
                "balancers_allowed": ready,
                "degraded": degraded,
                "forced_releases": self.forced_releases,
            }


bluetooth_coordinator = BluetoothCoordinator()
