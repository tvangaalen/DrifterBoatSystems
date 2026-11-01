"""The three DALY BMS units: persistent Bluetooth links, periodic status reads and the guarded MOS/SOC controls.

One `BatteryWorker` per battery owns a thread with its own asyncio loop, so a stuck Windows call on one battery can never
freeze the others (failure isolation). The link stays open; the status (nine DALY commands) is read every
`bms_refresh_interval` seconds. All radio work goes through the `BluetoothCoordinator` (user controls > manual refresh >
reconnect > automatic reads > balancers). A status is published only when complete, so the history never gets holes.

Controls (charge/discharge MOS, SOC) write, read back and verify. Some DALY firmware variants disagree on whether payload
`1` means ON, so the encoding is learned per battery and per MOS from the read-back (`data/bms_mos_encoding.json`).
Protection-threshold registers are deliberately never accessed.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import importlib.util
import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path

from ..config import PATHS, Paths
from .coordinator import bluetooth_coordinator
from .daly_protocol import (
    BATTERY_NAMES,
    COMMANDS,
    NOTIFY_UUID,
    SOC_CHARGING_POINTS,
    SOC_DISCHARGING_POINTS,
    WRITE_UUID,
    FrameAssembler,
    snapshot_from_frames,
    soc_from_average_mv,
    status_request,
    write_frame,
)
from .events import ble_log
from .link import Supervisor, Wakeup, drop_client, make_client, open_link

log = logging.getLogger("mastervolt.bms")

DEVICE_NAMES = BATTERY_NAMES
CONTROL_WATCHDOG_SECONDS = 120
CONNECT_TIMEOUT = 18.0  # hard deadline for connect and for start_notify: a hung Windows call must not hold the radio
NOTIFY_TIMEOUT = 7.0
DISCONNECT_TIMEOUT = 5.0
BMS_MAX_BACKOFF = 60.0  # a battery that cannot be reached is retried after retry*2^n seconds, at most this long
INCOMPLETE_LIMIT = 3  # consecutive incomplete status reads before the link is rebuilt
INCOMPLETE_RETRY_SECONDS = 10.0
GATT_TIMEOUT = 4.0  # every status request; a lost request is retried once before the link is torn down
COMMAND_SPACING = 0.25
REPLY_WAIT = 1.0
RETRY_REPLY_WAIT = 0.6
STARTUP_STAGGER = 1.0  # seconds between the starts of the three battery workers
CONNECTION_PAUSE = 1.0  # minimum time between two connection attempts of any battery
READ_WAIT = 6.0  # how long an automatic read waits for the radio (another read holds it for about 3.5 s)
MANUAL_WAIT = 35.0  # how long a manual refresh or reconnect waits for the radio
CONNECT_WAIT = 25.0
SCAN_TIMEOUT = 10.0
RESCAN_AFTER_FAILURES = 3  # a known device that fails this many attempts in a row is looked for again
HANG_SECONDS = 300.0  # a worker loop without progress for this long is replaced
MONITOR_SECONDS = 10.0
CRASH_BACKOFF_BASE = 5.0
CONTROL_ACTIONS = {"set_soc_100", "set_soc_charge", "set_soc_discharge", "set_soc_value", "charge", "discharge"}
ALL_ACTIONS = {
    "set_soc_100",
    "set_soc_charge",
    "set_soc_discharge",
    "set_soc_value",
    "charge_on",
    "charge_off",
    "discharge_on",
    "discharge_off",
}


def _soc_payload(percent: float) -> bytes:
    """SOC register 0x21: six zero bytes and the percentage x10 as a 16-bit big-endian number."""
    return b"\0" * 6 + int(round(percent * 10)).to_bytes(2, "big")


class BatteryWorker:
    """One isolated Windows/Bleak event loop for one DALY battery."""

    def __init__(self, service: DalyBmsService, name: str, index: int):
        self.service, self.name, self.index = service, name, index
        self.loop = None
        self.client = None
        self.device = None
        self.device_name = name
        self.stop_event = threading.Event()
        self.refresh_event = Wakeup()
        self.assembler = FrameAssembler()
        self.frames: list[bytes] = []
        self.last_refresh = 0.0
        self.completed_generation = 0
        self.connection_failures = 0  # consecutive failed attempts: drives the back-off, reset only by a successful connect
        self.attempts_since_scan = 0  # failed attempts since the device was last (re)discovered
        self.incomplete_streak = 0
        self.operation_lock = None
        self.supervisor = Supervisor(
            self._run,
            self.stop_event,
            name=f"daly-{name.lower().replace(' ', '-')}",
            device=name,
            hang_seconds=HANG_SECONDS,
            monitor_seconds=MONITOR_SECONDS,
            crash_backoff=CRASH_BACKOFF_BASE,
            on_crash=lambda exc: service.set_state(name, "error", f"Worker crashed ({exc!r}); restarting automatically"),
        )

    @property
    def thread(self):
        return self.supervisor.thread

    def start(self) -> None:
        self.stop_event.clear()
        self.supervisor.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.refresh_event.set()
        self.supervisor.join(timeout=4)

    def connected(self) -> bool:
        return bool(self.client and self.client.is_connected)

    # ---- link ------------------------------------------------------------------------------------------------
    def _notified(self, _sender, payload) -> None:
        self.frames.extend(self.assembler.feed(payload))

    async def _disconnect(self) -> None:
        client, self.client = self.client, None
        self.service.coordinator.mark_bms(self.name, False)
        await drop_client(client, self.name, timeout=DISCONNECT_TIMEOUT)

    async def _find_device(self) -> None:
        from bleak import BleakScanner

        def wanted(device, advertisement):
            hit = self.name.casefold() in (getattr(advertisement, "local_name", None) or getattr(device, "name", None) or "").casefold()
            if hit and isinstance(getattr(advertisement, "rssi", None), int):
                ble_log.rssi(self.name, advertisement.rssi)
            return hit

        found = await BleakScanner.find_device_by_filter(wanted, timeout=SCAN_TIMEOUT)
        if found is None:
            raise RuntimeError(f"{self.name} was not found. Wake it and close the DALY phone app.")
        self.device = found
        self.device_name = getattr(found, "name", None) or self.name
        self.attempts_since_scan = 0  # finding the device is not a successful connect: the back-off keeps growing

    async def _connect(self, queue_kind: str = "bms") -> bool:
        """Take the radio, (re)discover the device when needed, connect and start notifications. Always releases the radio."""
        service, coordinator = self.service, self.service.coordinator
        service.set_state(self.name, "scanning", None)
        # The coordinator's acquire blocks: run it outside this worker's event loop so finished BLE coroutines can always
        # publish their result. If Windows wedges the holder, its lease expires so it cannot starve the other batteries.
        asked = time.monotonic()
        owns_slot = await asyncio.to_thread(
            coordinator.acquire, queue_kind, MANUAL_WAIT if queue_kind == "bms_manual_connect" else CONNECT_WAIT
        )
        ble_log.timing(self.name, "radio_wait", time.monotonic() - asked, bool(owns_slot))
        if not owns_slot:
            service.set_state(self.name, "waiting", "Waiting for Bluetooth connection slot")
            return False
        half_open = None
        held_from = time.monotonic()
        try:
            await service.wait_connection_pause()
            if self.device is None or self.attempts_since_scan >= RESCAN_AFTER_FAILURES:
                await self._find_device()
            service.set_state(self.name, "connecting", None, device_name=self.device_name)

            def disconnected(client):
                if self.client is client:
                    self.client = None
                    ble_log.log(self.name, "link_lost", "the Bluetooth link dropped", failure=True)
                coordinator.mark_bms(self.name, False)
                service.set_state(self.name, "disconnected", "Bluetooth connection lost; reconnecting automatically")
                self.refresh_event.set()

            client = half_open = make_client(self.device, timeout=12, disconnected_callback=disconnected)
            ble_log.log(self.name, "connect_try", quiet=True)
            await open_link(client, self.name, NOTIFY_UUID, self._notified, connect_timeout=CONNECT_TIMEOUT, notify_timeout=NOTIFY_TIMEOUT)
            self.client, half_open, self.connection_failures, self.attempts_since_scan = client, None, 0, 0
            coordinator.mark_bms(self.name, True)
            service.set_state(self.name, "connected", None, device_name=self.device_name)
            ble_log.log(self.name, "connect_ok", success=True, quiet=True)
            return True
        except BaseException as exc:
            self.connection_failures += 1
            self.attempts_since_scan += 1
            await self._disconnect()
            await drop_client(
                half_open, self.name, timeout=DISCONNECT_TIMEOUT
            )  # connected but never finished notifications: do not leak it
            message = (
                f"{type(exc).__name__}: {str(exc).strip()}"
                if str(exc).strip()
                else f"{type(exc).__name__} (connect/notify did not finish in time)"
            )
            ble_log.log(self.name, "connect_failed", f"{message} (after {time.monotonic() - held_from:.1f} s on the radio)", failure=True)
            service.set_state(self.name, "error", str(exc) or f"{self.name} connection failed")
            return False
        finally:
            service.record_connection_attempt()
            ble_log.timing(self.name, "radio_hold", time.monotonic() - held_from, self.client is not None)
            coordinator.release(queue_kind, owns_slot)

    # ---- reading ---------------------------------------------------------------------------------------------
    async def _refresh(self, generation: int = 0, manual: bool = False) -> bool:
        async with self.operation_lock:
            return await self._refresh_unlocked(generation, manual=manual)

    async def _send_requests(self, commands, spacing: float, radio_owned: bool) -> None:
        for index, command in enumerate(commands, 1):
            if radio_owned:
                self.service.progress(f"verifying values ({index}/9)")
            for attempt in (1, 2):  # one retry for a single lost request before the whole link is torn down
                try:
                    await asyncio.wait_for(
                        self.client.write_gatt_char(WRITE_UUID, status_request(command), response=False), timeout=GATT_TIMEOUT
                    )
                    break
                except TimeoutError:
                    if attempt >= 2:
                        raise
                    if radio_owned:
                        self.service.progress(f"verification {index}/9 timed out; retrying")
                    await asyncio.sleep(0.3)
            await asyncio.sleep(spacing)

    def _missing(self) -> list[int]:
        answered = {frame[2] for frame in list(self.frames)}
        return [command for command in COMMANDS if command not in answered]

    async def _refresh_unlocked(
        self, generation: int = 0, radio_owned: bool = False, raise_on_error: bool = False, manual: bool = False
    ) -> bool:
        service, coordinator = self.service, self.service.coordinator
        if not self.connected():
            self.completed_generation = max(self.completed_generation, generation)
            return False
        queue_kind = "bms_manual_read" if manual else "bms_read"
        asked = time.monotonic()
        owns_slot = radio_owned or await asyncio.to_thread(coordinator.acquire, queue_kind, MANUAL_WAIT if manual else READ_WAIT)
        if not radio_owned:
            ble_log.timing(self.name, "radio_wait", time.monotonic() - asked, bool(owns_slot))
        if not owns_slot:
            self.refresh_event.set()
            return False
        try:
            service.set_state(self.name, "reading", None)
            self.frames = []
            self.assembler.clear()
            read_started = time.monotonic()
            await self._send_requests(COMMANDS, COMMAND_SPACING, radio_owned)
            await asyncio.sleep(REPLY_WAIT)
            if not radio_owned:
                # Monitoring reads only: ask once more for commands that were not answered, and never publish a partial
                # status (missing cells or temperatures would leave holes in the history). Control verification keeps its
                # own strict behaviour.
                missing = self._missing()
                if missing:
                    ble_log.log(self.name, "read_retry", f"no answer to {', '.join(f'0x{c:02X}' for c in missing)}")
                    for command in missing:
                        await asyncio.wait_for(
                            self.client.write_gatt_char(WRITE_UUID, status_request(command), response=False), timeout=GATT_TIMEOUT
                        )
                        await asyncio.sleep(COMMAND_SPACING)
                    await asyncio.sleep(RETRY_REPLY_WAIT)
                    missing = self._missing()
                if missing:
                    self.incomplete_streak += 1
                    message = f"{self.name} returned an incomplete status (no answer to {', '.join(f'0x{c:02X}' for c in missing)})"
                    ble_log.log(self.name, "read_incomplete", message, failure=True)
                    ble_log.timing(self.name, "read", time.monotonic() - read_started, False)
                    if self.incomplete_streak >= INCOMPLETE_LIMIT:
                        raise RuntimeError(f"{message} {self.incomplete_streak} times in a row")
                    service.set_state(self.name, "connected", message)
                    interval = max(2, int(service.settings_getter()["bms_refresh_interval"]))
                    self.last_refresh = time.monotonic() - interval + INCOMPLETE_RETRY_SECONDS  # look again shortly
                    return False
                self.incomplete_streak = 0
            service.set_snapshot(self.name, snapshot_from_frames(self.name, self.device_name, list(self.frames)))
            coordinator.mark_bms_refreshed(self.name)
            ble_log.log(self.name, "read_ok", success=True, quiet=True)
            if not radio_owned:
                ble_log.timing(self.name, "read", time.monotonic() - read_started, True)
            self.last_refresh = time.monotonic()
            return True
        except BaseException as exc:
            message = f"{self.name} verification read failed: {str(exc).strip() or type(exc).__name__}"
            service.set_state(self.name, "error", message)
            await self._disconnect()
            if raise_on_error:
                raise RuntimeError(message) from exc
            return False
        finally:
            if not radio_owned:
                coordinator.release(queue_kind, owns_slot)
            self.completed_generation = max(self.completed_generation, generation)

    # ---- controls --------------------------------------------------------------------------------------------
    async def _write(self, command: int, payload: bytes, timeout: float = 8) -> None:
        await asyncio.wait_for(self.client.write_gatt_char(WRITE_UUID, write_frame(command, payload), response=False), timeout=timeout)

    def _require_link(self) -> None:
        if not self.connected():
            raise RuntimeError(f"{self.name} Bluetooth connection was lost")

    async def control(self, action: str, enabled=None) -> dict:
        """Run one verified control on this battery (the caller holds the radio via the coordinator)."""
        async with self.operation_lock:
            service = self.service
            latest = service.get_battery(self.name)
            cells = latest.get("cells_mv") or []
            average = sum(cells) / len(cells) if cells else None
            soc_charge = soc_from_average_mv(average, SOC_CHARGING_POINTS) if average is not None else None
            soc_discharge = soc_from_average_mv(average, SOC_DISCHARGING_POINTS) if average is not None else None
            manual_percent = None
            if action == "set_soc_value":
                try:
                    manual_percent = float(enabled)
                except (TypeError, ValueError):
                    raise RuntimeError(f"{self.name}: invalid manual SOC value") from None
                if not 0 <= manual_percent <= 100:
                    raise RuntimeError(f"{self.name}: SOC must be between 0 and 100%")
            self._require_link()
            if action in {"set_soc_charge", "set_soc_discharge"} and average is None:
                raise RuntimeError(f"{self.name} has no cell-voltage data")
            self._require_link()
            if action in {"charge", "discharge"}:
                return await self._set_mos(action, bool(enabled), latest)
            percent = {
                "set_soc_100": 100.0,
                "set_soc_charge": soc_charge or 0,
                "set_soc_discharge": soc_discharge or 0,
                "set_soc_value": manual_percent or 0,
            }[action]
            payload = _soc_payload(percent)
            for attempt in (1, 2):
                service.progress(f"sending setting (attempt {attempt}/2)")
                try:
                    await self._write(0x21, payload)
                    break
                except TimeoutError as exc:
                    if attempt == 2:
                        raise RuntimeError(f"{self.name} did not accept the setting after 2 attempts: Bluetooth write timed out") from exc
                    await asyncio.sleep(0.5)
            service.progress("waiting for BMS confirmation")
            await asyncio.sleep(1)
            await self._refresh_unlocked(radio_owned=True, raise_on_error=True)
            service.progress("verification complete")
            await asyncio.sleep(0)  # let run_coroutine_threadsafe deliver the result before any background work is considered
            selected = {"set_soc_charge": soc_charge, "set_soc_discharge": soc_discharge, "set_soc_value": manual_percent}.get(action)
            return {"changed": True, "battery": self.name, "action": action, "enabled": enabled, "soc_percent": selected}

    async def _set_mos(self, action: str, desired: bool, latest: dict) -> dict:
        """Switch one MOSFET and verify it by reading the status back.

        A write that was merely accepted does not count: some units accept a frame without applying it, and this hardware has
        shown the *other* MOS changing as a side effect. The unrelated MOS is preserved and restored when it moved.
        """
        service = self.service
        command = {"charge": 0xDA, "discharge": 0xD9}[action]
        target_field = f"{action}_mosfet_on"
        other_action = "discharge" if action == "charge" else "charge"
        other_field = f"{other_action}_mosfet_on"
        original_other = latest.get(other_field)
        if original_other not in (True, False):
            raise RuntimeError(f"{self.name} has no verified {other_action} MOS state")
        last_state: dict = {}
        learned = service.mos_encoding(self.name, action)
        for attempt in (1, 2):
            # DALY firmware families disagree on whether payload 1 means ON. Use the learned per-device mapping; while it is
            # unknown, probe both encodings and keep only a verified one. The second attempt always tries the opposite.
            preferred = True if learned is None else learned
            one_means_on = preferred if attempt == 1 else not preferred
            wire = desired if one_means_on else not desired
            service.progress(f"setting {action} {'ON' if desired else 'OFF'} (verification {attempt}/2)")
            try:
                await self._write(command, b"\x01" if wire else b"\x00")
            except TimeoutError:
                if attempt == 2:
                    raise RuntimeError(f"{self.name} did not accept the {action} setting: Bluetooth write timed out") from None
                continue
            service.progress(f"verifying {action} MOS state")
            await asyncio.sleep(1)
            await self._refresh_unlocked(radio_owned=True, raise_on_error=True)
            last_state = service.get_battery(self.name)
            if last_state.get(target_field) == desired and last_state.get(other_field) != original_other:
                last_state = await self._restore_other_mos(other_action, other_field, original_other, last_state)
            if last_state.get(target_field) == desired and last_state.get(other_field) == original_other:
                service.remember_mos_encoding(self.name, action, one_means_on)
                service.progress("verification complete")
                await asyncio.sleep(0)
                return {"changed": True, "battery": self.name, "action": action, "enabled": desired, "verified": True}
            if attempt == 1:
                service.progress("requested MOS state not confirmed; retrying")
        raise RuntimeError(
            f"{self.name} did not confirm {action} {'ON' if desired else 'OFF'} after 2 attempts "
            f"(reported charge={'ON' if last_state.get('charge_mosfet_on') else 'OFF'}, "
            f"discharge={'ON' if last_state.get('discharge_mosfet_on') else 'OFF'}; "
            f"target={last_state.get(target_field)}, preserved={last_state.get(other_field)})"
        )

    async def _restore_other_mos(self, other_action: str, other_field: str, original_other: bool, last_state: dict) -> dict:
        service = self.service
        service.progress(f"restoring unchanged {other_action} MOS state")
        command = {"charge": 0xDA, "discharge": 0xD9}[other_action]
        learned = service.mos_encoding(self.name, other_action)
        for attempt in (1, 2):
            preferred = True if learned is None else learned
            one_means_on = preferred if attempt == 1 else not preferred
            wire = original_other if one_means_on else not original_other
            await self._write(command, b"\x01" if wire else b"\x00")
            await asyncio.sleep(1)
            await self._refresh_unlocked(radio_owned=True, raise_on_error=True)
            last_state = service.get_battery(self.name)
            if last_state.get(other_field) == original_other:
                service.remember_mos_encoding(self.name, other_action, one_means_on)
                break
        return last_state

    # ---- the worker loop -------------------------------------------------------------------------------------
    async def _run(self, epoch: int = 0) -> None:
        service = self.service
        self.loop = asyncio.get_running_loop()
        self.operation_lock = asyncio.Lock()
        self.refresh_event.bind()
        try:
            await asyncio.sleep(self.index * STARTUP_STAGGER)
            while self.supervisor.current(epoch):
                self.supervisor.heartbeat()
                # A user control owns the radio until its result has reached the HTTP thread; starting a background
                # refresh meanwhile used to create a circular wait right after verification.
                if service.control_busy():
                    await asyncio.sleep(0.1)
                    continue
                requested = self.refresh_event.is_set()
                self.refresh_event.clear()
                generation = service.refresh_generation
                manual = generation > self.completed_generation
                settings = service.settings_getter()
                if not self.connected():
                    await self._connect("bms_manual_connect" if manual else "bms")
                    if self.connected():
                        await self._refresh(generation, manual=manual)
                    else:
                        self.completed_generation = max(self.completed_generation, generation)
                else:
                    interval = max(2, int(settings["bms_refresh_interval"]))
                    if requested or time.monotonic() - self.last_refresh >= interval:
                        await self._refresh(generation, manual=manual)
                retry = max(1, int(settings["bms_connection_retry_seconds"]))
                pause = 0.25 if self.connected() else min(BMS_MAX_BACKOFF, retry * 2 ** min(max(0, self.connection_failures - 1), 6))
                await self.refresh_event.wait(pause)
        finally:
            if (
                self.supervisor.current(epoch) or self.stop_event.is_set()
            ):  # an abandoned (replaced) worker must not close the new one's link
                await self._disconnect()
                self.loop = None


class DalyBmsService:
    """Coordinator for three failure-isolated persistent DALY workers."""

    def __init__(self, paths: Paths = PATHS, coordinator=None):
        self.coordinator = coordinator or bluetooth_coordinator
        self.lock = threading.RLock()
        self.batteries = {name: {"state": "not_read", "battery": name} for name in DEVICE_NAMES}
        self.settings_getter = lambda: {"bms_refresh_interval": 30, "bms_connection_retry_seconds": 5}
        self._workers: dict[str, BatteryWorker] = {}
        self._connection_timing_lock = threading.Lock()
        self._last_connection_attempt = 0.0
        self.refresh_generation = 0
        self.control_status = {"busy": False, "phase": "idle", "message": "", "current": 0, "total": 0}
        self.backup_dir = paths.backups
        self._mos_encoding_path = Path(paths.mos_encoding_file)
        try:
            self._mos_encodings = json.loads(self._mos_encoding_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            self._mos_encodings = {}

    # ---- state shared with the workers -----------------------------------------------------------------------
    def set_state(self, name: str, state: str, error=None, **values) -> None:
        with self.lock:
            self.batteries[name] = {**self.batteries.get(name, {}), **values, "battery": name, "state": state, "error": error}

    def set_snapshot(self, name: str, value: dict) -> None:
        with self.lock:
            self.batteries[name] = dict(value)

    def get_battery(self, name: str) -> dict:
        with self.lock:
            return dict(self.batteries.get(name, {}))

    def mos_encoding(self, name: str, action: str):
        with self.lock:
            value = self._mos_encodings.get(name, {}).get(action)
            return value if value in (True, False) else None

    def remember_mos_encoding(self, name: str, action: str, one_means_on: bool) -> None:
        with self.lock:
            self._mos_encodings.setdefault(name, {})[action] = bool(one_means_on)
            value = json.dumps(self._mos_encodings, indent=2, sort_keys=True) + "\n"
        self._mos_encoding_path.parent.mkdir(exist_ok=True)
        temporary = self._mos_encoding_path.with_suffix(".tmp")
        temporary.write_text(value, encoding="utf-8")
        temporary.replace(self._mos_encoding_path)

    async def wait_connection_pause(self) -> None:
        """At least CONNECTION_PAUSE between two connection attempts of any battery (Windows needs the breather)."""
        with self._connection_timing_lock:
            delay = max(0.0, CONNECTION_PAUSE - (time.monotonic() - self._last_connection_attempt))
        if delay:
            await asyncio.sleep(delay)

    def record_connection_attempt(self) -> None:
        with self._connection_timing_lock:
            self._last_connection_attempt = time.monotonic()

    # ---- lifecycle -------------------------------------------------------------------------------------------
    def start(self, settings_getter) -> None:
        if importlib.util.find_spec("bleak") is None:
            for name in DEVICE_NAMES:
                self.set_state(name, "error", "Windows Bluetooth component 'bleak' is unavailable")
            return
        self.settings_getter = settings_getter
        with self.lock:
            if self._workers:
                return
            self._workers = {name: BatteryWorker(self, name, index) for index, name in enumerate(DEVICE_NAMES)}
            workers = list(self._workers.values())
        for worker in workers:
            worker.start()

    def stop(self) -> None:
        with self.lock:
            workers = list(self._workers.values())
            self._workers = {}
        for worker in workers:
            worker.stop()

    def snapshot(self) -> dict:
        with self.lock:
            workers = dict(self._workers)
            batteries = {name: dict(value) for name, value in self.batteries.items()}
            control_status = dict(self.control_status)
        pending = [name for name, worker in workers.items() if worker.completed_generation < self.refresh_generation]
        settings = self.settings_getter()
        return {
            "busy": bool(workers) and bool(pending),
            "refresh_started_at": None,
            "refresh_status": {
                "generation": self.refresh_generation,
                "completed": len(workers) - len(pending),
                "total": len(workers),
                "pending": pending,
            },
            "control_status": control_status,
            "queue": self.coordinator.snapshot(),
            "batteries": batteries,
            "read_only": False,
            "controls_available": True,
            "ble_available": importlib.util.find_spec("bleak") is not None,
            "persistent_connections": True,
            "connected_count": sum(1 for worker in workers.values() if worker.connected()),
            "refresh_interval_seconds": int(settings["bms_refresh_interval"]),
            "connection_retry_interval_seconds": int(settings["bms_connection_retry_seconds"]),
        }

    def refresh_all(self) -> dict:
        self.refresh_generation += 1
        for worker in list(self._workers.values()):
            worker.refresh_event.set()
        return {"started": True, "parallel": True}

    def refresh_one(self, name: str) -> dict:
        if name not in DEVICE_NAMES:
            raise ValueError("Unknown battery")
        worker = self._workers.get(name)
        if not worker:
            raise RuntimeError(f"{name} worker is unavailable")
        worker.refresh_event.set()
        return {"started": True, "battery": name}

    # ---- controls --------------------------------------------------------------------------------------------
    def _backup(self, names) -> None:
        """Write the battery's last status to backups/ before changing anything."""
        self.backup_dir.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        for name in names:
            path = self.backup_dir / f'{name.lower().replace(" ", "_")}_backup_{stamp}.json'
            path.write_text(json.dumps(self.get_battery(name), indent=2) + "\n", encoding="utf-8")

    def set_control_status(self, **updates) -> None:
        with self.lock:
            self.control_status = {**self.control_status, **updates}

    def progress(self, detail: str) -> None:
        with self.lock:
            current = int(self.control_status.get("current") or 1)
            total = int(self.control_status.get("total") or 1)
            if total > 1:
                label = f"Battery {current}/{total}"
            else:
                label = next(
                    (name.title() for name in DEVICE_NAMES if name.lower() in str(self.control_status.get("message", "")).lower()),
                    "Battery",
                )
            self.control_status = {**self.control_status, "phase": "updating", "message": f"{label}: {detail}"}

    def control_busy(self) -> bool:
        with self.lock:
            return bool(self.control_status.get("busy"))

    def _run_control(self, name: str, action: str, enabled=None):
        worker = self._workers.get(name)
        latest = self.get_battery(name)
        if not worker or not worker.loop or not worker.connected() or latest.get("state") not in {"connected", "reading"}:
            raise RuntimeError(f"{name} must be connected and refreshed before changing it")
        future = asyncio.run_coroutine_threadsafe(worker.control(action, enabled), worker.loop)
        # Every BLE write/read already has its own short timeout and retry; this outer watchdog is only a deadlock guard
        # and must accommodate all nine verification requests including their retry allowance.
        try:
            return future.result(timeout=CONTROL_WATCHDOG_SECONDS)
        except concurrent.futures.TimeoutError as exc:
            with self.lock:
                last_phase = self.control_status.get("message") or "unknown phase"
            future.cancel()
            try:
                future.result(timeout=3)
            except BaseException:
                pass
            disconnect = asyncio.run_coroutine_threadsafe(worker._disconnect(), worker.loop)
            try:
                disconnect.result(timeout=5)
            except BaseException:
                pass
            raise RuntimeError(
                f"{name} control watchdog timed out after {CONTROL_WATCHDOG_SECONDS} seconds during: {last_phase}; the Bluetooth operation was cancelled"
            ) from exc

    def control(self, name: str, action: str, enabled=None):
        if name not in DEVICE_NAMES:
            raise ValueError("Unknown battery")
        if action not in CONTROL_ACTIONS:
            raise ValueError("Unknown BMS action")
        self._backup([name])
        self.set_control_status(busy=True, phase="waiting", message="Waiting for Bluetooth queue to become available", current=0, total=1)
        owns_radio = 0
        try:
            owns_radio = self.coordinator.acquire("bms_control", timeout=35)
            if not owns_radio:
                raise RuntimeError("Bluetooth queue did not become available in time")
            self.set_control_status(phase="updating", message=f"Updating {name} (1/1)", current=1)
            return self._run_control(name, action, enabled)
        finally:
            if owns_radio:
                self.coordinator.release("bms_control", owns_radio)
            self.set_control_status(busy=False, phase="idle", message="", current=0, total=0)

    def control_all(self, action: str, percent=None):
        """Apply `action` to every battery that needs it, one after the other; stops at the first failure and says what was done."""
        if action not in ALL_ACTIONS:
            raise ValueError("Unknown BMS action")
        targets = list(DEVICE_NAMES)
        if action.startswith(("charge_", "discharge_")):
            kind = action.split("_")[0]
            desired = action.endswith("_on")
            targets = [name for name in DEVICE_NAMES if self.get_battery(name).get(f"{kind}_mosfet_on") is not desired]
        if not targets:
            return {"changed": False, "action": action, "results": {}, "refresh_complete": True, "targets": []}
        for name in targets:
            worker = self._workers.get(name)
            if not worker or not worker.connected() or self.get_battery(name).get("state") not in {"connected", "reading"}:
                raise RuntimeError("All three batteries must be connected before changing all values")
        self._backup(targets)
        results: dict = {}
        owns_radio = 0
        total = len(targets)
        self.set_control_status(
            busy=True, phase="waiting", message="Waiting for Bluetooth queue to become available", current=0, total=total
        )
        try:
            owns_radio = self.coordinator.acquire("bms_control", timeout=35)
            if not owns_radio:
                raise RuntimeError("Bluetooth queue did not become available in time")
            completed = []
            for index, name in enumerate(targets, 1):
                try:
                    self.set_control_status(phase="updating", message=f"Updating Battery {index}/{total}", current=index)
                    if action.startswith(("charge_", "discharge_")):
                        single, enabled = action.split("_")[0], action.endswith("_on")
                    elif action == "set_soc_value":
                        single, enabled = action, percent
                    else:
                        single, enabled = action, None
                    results[name] = self._run_control(name, single, enabled)
                    completed.append(name)
                except Exception as exc:
                    remaining = list(targets[index:])
                    done = ", ".join(completed) if completed else "none"
                    untouched = ", ".join(remaining) if remaining else "none"
                    raise RuntimeError(
                        f"Set all stopped at Battery {index}/{total} ({name}): {str(exc).strip() or type(exc).__name__}. Completed before failure: {done}. Not changed: {untouched}"
                    ) from exc
            return {"changed": True, "action": action, "results": results, "refresh_complete": True, "targets": targets}
        finally:
            if owns_radio:
                self.coordinator.release("bms_control", owns_radio)
            self.set_control_status(busy=False, phase="idle", message="", current=0, total=0)
