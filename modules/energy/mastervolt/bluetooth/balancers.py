"""The three DALY balancers: read-only monitoring, one balancer at a time.

Six simultaneous GATT links are not reliable on one Windows adapter, so the BMS links stay open and the balancers are
sampled in turn: connect, read the nine status commands, disconnect. They only run once every BMS link is up and has been
read (or, in *degraded mode*, when one BMS has been away for two minutes). A measurement is published only when every
command was answered, so a half-read balancer never reaches the history.

Each balancer keeps its own schedule: healthy ones follow the refresh interval, failing ones back off exponentially
(retry x 2^n, at most five minutes) so they do not hammer the Windows Bluetooth stack. A stall watchdog first forces a
fresh scan, then rebuilds the worker and flags it as *wedged*; a `Supervisor` also restarts a worker that crashed, died or
hangs (CHANGELOG 1.22.1: a `CancelledError` once ended this thread silently for twenty minutes).
"""

from __future__ import annotations

import asyncio
import importlib.util
import threading
import time
from datetime import UTC, datetime

from .coordinator import bluetooth_coordinator
from .daly_protocol import (
    BALANCER_NAMES,
    NOTIFY_UUID,
    WRITE_UUID,
    FrameAssembler,
    decode,
    decode_alarm_bytes,
    status_request,
)
from .daly_protocol import (
    COMMANDS as PROTOCOL_COMMANDS,
)
from .events import ble_log
from .link import Supervisor, Wakeup, WorkerRestart, drop_client, make_client, open_link, scan_for

DEVICE_NAMES = BALANCER_NAMES
COMMANDS = tuple(PROTOCOL_COMMANDS)
STANDARD_NAMES = {
    "00002a19-0000-1000-8000-00805f9b34fb": "Battery level",
    "00002a24-0000-1000-8000-00805f9b34fb": "Model number",
    "00002a25-0000-1000-8000-00805f9b34fb": "Serial number",
    "00002a26-0000-1000-8000-00805f9b34fb": "Firmware revision",
    "00002a27-0000-1000-8000-00805f9b34fb": "Hardware revision",
    "00002a29-0000-1000-8000-00805f9b34fb": "Manufacturer",
}

# Timing and robustness settings. Module constants so the self-test can shrink them.
INITIAL_DELAY = 8.0  # let the three safety-critical BMS links settle before adding balancers
GATT_TIMEOUT = 6.0  # every single GATT read or write: a hung Windows call must never hold the radio
CONNECT_TIMEOUT = 18.0
NOTIFY_TIMEOUT = 7.0
DISCONNECT_TIMEOUT = 10.0
SCAN_TIMEOUT = 12.0  # upper bound; a scan ends as soon as every wanted balancer has been seen
COMMAND_SPACING = 0.15
FRAME_WAIT = 2.0  # how long to wait for the answers to one round of status requests
READ_ATTEMPTS = 2  # a round is repeated once for the commands that were not answered
SETTLE_SECONDS = 4.0  # Windows releases a finished GATT connection asynchronously
INCOMPLETE_RETRY_SECONDS = 15.0
MAX_BACKOFF_SECONDS = 300.0
WATCHDOG_SECONDS = 600.0  # no successful read for this long while the BMS links are healthy: rebuild the worker
HANG_SECONDS = 300.0  # the worker's event loop made no progress at all for this long: abandon it and start a new one
MONITOR_SECONDS = 10.0  # how often the monitor looks at the worker thread
CRASH_BACKOFF_BASE = 5.0  # seconds before the supervisor restarts a crashed worker (doubles per crash, at most 60 s)
LEASE_WAIT = 8.0  # how long a balancer waits for its turn on the radio
SCAN_LEASE_WAIT = 3.0
LOG_NAME = "balancers"


class BalancerDeferred(RuntimeError):
    """Balancer work intentionally postponed while the BMS has radio priority."""


def describe_value(raw: bytes) -> dict:
    """A GATT value in the forms the diagnostics show: hex, text (when printable) and a little-endian number."""
    raw = bytes(raw)
    text = None
    try:
        decoded = raw.decode("utf-8").strip("\0\r\n ")
        if decoded and all(ch.isprintable() for ch in decoded):
            text = decoded
    except UnicodeDecodeError:
        pass
    return {
        "hex": raw.hex(" ").upper(),
        "text": text,
        "unsigned_le": int.from_bytes(raw, "little") if 0 < len(raw) <= 8 else None,
        "length": len(raw),
    }


class DalyBalancerService:
    def __init__(self, coordinator=None):
        self.coordinator = coordinator or bluetooth_coordinator
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.wake = Wakeup()
        self.ble_available = importlib.util.find_spec("bleak") is not None
        self.settings_getter = lambda: {"balancer_refresh_interval": 30, "balancer_connection_retry_seconds": 30}
        self.clients: dict = {}
        self.assemblers = {name: FrameAssembler() for name in DEVICE_NAMES}
        self.decoded = {name: {} for name in DEVICE_NAMES}
        self.known_devices: dict = {}
        self.connection_failures = {name: 0 for name in DEVICE_NAMES}
        self.static_values: dict = {}
        self.cycle_cursor = 0
        self.single_queue: list[str] = []
        self.refresh_generation = 0
        self.completed_generation = 0
        self.next_due = {name: 0.0 for name in DEVICE_NAMES}
        self.last_success = {name: None for name in DEVICE_NAMES}
        self.last_progress = time.monotonic()
        self.watchdog_level = 0
        self.worker_restarts = 0
        self.restarts_without_success = 0
        self.wedged = False
        self.devices = {
            name: {"name": name, "state": "not_read", "values": [], "status": {}, "error": None, "captured_at": None}
            for name in DEVICE_NAMES
        }
        self.supervisor = Supervisor(
            self._run,
            self.stop_event,
            name="daly-balancers",
            device=LOG_NAME,
            hang_seconds=HANG_SECONDS,
            monitor_seconds=MONITOR_SECONDS,
            crash_backoff=CRASH_BACKOFF_BASE,
            on_crash=self._worker_crashed,
            on_restart=self._worker_restart,
            on_replaced=self._worker_replaced,
        )

    # ---- supervisor hooks ------------------------------------------------------------------------------------
    def _worker_crashed(self, exc: BaseException) -> None:
        for name in DEVICE_NAMES:
            self._set(name, state="error", error=f"Balancer worker crashed ({exc}); restarting automatically")

    def _worker_restart(self, exc: BaseException) -> None:
        self.restarts_without_success += 1
        self.wedged = self.restarts_without_success >= 3
        ble_log.log(LOG_NAME, "worker_restart", f"{exc} (restart {self.restarts_without_success} without a successful read)", failure=True)

    def _worker_replaced(self, reason: str) -> None:
        self.worker_restarts += 1

    # ---- lifecycle -------------------------------------------------------------------------------------------
    @property
    def thread(self):
        return self.supervisor.thread

    def start(self, settings_getter=None) -> None:
        if self.supervisor.alive:
            return
        if settings_getter:
            self.settings_getter = settings_getter
        self.stop_event.clear()
        if not self.ble_available:
            for name in DEVICE_NAMES:
                self._set(name, state="error", error="Windows Bluetooth component unavailable")
            return
        self.supervisor.hang_seconds, self.supervisor.monitor_seconds, self.supervisor.crash_backoff = (
            HANG_SECONDS,
            MONITOR_SECONDS,
            CRASH_BACKOFF_BASE,
        )
        self.supervisor.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.wake.set()
        self.supervisor.join(timeout=8)

    # ---- requests from the API -------------------------------------------------------------------------------
    def refresh_all(self) -> dict:
        self.refresh_generation += 1
        self.wake.set()
        return {"accepted": True, "generation": self.refresh_generation}

    def refresh_one(self, name: str) -> dict:
        """Queue a manual refresh of one balancer; the next cycle reads only that balancer."""
        if name not in DEVICE_NAMES:
            raise ValueError("Unknown balancer")
        if not self.ble_available:
            raise RuntimeError("Windows Bluetooth component unavailable")
        with self.lock:
            if name not in self.single_queue:
                self.single_queue.append(name)
            if self.devices[name].get("state") in ("not_read", "connected", "disconnected", "error"):
                self.devices[name] = {**self.devices[name], "state": "queued", "error": None}
        self.wake.set()
        return {"started": True, "device": name}

    def _requeue_manual(self, names) -> None:
        """Put unfinished manual refreshes back in front so a deferred attempt is retried."""
        with self.lock:
            for name in reversed(names):
                if name not in self.single_queue:
                    self.single_queue.insert(0, name)
        self.wake.set()

    def snapshot(self) -> dict:
        settings = self.settings_getter()
        interval = float(settings["balancer_refresh_interval"])
        now = time.monotonic()
        stale_after = max(180.0, 4 * interval)
        with self.lock:
            devices = {}
            for name, value in self.devices.items():
                age = None if self.last_success[name] is None else now - self.last_success[name]
                devices[name] = {
                    **value,
                    "connection_failures": self.connection_failures[name],
                    "values": [dict(item) for item in value.get("values", [])],
                    "last_success_age_seconds": None if age is None else round(age, 1),
                    "stale": age is not None and age > stale_after,
                    "next_attempt_in_seconds": max(0.0, round(self.next_due[name] - now, 1)),
                }
            return {
                "ble_available": self.ble_available,
                "persistent_connections": False,
                "connection_mode": "sequential-read-disconnect",
                "shared_discovery": True,
                "busy": self.completed_generation < self.refresh_generation,
                "refresh_generation": self.refresh_generation,
                "completed_generation": self.completed_generation,
                "refresh_interval_seconds": int(interval),
                "retry_interval_seconds": int(settings["balancer_connection_retry_seconds"]),
                "coordinator": self.coordinator.snapshot(),
                "wedged": self.wedged,
                "worker_alive": self.supervisor.alive,
                "worker_restarts": self.worker_restarts,
                "watchdog_level": self.watchdog_level,
                "devices": devices,
            }

    def _set(self, name: str, **updates) -> None:
        with self.lock:
            self.devices[name] = {**self.devices[name], **updates}

    # ---- scheduling ------------------------------------------------------------------------------------------
    def _schedule(self, name: str, ok: bool, incomplete: bool = False, deferred: bool = False) -> None:
        """Decide when this balancer is due again."""
        settings = self.settings_getter()
        interval = float(settings["balancer_refresh_interval"])
        base = float(settings["balancer_connection_retry_seconds"])
        if deferred:
            delay = 2.0
        elif ok:
            delay = interval
        elif incomplete:
            delay = INCOMPLETE_RETRY_SECONDS
        else:
            delay = min(MAX_BACKOFF_SECONDS, base * 2 ** (min(max(1, self.connection_failures[name]), 8) - 1))
        self.next_due[name] = time.monotonic() + delay

    def _watchdog(self) -> None:
        """A balancer stall while the BMS links are healthy first forces a fresh scan, then a rebuild of the worker."""
        stalled = time.monotonic() - self.last_progress
        if stalled >= WATCHDOG_SECONDS:
            self.watchdog_level = 2
            self.worker_restarts += 1
            self.last_progress = time.monotonic()
            raise WorkerRestart(f"no successful balancer read for {stalled:.0f} s while the BMS links are healthy")
        if stalled >= WATCHDOG_SECONDS / 2 and self.watchdog_level < 1:
            self.watchdog_level = 1
            self.known_devices.clear()
            for name in DEVICE_NAMES:
                self.connection_failures[name] = 0
            ble_log.log(
                LOG_NAME, "watchdog_rescan", f"no successful balancer read for {stalled:.0f} s; forgetting known devices", failure=True
            )

    # ---- radio work ------------------------------------------------------------------------------------------
    async def _discover(self, names: list[str]) -> dict:
        """Find every missing balancer in one radio scan instead of three competing scans."""
        if not names:
            return {}
        async with self.coordinator.alease("balancer", timeout=SCAN_LEASE_WAIT) as granted:
            if not granted:
                raise BalancerDeferred("Waiting for BMS connection priority")
            with ble_log.timed(LOG_NAME, "scan"):
                matches, signal = await scan_for(names, DEVICE_NAMES, SCAN_TIMEOUT)
        show = lambda name: f"{name} ({signal[name]} dBm)" if name in signal else name  # noqa: E731
        others = [name for name in signal if name not in matches]
        ble_log.log(
            LOG_NAME,
            "scan",
            f"looked for {', '.join(names)}; found {', '.join(show(name) for name in matches) or 'none'}"
            + (f"; also visible {', '.join(show(name) for name in others)}" if others else ""),
        )
        return matches

    async def _disconnect(self, name: str, client=None) -> None:
        await drop_client(client or self.clients.pop(name, None), name, timeout=DISCONNECT_TIMEOUT)

    async def _connect(self, name: str, device) -> None:
        self._set(name, state="scanning", error=None)
        if not device:
            raise RuntimeError(f"{name} not found; retrying automatically")
        self.known_devices[name] = device
        self._set(name, state="connecting")

        def disconnected(disconnected_client, n=name):
            # A deliberate read-complete disconnect pops the client first and must not replace the successful snapshot.
            if self.clients.get(n) is disconnected_client:
                self.clients.pop(n, None)
                self._set(n, state="disconnected", error="Bluetooth connection lost; retrying automatically")

        client = make_client(device, timeout=15, disconnected_callback=disconnected)
        ble_log.log(name, "connect_try", quiet=True)
        try:
            await open_link(
                client,
                name,
                NOTIFY_UUID,
                lambda sender, data, n=name: self._notification(n, sender, data),
                connect_timeout=CONNECT_TIMEOUT,
                notify_timeout=NOTIFY_TIMEOUT,
            )
        except BaseException:
            await self._disconnect(name, client)
            raise
        self.clients[name] = client
        self.connection_failures[name] = 0
        self._set(name, state="connected", error=None)
        ble_log.log(name, "connect_ok", quiet=True)

    def _notification(self, name: str, sender, data) -> None:
        uuid = str(getattr(sender, "uuid", sender)).lower()
        value = describe_value(data)
        with self.lock:
            rows = self.devices[name].get("values", [])
            for row in rows:
                if row.get("uuid") == uuid:
                    frames = list(row.get("frames_hex", []))
                    frames.append(value["hex"])
                    row.update(value)
                    row["frames_hex"] = frames[-50:]
                    row["source"] = "notification"
                    break
            else:
                rows.append(
                    {
                        "service": "—",
                        "uuid": uuid,
                        "label": STANDARD_NAMES.get(uuid, "Unknown characteristic"),
                        "properties": ["notify"],
                        "source": "notification",
                        "frames_hex": [value["hex"]],
                        **value,
                    }
                )
        if uuid == NOTIFY_UUID:
            self._consume_frames(name, data)

    def _consume_frames(self, name: str, data) -> None:
        """Feed the stream to the frame assembler and keep the decoded answers (the status is published once complete)."""
        for frame in self.assemblers[name].feed(data):
            command, values = decode(frame)
            # Standalone DALY balancers reuse byte 3 of the 0x93 payload for the balance current in 0.01 A: live frames 0x55
            # and 0x32 are 0.85 A and 0.50 A. The 0x90 pack current is unrelated (it legitimately stays zero while balancing).
            if command == 0x93:
                values["balance_current_a"] = frame[7] / 100
            with self.lock:
                self.decoded[name].setdefault(command, []).append(values)
                self.decoded[name][command] = self.decoded[name][command][-16:]

    def _update_status(self, name: str) -> None:
        groups = self.decoded[name]
        last = lambda command: (groups.get(command) or [{}])[-1]  # noqa: E731
        summary, limits, activity, meta, balance, alarm = last(0x90), last(0x91), last(0x93), last(0x94), last(0x97), last(0x98)
        cell_count = meta.get("cell_count", 0)
        cells = []
        for group in sorted(groups.get(0x95, []), key=lambda item: item.get("frame_number", 0)):
            cells.extend(group.get("cell_voltages_mv", []))
        if cell_count:
            cells = cells[:cell_count]
        temperatures = []
        for group in sorted(groups.get(0x96, []), key=lambda item: item.get("frame_number", 0)):
            temperatures.extend(group.get("temperatures_c", []))
        sensor_count = meta.get("temperature_sensor_count", 0)
        if sensor_count:
            temperatures = temperatures[-sensor_count:]
        high, low = limits.get("highest_cell_mv"), limits.get("lowest_cell_mv")
        if cells:
            high, low = max(cells), min(cells)
        balancing = [n for n in balance.get("balancing_cells", []) if not cell_count or n <= cell_count]
        status = {
            "balance_active": bool(balancing),
            "balance_position": balancing,
            "reported_current_a": activity.get("balance_current_a"),
            "pack_voltage_v": summary.get("pack_voltage_v"),
            "highest_cell_mv": high,
            "lowest_cell_mv": low,
            "average_cell_mv": sum(cells) / len(cells) if cells else None,
            "cell_delta_mv": high - low if high is not None and low is not None else None,
            "cells_mv": cells,
            "temperatures_c": temperatures,
            "cell_count": cell_count or len(cells) or None,
            "cycles": meta.get("charge_discharge_cycles"),
            "alarms": decode_alarm_bytes(alarm.get("alarm_bytes_hex", "")),
            "valid_frame_count": sum(len(items) for items in groups.values()),
        }
        with self.lock:
            self.devices[name]["status"] = status
            self.devices[name]["captured_at"] = datetime.now(UTC).isoformat()

    async def _static_rows(self, name: str, client) -> list:
        """Device information (model, serial, GATT layout) never changes: read it once per balancer, not on every cycle."""
        if name in self.static_values:
            return self.static_values[name]
        rows = []
        clean = True
        for service in client.services:
            for char in service.characteristics:
                properties = list(char.properties)
                base = {
                    "service": str(service.uuid).lower(),
                    "uuid": str(char.uuid).lower(),
                    "label": STANDARD_NAMES.get(str(char.uuid).lower(), char.description or "Unknown characteristic"),
                    "properties": properties,
                }
                if "read" in properties:
                    try:
                        rows.append(
                            {
                                **base,
                                "source": "read",
                                **describe_value(await asyncio.wait_for(client.read_gatt_char(char), timeout=GATT_TIMEOUT)),
                            }
                        )
                    except Exception as exc:
                        clean = False
                        rows.append(
                            {
                                **base,
                                "source": "read error",
                                "hex": "",
                                "text": None,
                                "unsigned_le": None,
                                "length": 0,
                                "error": str(exc) or type(exc).__name__,
                            }
                        )
                elif "notify" in properties or "indicate" in properties:
                    rows.append({**base, "source": "waiting for notification", "hex": "", "text": None, "unsigned_le": None, "length": 0})
                else:
                    rows.append({**base, "source": "not readable", "hex": "", "text": None, "unsigned_le": None, "length": 0})
        if clean:
            self.static_values[name] = rows
        return rows

    async def _wait_frames(self, name: str, commands) -> None:
        deadline = time.monotonic() + FRAME_WAIT
        while time.monotonic() < deadline:
            if all(command in self.decoded[name] for command in commands):
                return
            await asyncio.sleep(0.02)

    async def _read(self, name: str) -> bool:
        """Request every status command, repeat the unanswered ones once, publish only a complete status.
        Returns False (and publishes nothing) when commands stay unanswered."""
        started = time.monotonic()
        client = self.clients[name]
        rows = await self._static_rows(name, client)
        self._set(name, state="connected", values=[dict(row) for row in rows], error=None)
        if not any(str(char.uuid).lower() == WRITE_UUID for service in client.services for char in service.characteristics):
            raise RuntimeError(f"{name} has no DALY command channel")
        # The FFF1 data channel stays silent until the app requests status. Probe only DALY's documented read range;
        # never send configuration writes.
        self.assemblers[name].clear()
        self.decoded[name] = {}
        pending = list(COMMANDS)
        for attempt in range(1, READ_ATTEMPTS + 1):
            for command in pending:
                await asyncio.wait_for(client.write_gatt_char(WRITE_UUID, status_request(command), response=False), timeout=GATT_TIMEOUT)
                await asyncio.sleep(COMMAND_SPACING)
            await self._wait_frames(name, pending)
            pending = [command for command in COMMANDS if command not in self.decoded[name]]
            if not pending:
                break
            ble_log.log(name, "read_retry", f"attempt {attempt}: no answer to {', '.join(f'0x{c:02X}' for c in pending)}")
        if pending:
            message = f"Incomplete status: no answer to {', '.join(f'0x{c:02X}' for c in pending)}"
            self._set(name, state="connected", error=message)
            ble_log.log(name, "read_incomplete", message, failure=True)
            ble_log.timing(name, "read", time.monotonic() - started, False)
            return False
        self._update_status(name)
        ble_log.timing(name, "read", time.monotonic() - started, True)
        ble_log.log(
            name,
            "read_ok",
            f"{sum(len(v) for v in self.decoded[name].values())} frames in {time.monotonic() - started:.1f} s",
            success=True,
            quiet=True,
        )
        return True

    async def _disconnect_all(self) -> None:
        for name in list(self.clients):
            await self._disconnect(name)

    async def _idle(self) -> None:
        """Sleep until the next balancer is due, a manual/full refresh is requested, or the service stops."""
        deadline = min(self.next_due.values())
        while not self.stop_event.is_set() and time.monotonic() < deadline and not self.wake.is_set():
            self.supervisor.heartbeat()
            await self.wake.wait(min(0.25, max(0.005, deadline - time.monotonic())))
        if self.wake.is_set() and self.refresh_generation <= self.completed_generation and not self.single_queue:
            self.wake.clear()

    # ---- the worker loop -------------------------------------------------------------------------------------
    async def _read_one(self, name: str, device, manual: list[str]) -> tuple[bool, bool, bool]:
        """One balancer: take the radio, connect, read, disconnect. Returns (ok, incomplete, deferred)."""
        ok = incomplete = False
        held_from = None
        asked = time.monotonic()
        try:
            # One lease covers connect, notifications, read and all request frames, so a BMS operation can no longer slip
            # in between connect and read and leave a stale wait state.
            async with self.coordinator.alease("balancer", timeout=LEASE_WAIT) as granted:
                ble_log.timing(name, "radio_wait", time.monotonic() - asked, bool(granted))
                if not granted:
                    raise BalancerDeferred("Queued for Bluetooth radio")
                held_from = time.monotonic()
                await self._connect(name, device)
                ok = await self._read(name)
                incomplete = not ok
        except BalancerDeferred as exc:
            await self._disconnect(name)
            self._set(name, state="queued", error=str(exc))
            self._schedule(name, False, deferred=True)
            return False, False, True
        except (Exception, asyncio.CancelledError) as exc:
            phase = "read_failed" if name in self.clients else "connect_failed"  # the client is only registered after a successful connect
            await self._disconnect(name)
            self.connection_failures[name] += 1
            if self.connection_failures[name] >= 2:
                self.known_devices.pop(name, None)
            message = str(exc).strip() or f"{name} connection timed out; retrying automatically"
            self._set(name, state="error", error=message)
            after = f" (after {time.monotonic() - held_from:.1f} s on the radio)" if held_from else ""
            ble_log.log(name, phase, f"{type(exc).__name__}: {message}{after}", failure=True)
        finally:
            if held_from:
                ble_log.timing(name, "radio_hold", time.monotonic() - held_from, ok)
            await self._disconnect(name)
        if ok:
            self.last_success[name] = time.monotonic()
            self.last_progress = self.last_success[name]
            self.watchdog_level = 0
            self.restarts_without_success = 0
            self.wedged = False
        self._schedule(name, ok, incomplete=incomplete)
        return ok, incomplete, False

    def _plan(self) -> tuple[list[str], list[str], int, bool]:
        """(targets, manual, generation, complete): who to read in this cycle."""
        with self.lock:
            manual = [name for name in self.single_queue if name in DEVICE_NAMES]
            self.single_queue.clear()
        full = self.refresh_generation > self.completed_generation
        if manual:
            # A manual refresh of the clicked balancer(s): they go first and nothing else is read in this cycle. It never
            # completes a "Refresh all" generation.
            return manual, manual, self.refresh_generation, False
        rotated = list(DEVICE_NAMES[self.cycle_cursor :] + DEVICE_NAMES[: self.cycle_cursor])
        # A device that timed out must not remain disadvantaged in the third position: failed devices go first, healthy ones rotate.
        order = sorted(rotated, key=lambda name: (self.devices[name].get("state") != "error", -self.connection_failures[name]))
        now = time.monotonic()
        targets = order if full else [name for name in order if self.next_due[name] <= now]
        if targets:
            self.cycle_cursor = (self.cycle_cursor + 1) % len(DEVICE_NAMES)
        return targets, [], self.refresh_generation, full

    async def _run(self, epoch: int = 0) -> None:
        await asyncio.sleep(INITIAL_DELAY)
        self.wake.bind()
        self.last_progress = time.monotonic()
        was_ready = False
        try:
            while self.supervisor.current(epoch):
                self.supervisor.heartbeat()
                if not self.coordinator.bms_ready():
                    for name in DEVICE_NAMES:
                        self._set(name, state="waiting", error="Waiting for all BMS connections and initial readings")
                    self.last_progress = time.monotonic()  # waiting for the BMS links is not a balancer stall
                    was_ready = False
                    await asyncio.sleep(1)
                    continue
                if not was_ready:
                    self.last_progress = time.monotonic()  # the stall clock starts when the balancers may run
                    was_ready = True
                for name in DEVICE_NAMES:
                    if self.devices[name].get("state") == "waiting":
                        self._set(name, state="queued", error=None)
                self._watchdog()
                targets, manual, generation, complete = self._plan()
                if not targets:
                    await self._idle()
                    continue
                discover_names = [name for name in targets if name not in self.known_devices or self.connection_failures[name] >= 2]
                for name in discover_names:
                    if self.connection_failures[name] >= 2:
                        self.known_devices.pop(name, None)
                    self._set(name, state="scanning", error=None)
                discovered: dict = {}
                if discover_names:
                    try:
                        discovered = await self._discover(discover_names)
                    except BalancerDeferred as exc:
                        for name in discover_names:
                            self._set(name, state="waiting", error=str(exc))
                        if manual:
                            self._requeue_manual(manual)
                        await asyncio.sleep(1)
                        continue
                    except (Exception, asyncio.CancelledError) as exc:
                        ble_log.log(LOG_NAME, "scan_failed", repr(exc), failure=True)
                        for name in discover_names:
                            self._set(name, state="error", error=f"Bluetooth scan failed: {exc}")
                for name in targets:
                    if not self.supervisor.current(epoch):
                        break
                    self.supervisor.heartbeat()
                    # A manual refresh request overtakes the rest of a running full cycle.
                    if not manual and self.single_queue:
                        complete = False
                        break
                    device = discovered.get(name) or self.known_devices.get(name)
                    _, _, deferred = await self._read_one(name, device, manual)
                    if deferred:
                        complete = False
                        if manual:
                            self._requeue_manual(manual[manual.index(name) :])
                        break
                    # Windows frequently releases a completed GATT connection asynchronously; this pause keeps the next
                    # balancer from colliding with the controller cleanup.
                    await asyncio.sleep(SETTLE_SECONDS)
                if complete:
                    self.completed_generation = max(self.completed_generation, generation)
                if self.refresh_generation <= self.completed_generation and not self.single_queue:
                    self.wake.clear()
        finally:
            if epoch is None or epoch == self.supervisor.epoch:  # a replaced worker must not close the new worker's links
                await self._disconnect_all()
