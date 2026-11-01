"""Non-hardware self-test for DalyBalancerService using a simulated Bluetooth layer (fake bleak).

Covers: complete-status publishing (no half-read balancers in the history), one retry for unanswered commands,
static device information read once, GATT time-outs, per-balancer exponential backoff, the crash-proof supervisor,
the stall watchdog (rescan, worker rebuild, wedged flag and recovery), the manual/full refresh semantics, a CancelledError
out of a Bluetooth call and a dead or hung worker (monitor thread).
"""

import asyncio
import time

import bleak

from mastervolt.bluetooth import balancers as bal
from mastervolt.bluetooth.coordinator import BluetoothCoordinator
from mastervolt.bluetooth.events import ble_log
from tests.ble_fakes import BEHAVIOUR, COUNT, PRESENT, RSSI, FakeClient, FakeScanner, wait

NAMES = bal.DEVICE_NAMES


def fast(**overrides):
    values = dict(
        INITIAL_DELAY=0,
        GATT_TIMEOUT=0.25,
        CONNECT_TIMEOUT=0.4,
        NOTIFY_TIMEOUT=0.4,
        DISCONNECT_TIMEOUT=0.3,
        COMMAND_SPACING=0.001,
        FRAME_WAIT=0.25,
        SETTLE_SECONDS=0.01,
        INCOMPLETE_RETRY_SECONDS=0.05,
        MAX_BACKOFF_SECONDS=0.4,
        WATCHDOG_SECONDS=600.0,
        CRASH_BACKOFF_BASE=0.02,
        HANG_SECONDS=300.0,
        MONITOR_SECONDS=0.05,
    )
    values.update(overrides)
    for key, value in values.items():
        setattr(bal, key, value)


def make(interval=0.3, retry=0.05, ready=True, **overrides):
    COUNT.clear()
    BEHAVIOUR.clear()
    PRESENT.clear()
    PRESENT.update(NAMES)
    ble_log.clear()
    for name in NAMES:
        BEHAVIOUR[name] = {}
    fast(**overrides)
    coordinator = BluetoothCoordinator()
    if ready:
        for battery in ("BATTERY 1", "BATTERY 2", "BATTERY 3"):
            coordinator.mark_bms(battery, True)
            coordinator.mark_bms_refreshed(battery)
    service = bal.DalyBalancerService(coordinator=coordinator)
    service.ble_available = True
    service.settings_getter = lambda: {"balancer_refresh_interval": interval, "balancer_connection_retry_seconds": retry}
    published = []
    original = service._update_status

    def recording(name):
        published.append((name, set(service.decoded[name])))
        original(name)

    service._update_status = recording
    service.published = published
    return service, coordinator


def events(device, kind):
    return ble_log.snapshot(300)["counters"].get(device, {}).get("events", {}).get(kind, 0)


def main():
    bleak.BleakClient, bleak.BleakScanner = FakeClient, FakeScanner
    try:
        # ---- 1. normal operation: complete statuses only, static data read once
        s, _ = make(interval=0.15)
        RSSI.update({"DL-BAL1": -85, "DL-BAL2": -62})
        s.start()
        assert wait(lambda: all(s.devices[n]["captured_at"] for n in NAMES) and len(s.published) >= 6), s.published
        s.stop()
        assert all(commands == set(bal.COMMANDS) for _, commands in s.published), "a status was published before every command was answered"
        for n in NAMES:
            assert (
                COUNT[(n, "static_read")] == 2
            ), f"{n}: device information must be read once, not every cycle ({COUNT[(n, 'static_read')]})"
            assert s.devices[n]["status"]["valid_frame_count"] == 10 and len(s.devices[n]["status"]["cells_mv"]) == 4
            assert COUNT[(n, "connect")] >= 2
        assert COUNT[("scanner", "scan")] == 1, "known balancers must not be scanned for again"
        snap = s.snapshot()
        assert all(snap["devices"][n]["last_success_age_seconds"] is not None and not snap["devices"][n]["stale"] for n in NAMES)
        timings = ble_log.snapshot()["counters"]["DL-BAL1"]["timings"]
        for kind in ("connect", "notify", "read", "disconnect", "radio_hold", "radio_wait"):
            assert (
                timings[kind]["ok"] >= 2
                and timings[kind]["avg_ok_seconds"] is not None
                and timings[kind]["p95_ok_seconds"] >= timings[kind]["p50_ok_seconds"]
            ), (kind, timings.get(kind))
        assert (
            timings["radio_hold"]["avg_ok_seconds"] >= timings["connect"]["avg_ok_seconds"]
        ), "the radio is held at least as long as the connect takes"
        assert ble_log.snapshot()["counters"]["balancers"]["timings"]["scan"]["count"] == 1
        signal = {n: ble_log.snapshot()["counters"][n]["signal"] for n in NAMES}
        assert (signal["DL-BAL1"]["last_dbm"], signal["DL-BAL2"]["last_dbm"], signal["DL-BAL3"]["last_dbm"]) == (-85, -62, -60), signal
        scan = [e["detail"] for e in ble_log.snapshot(300)["events"] if e["kind"] == "scan"][0]
        assert "DL-BAL1 (-85 dBm)" in scan and "DL-BAL3 (-60 dBm)" in scan, scan
        RSSI.clear()
        print(
            "Complete statuses only, device information read once, one scan for three balancers, timings and signal strength recorded: OK"
        )

        # ---- 2. an unanswered command is asked again within the same connection
        s, _ = make(interval=5)
        BEHAVIOUR["DL-BAL1"]["drop_once"] = {0x95}
        s.start()
        assert wait(lambda: s.devices["DL-BAL1"]["captured_at"])
        s.stop()
        assert events("DL-BAL1", "read_retry") == 1 and s.devices["DL-BAL1"]["status"]["valid_frame_count"] == 10
        assert all(commands == set(bal.COMMANDS) for _, commands in s.published)
        print("Retry of unanswered commands (0x95) completes the read: OK")

        # ---- 3. commands that stay unanswered publish nothing (no half-read balancer in the history)
        s, _ = make(interval=5)
        BEHAVIOUR["DL-BAL2"]["drop_always"] = {0x96}
        s.start()
        assert wait(
            lambda: s.devices["DL-BAL1"]["captured_at"]
            and s.devices["DL-BAL3"]["captured_at"]
            and "Incomplete" in (s.devices["DL-BAL2"]["error"] or "")
        )
        s.stop()
        assert (
            s.devices["DL-BAL2"]["captured_at"] is None and s.devices["DL-BAL2"]["status"] == {}
        ), "an incomplete status must not be published"
        assert "0x96" in s.devices["DL-BAL2"]["error"] and s.connection_failures["DL-BAL2"] == 0
        print("Persistently unanswered command: nothing published, clear error, others unaffected: OK")

        # ---- 4. a hung GATT write times out, releases the radio and does not stop the others
        s, coordinator = make(interval=0.2)
        BEHAVIOUR["DL-BAL3"]["hang_write"] = True
        s.start()
        assert wait(lambda: s.connection_failures["DL-BAL3"] >= 1 and s.devices["DL-BAL1"]["captured_at"])
        first = COUNT[("DL-BAL1", "connect")]
        assert wait(lambda: COUNT[("DL-BAL1", "connect")] > first + 1), "healthy balancers stopped after another one hung"
        assert coordinator.snapshot()["active"] in (None, "balancer")
        s.stop()
        assert events("DL-BAL3", "read_failed") >= 1
        hold = ble_log.snapshot()["counters"]["DL-BAL3"]["timings"]["radio_hold"]
        assert hold["failed"] >= 1 and hold["max_failed_seconds"] >= 0.2, hold  # the hung write cost about GATT_TIMEOUT of radio time
        assert any(
            "s on the radio)" in e["detail"]
            for e in ble_log.snapshot(300)["events"]
            if e["device"] == "DL-BAL3" and e["kind"] == "read_failed"
        )
        print("Hung GATT write: time-out, radio released, other balancers keep reading: OK")

        # ---- 5. exponential backoff for a failing balancer, healthy ones keep their own interval
        s, _ = make(interval=0.02, retry=0.05)
        BEHAVIOUR["DL-BAL2"]["fail_connect"] = 99
        delays, healthy = [], []
        original_schedule = s._schedule

        def spy(name, ok, incomplete=False, deferred=False):
            original_schedule(name, ok, incomplete=incomplete, deferred=deferred)
            (delays if name == "DL-BAL2" else healthy).append(round(s.next_due[name] - time.monotonic(), 2))

        s._schedule = spy
        s.start()
        assert wait(lambda: len(delays) >= 5, 10)
        s.stop()
        assert delays[:4] == [0.05, 0.1, 0.2, 0.4] and max(delays) <= bal.MAX_BACKOFF_SECONDS + 0.01, delays
        assert healthy and all(delay == 0.02 for delay in healthy), "a healthy balancer must keep its own refresh interval"
        print(f"Exponential backoff for a failing balancer {delays[:5]} (capped), healthy ones keep their interval: OK")

        # ---- 6. the supervisor survives a crash inside the Bluetooth loop
        s, _ = make(interval=0.2)
        state = {"crashed": False}
        original_watchdog = s._watchdog

        def crashing():
            if not state["crashed"]:
                state["crashed"] = True
                raise RuntimeError("boom (simulated crash)")
            original_watchdog()

        s._watchdog = crashing
        s.start()
        assert wait(
            lambda: state["crashed"] and all(s.devices[n]["captured_at"] for n in NAMES)
        ), "balancers were not polled again after a crash"
        s.stop()
        assert events("balancers", "worker_crash") == 1
        print("Crash inside the worker: supervisor rebuilds it and polling resumes: OK")

        # ---- 7. stall watchdog: rescan, worker rebuild, wedged flag, recovery
        s, _ = make(interval=0.1, retry=0.02, WATCHDOG_SECONDS=1.0)
        for n in NAMES:
            BEHAVIOUR[n]["fail_connect"] = 10**6
        s.start()
        assert wait(lambda: events("balancers", "watchdog_rescan") >= 1, 5), "no forced rescan"
        assert wait(lambda: s.snapshot()["wedged"] and s.snapshot()["worker_restarts"] >= 3, 15), s.snapshot()["worker_restarts"]
        for n in NAMES:
            BEHAVIOUR[n]["fail_connect"] = 0
        assert wait(
            lambda: all(s.devices[n]["captured_at"] for n in NAMES) and not s.snapshot()["wedged"], 15
        ), "no recovery after the fault cleared"
        assert s.snapshot()["watchdog_level"] == 0
        s.stop()
        assert events("balancers", "worker_restart") >= 3
        print("Stall watchdog: forced rescan, worker rebuilt 3x, 'wedged' flagged, recovers when the fault clears: OK")

        # ---- 8. waiting for the BMS links is not a balancer stall
        s, coordinator = make(interval=0.1, ready=False, WATCHDOG_SECONDS=1.0)
        s.start()
        time.sleep(2.5)
        assert s.snapshot()["worker_restarts"] == 0 and all(s.devices[n]["state"] == "waiting" for n in NAMES)
        for battery in ("BATTERY 1", "BATTERY 2", "BATTERY 3"):
            coordinator.mark_bms(battery, True)
            coordinator.mark_bms_refreshed(battery)
        assert wait(lambda: all(s.devices[n]["captured_at"] for n in NAMES))
        s.stop()
        assert s.snapshot()["worker_restarts"] == 0
        print("Waiting for the BMS links does not trigger the watchdog: OK")

        # ---- 9. staleness is reported
        s, _ = make(interval=5)
        s.start()
        assert wait(lambda: all(s.devices[n]["captured_at"] for n in NAMES))
        s.stop()
        s.last_success["DL-BAL1"] = time.monotonic() - 1000
        snap = s.snapshot()
        assert snap["devices"]["DL-BAL1"]["stale"] and not snap["devices"]["DL-BAL2"]["stale"]
        print("Stale data flag in the snapshot: OK")

        # ---- 10. manual and full refresh semantics
        s, _ = make(interval=60)
        s.start()
        assert wait(lambda: all(s.devices[n]["captured_at"] for n in NAMES))
        time.sleep(0.3)
        before = {n: COUNT[(n, "connect")] for n in NAMES}
        s.refresh_one("DL-BAL2")
        assert wait(lambda: COUNT[("DL-BAL2", "connect")] == before["DL-BAL2"] + 1)
        time.sleep(0.4)
        assert (
            COUNT[("DL-BAL1", "connect")] == before["DL-BAL1"] and COUNT[("DL-BAL3", "connect")] == before["DL-BAL3"]
        ), "a manual refresh must read only that balancer"
        out = s.refresh_all()
        assert wait(lambda: s.snapshot()["completed_generation"] == out["generation"] and not s.snapshot()["busy"])
        assert all(COUNT[(n, "connect")] >= before[n] + 1 for n in NAMES)
        s.stop()
        print("Manual refresh reads one balancer, refresh all reads all three and completes: OK")

        # ---- 11. a CancelledError out of a Windows Bluetooth call must not end the worker (it once did, silently, for 20+ minutes)
        s, _ = make(interval=0.2)
        BEHAVIOUR["DL-BAL1"]["cancel_connect"] = 2
        s.start()
        assert wait(lambda: all(s.devices[n]["captured_at"] for n in NAMES), 10), "the balancers stopped after a CancelledError"
        out = s.refresh_all()
        assert wait(
            lambda: s.snapshot()["completed_generation"] == out["generation"] and not s.snapshot()["busy"]
        ), "a pending Refresh BAL never completed"
        assert s.snapshot()["worker_alive"]
        s.stop()
        print("CancelledError from connect(): treated as a failed connect, balancers keep polling, Refresh BAL completes: OK")

        # ---- 12. the supervisor itself survives it too (cancel arriving outside the per-balancer handler)
        s, _ = make(interval=0.2)
        state = {"n": 0}
        original_watchdog = s._watchdog

        def cancelling():
            state["n"] += 1
            if state["n"] == 1:
                raise asyncio.CancelledError()
            original_watchdog()

        s._watchdog = cancelling
        s.start()
        assert wait(lambda: all(s.devices[n]["captured_at"] for n in NAMES), 10), "worker did not restart after a CancelledError"
        s.stop()
        assert events("balancers", "worker_crash") == 1
        print("CancelledError escaping the loop: supervisor restarts the worker: OK")

        # ---- 13. monitor: a dead worker thread is replaced, a hung event loop is abandoned
        s, _ = make(interval=0.2)
        real_main = s.supervisor._thread_main
        calls = {"n": 0}

        def dying(epoch=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise SystemExit()  # something that is neither Exception nor CancelledError ends the thread
            real_main(epoch)

        s.supervisor._thread_main = dying
        s.start()
        assert wait(lambda: events("balancers", "worker_dead") >= 1, 10), "a dead worker thread was not noticed"
        assert wait(
            lambda: s.snapshot()["worker_alive"] and all(s.devices[n]["captured_at"] for n in NAMES), 10
        ), "no new worker after the thread died"
        s.stop()
        print("Monitor: a dead worker thread is replaced and polling resumes: OK")
        s, _ = make(interval=0.2, HANG_SECONDS=0.6)
        hung = {"done": False}
        original_watchdog = s._watchdog

        def blocking():
            if not hung["done"]:
                hung["done"] = True
                time.sleep(2.5)  # a synchronous call that blocks the whole event loop
            original_watchdog()

        s._watchdog = blocking
        s.start()
        old = s.thread
        assert wait(lambda: events("balancers", "worker_hung") >= 1, 10), "a hung event loop was not noticed"
        assert wait(lambda: s.thread is not old and all(s.devices[n]["captured_at"] for n in NAMES), 10), "no new worker after the hang"
        assert s.snapshot()["worker_restarts"] >= 1
        s.stop()
        print("Monitor: a hung event loop is abandoned and replaced by a fresh worker: OK")
    finally:
        pass
    print("All balancer service checks: OK")


if __name__ == "__main__":
    main()
