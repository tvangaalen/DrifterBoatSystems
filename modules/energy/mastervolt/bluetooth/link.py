"""Building blocks shared by the BMS and balancer Bluetooth workers.

* `Wakeup`      - an event that threads can set and an asyncio task can wait for, with a timeout
* `Supervisor`  - runs a worker's coroutine in its own thread/event loop and keeps it alive: it restarts the worker after a
                  crash, and a monitor thread replaces a worker thread that has died or whose event loop hangs
* client helpers - creating a Bleak client, opening the link with hard deadlines, disconnecting safely
* `scan_for`    - find the wanted devices in one scan that ends as soon as they have all been seen

Every Windows Bluetooth call gets a hard deadline (`asyncio.wait_for`): a hung WinRT call would otherwise freeze a whole
worker loop (CLAUDE.md). A client that connected but failed later is always disconnected.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import time
from collections.abc import Awaitable, Callable

from .events import ble_log

USE_CACHED_SERVICES = True  # Windows: skip GATT service discovery on every connect (the DALY layout never changes)


class WorkerRestart(RuntimeError):
    """Raised inside a worker to have the supervisor rebuild its event loop and every Bluetooth object in it."""


class Wakeup:
    """`set()` from any thread; `await wait(timeout)` in the worker's loop. Replaces fixed 250 ms polling sleeps."""

    def __init__(self):
        self._flag = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._async: asyncio.Event | None = None

    def bind(self) -> None:
        """Attach to the running loop (call at the start of the worker's coroutine)."""
        self._loop = asyncio.get_running_loop()
        self._async = asyncio.Event()
        if self._flag.is_set():
            self._async.set()

    def set(self) -> None:
        self._flag.set()
        loop, event = self._loop, self._async
        if loop and event:
            try:
                loop.call_soon_threadsafe(event.set)
            except RuntimeError:  # the loop is closed: the flag is all that matters now
                pass

    def clear(self) -> None:
        self._flag.clear()
        if self._async:
            self._async.clear()

    def is_set(self) -> bool:
        return self._flag.is_set()

    async def wait(self, timeout: float) -> bool:
        """Sleep until set (True) or `timeout` seconds have passed (False)."""
        deadline = self._loop.time() + max(0.0, timeout)
        while True:
            if self._flag.is_set():
                return True
            self._async.clear()
            if self._flag.is_set():
                return True
            remaining = deadline - self._loop.time()
            if remaining <= 0:
                return False
            try:
                await asyncio.wait_for(self._async.wait(), remaining)
            except TimeoutError:
                return self._flag.is_set()  # a wake-up whose flag was cleared again in the meantime is not a wake-up: wait on


class Supervisor:
    """Keeps `run(epoch)` (a coroutine function) alive in a thread of its own.

    * An exception - including the `CancelledError` Windows Bluetooth calls sometimes raise, which is not an `Exception` and
      once ended a worker thread for good - restarts the worker after an exponential pause (`on_crash` is told first).
    * `WorkerRestart` restarts it after one second (`on_restart` is told first).
    * A monitor thread notices a worker thread that died, or an event loop that made no `heartbeat()` for `hang_seconds`,
      and starts a fresh worker. The old one is abandoned; it stops by itself if it ever wakes up (its epoch is stale).
    """

    def __init__(
        self,
        run: Callable[[int], Awaitable[None]],
        stop_event: threading.Event,
        *,
        name: str,
        device: str,
        hang_seconds: float = 300.0,
        monitor_seconds: float = 10.0,
        crash_backoff: float = 5.0,
        on_crash: Callable[[BaseException], None] | None = None,
        on_restart: Callable[[BaseException], None] | None = None,
        on_replaced: Callable[[str], None] | None = None,
    ):
        self.run, self.stop_event, self.name, self.device = run, stop_event, name, device
        self.hang_seconds, self.monitor_seconds, self.crash_backoff = hang_seconds, monitor_seconds, crash_backoff
        self.on_crash, self.on_restart, self.on_replaced = on_crash, on_restart, on_replaced
        self.epoch = 0
        self.thread: threading.Thread | None = None
        self.monitor: threading.Thread | None = None
        self.last_heartbeat = time.monotonic()

    # ---- control ----------------------------------------------------------------------------------------------
    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self._spawn()
        if not (self.monitor and self.monitor.is_alive()):
            self.monitor = threading.Thread(target=self._monitor_main, daemon=True, name=f"{self.name}-monitor")
            self.monitor.start()

    def join(self, timeout: float) -> None:
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=timeout)

    @property
    def alive(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def heartbeat(self) -> None:
        self.last_heartbeat = time.monotonic()

    def current(self, epoch) -> bool:
        """False once the service is stopping or this worker has been replaced."""
        return not self.stop_event.is_set() and (epoch is None or epoch == self.epoch)

    # ---- internals --------------------------------------------------------------------------------------------
    def _spawn(self) -> None:
        self.epoch += 1
        self.heartbeat()
        self.thread = threading.Thread(target=self._thread_main, args=(self.epoch,), daemon=True, name=self.name)
        self.thread.start()

    def _thread_main(self, epoch: int) -> None:
        crashes = 0
        while self.current(epoch):
            try:
                asyncio.run(self.run(epoch))
                crashes = 0
            except WorkerRestart as exc:
                if self.on_restart:
                    self.on_restart(exc)
            except (Exception, asyncio.CancelledError) as exc:
                crashes += 1
                if self.on_crash:
                    self.on_crash(exc)
                ble_log.log(self.device, "worker_crash", repr(exc), failure=True)
                self.stop_event.wait(min(60.0, self.crash_backoff * 2 ** min(crashes, 4)))
                continue
            self.stop_event.wait(1.0)

    def _monitor_main(self) -> None:
        while not self.stop_event.wait(self.monitor_seconds):
            dead = not self.alive
            stalled = time.monotonic() - self.last_heartbeat
            if not dead and stalled < self.hang_seconds:
                continue
            reason = "worker_dead" if dead else "worker_hung"
            if self.on_replaced:
                self.on_replaced(reason)
            ble_log.log(
                self.device,
                reason,
                "the worker thread had stopped" if dead else f"the worker made no progress for {stalled:.0f} s",
                failure=True,
            )
            self._spawn()


# ---- Bleak helpers -------------------------------------------------------------------------------------------------
def make_client(device, *, timeout: float, disconnected_callback):
    """A BleakClient for `device`; on Windows with cached GATT services where the installed bleak supports it."""
    from bleak import BleakClient

    options = {"timeout": timeout, "disconnected_callback": disconnected_callback}
    if USE_CACHED_SERVICES and sys.platform == "win32":
        options["winrt"] = {"use_cached_services": True}
    try:
        return BleakClient(device, **options)
    except TypeError:
        options.pop("winrt", None)  # a bleak without WinRT client arguments
        return BleakClient(device, **options)


async def open_link(client, name: str, notify_uuid: str, on_data, *, connect_timeout: float, notify_timeout: float) -> None:
    """Connect and start notifications, each under its own hard deadline and timed in the Bluetooth log."""
    with ble_log.timed(name, "connect"):
        await asyncio.wait_for(client.connect(), timeout=connect_timeout)
    with ble_log.timed(name, "notify"):
        await asyncio.wait_for(client.start_notify(notify_uuid, on_data), timeout=notify_timeout)


async def drop_client(client, name: str, *, timeout: float) -> None:
    """Disconnect with a deadline. A client whose disconnect hangs is logged (a possible leaked Windows handle) and abandoned."""
    if not client:
        return
    try:
        with ble_log.timed(name, "disconnect"):
            await asyncio.wait_for(client.disconnect(), timeout=timeout)
    except TimeoutError:
        ble_log.log(
            name,
            "disconnect_timeout",
            f"disconnect did not finish within {timeout:g} s (possible leaked Windows Bluetooth handle)",
            failure=True,
        )
    except BaseException:
        pass


async def scan_for(wanted: list[str], known: tuple[str, ...], timeout: float):
    """Scan until every name in `wanted` has been seen (or `timeout`); returns ({name: device}, {name: rssi}).

    The signal strength of every DALY device seen (also ones not looked for) is recorded in the Bluetooth log. Ending the
    scan as soon as the wanted devices are found - instead of always scanning for the whole timeout - keeps the radio free
    for the battery links.
    """
    from bleak import BleakScanner

    found: dict[str, object] = {}
    signal: dict[str, int] = {}
    done = asyncio.Event()

    def on_advertisement(device, advertisement):
        visible = getattr(advertisement, "local_name", None) or getattr(device, "name", None) or ""
        for name in known:
            if name.casefold() in visible.casefold():
                rssi = getattr(advertisement, "rssi", None)
                if isinstance(rssi, int):
                    ble_log.rssi(name, rssi)
                    signal[name] = rssi
                if name in wanted:
                    found.setdefault(name, device)
        if all(name in found for name in wanted):
            done.set()

    scanner = BleakScanner(detection_callback=on_advertisement)
    async with scanner:
        try:
            await asyncio.wait_for(done.wait(), timeout=timeout)
        except TimeoutError:
            pass
        # Parity with a plain timed scan: whatever the scanner has collected by now counts, whether or not the callback reported it.
        for device, advertisement in getattr(scanner, "discovered_devices_and_advertisement_data", {}).values():
            on_advertisement(device, advertisement)
    return found, signal
