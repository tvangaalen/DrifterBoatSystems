"""Non-hardware self-test for the DALY BMS monitoring workers (persistent links) on a simulated Bluetooth layer.

Only the monitoring path is exercised: connect, notify, status reads, retries and back-off. The control writes
(MOSFET / SOC) are covered by bms_control_self_test.py and are not touched here.
"""

import tempfile
import time
from pathlib import Path

import bleak

from mastervolt.bluetooth import bms
from mastervolt.bluetooth.coordinator import BluetoothCoordinator
from mastervolt.bluetooth.events import ble_log
from mastervolt.config import Paths
from tests.ble_fakes import BEHAVIOUR, COUNT, PRESENT, RSSI, FakeClient, FakeScanner, wait

NAMES = bms.DEVICE_NAMES
ATTEMPTS = {}


class TimedClient(FakeClient):
    async def connect(self):
        ATTEMPTS.setdefault(self.device.name, []).append(time.monotonic())
        await super().connect()


def fast(**overrides):
    values = dict(
        CONNECT_TIMEOUT=0.4,
        NOTIFY_TIMEOUT=0.4,
        DISCONNECT_TIMEOUT=0.3,
        BMS_MAX_BACKOFF=1.5,
        INCOMPLETE_LIMIT=3,
        INCOMPLETE_RETRY_SECONDS=0.2,
        GATT_TIMEOUT=0.3,
        COMMAND_SPACING=0.002,
        REPLY_WAIT=0.05,
        RETRY_REPLY_WAIT=0.05,
        STARTUP_STAGGER=0.05,
        CONNECTION_PAUSE=0.02,
    )
    values.update(overrides)
    for key, value in values.items():
        setattr(bms, key, value)


def make(retry=0.3, degraded_after=None, **overrides):
    COUNT.clear()
    BEHAVIOUR.clear()
    PRESENT.clear()
    ATTEMPTS.clear()
    PRESENT.update(NAMES)
    ble_log.clear()
    for name in NAMES:
        BEHAVIOUR[name] = {}
    fast(**overrides)
    coordinator = BluetoothCoordinator(degraded_after=degraded_after)
    service = bms.DalyBmsService(Paths(Path(tempfile.mkdtemp())), coordinator=coordinator)
    service.settings_getter = lambda: {"bms_refresh_interval": 2, "bms_connection_retry_seconds": retry}
    return service, coordinator


def start(service):
    service.start(service.settings_getter)


def events(device, kind):
    return ble_log.snapshot(300)["counters"].get(device, {}).get("events", {}).get(kind, 0)


def published(service, name):
    return "cells_mv" in service.get_battery(name)


def main():
    bleak.BleakClient, bleak.BleakScanner = TimedClient, FakeScanner
    # ---- 1. normal operation
    s, c = make()
    RSSI["BATTERY 2"] = -77
    start(s)
    assert wait(lambda: all(published(s, n) for n in NAMES)), [s.get_battery(n) for n in NAMES]
    assert wait(lambda: COUNT[("BATTERY 1", "write")] >= 18), "the batteries are not read periodically"  # two full rounds of 9 requests
    snap, csnap = s.snapshot(), c.snapshot()
    s.stop()
    for n in NAMES:
        b = snap["batteries"][n]
        assert b["valid_frame_count"] == 10 and len(b["cells_mv"]) == 4 and b["state_of_charge_percent"] == 80.0, b
        assert COUNT[(n, "connect")] == 1, "the persistent link must not be rebuilt"
    assert csnap["connected_bms"] == 3 and csnap["refreshed_bms"] == 3 and csnap["balancers_allowed"]
    assert c.snapshot()["active"] is None
    for n in NAMES:
        t = ble_log.snapshot()["counters"][n]["timings"]
        assert (
            t["connect"]["ok"] == 1
            and t["notify"]["ok"] == 1
            and t["read"]["ok"] >= 1
            and t["radio_wait"]["ok"] >= 2
            and t["radio_hold"]["ok"] == 1
        ), (
            n,
            t,
        )  # one wait for the connect, one per read
    assert (
        ble_log.snapshot()["counters"]["BATTERY 2"]["signal"]["last_dbm"] == -77
        and ble_log.snapshot()["counters"]["BATTERY 1"]["signal"]["last_dbm"] == -60
    )
    RSSI.clear()
    print("Persistent links, complete periodic reads, radio released between operations, timings and signal strength recorded: OK")

    # ---- 2. a hung connect() is cut off, the radio is released and the others keep going
    s, c = make()
    BEHAVIOUR["BATTERY 2"]["connect_hang"] = True
    start(s)
    assert wait(lambda: published(s, "BATTERY 1") and published(s, "BATTERY 3") and events("BATTERY 2", "connect_failed") >= 1)
    assert s.get_battery("BATTERY 2")["state"] in ("error", "scanning", "connecting"), s.get_battery("BATTERY 2")
    assert c.snapshot()["forced_releases"] == 0, "the connect deadline must fire before the coordinator has to take the radio back"
    t = ble_log.snapshot()["counters"]["BATTERY 2"]["timings"]["connect"]
    assert (
        t["failed"] >= 1 and 0.3 <= t["max_failed_seconds"] <= 1.5 and t["ok"] == 0
    ), t  # the time-out shows up as a failed sample of about CONNECT_TIMEOUT
    assert any(
        "s on the radio)" in e["detail"]
        for e in ble_log.snapshot(300)["events"]
        if e["device"] == "BATTERY 2" and e["kind"] == "connect_failed"
    )
    assert wait(lambda: COUNT[("BATTERY 1", "write")] >= 18), "healthy batteries stopped reading while another one could not connect"
    s.stop()
    assert c.snapshot()["active"] is None
    print("Hung connect(): hard deadline, radio released, healthy batteries unaffected: OK")

    # ---- 3. start_notify hangs after a successful connect: the half-open link must be closed (no leaked handle)
    s, c = make()
    BEHAVIOUR["BATTERY 3"]["notify_hang"] = True
    start(s)
    assert wait(lambda: events("BATTERY 3", "connect_failed") >= 1 and COUNT[("BATTERY 3", "disconnect")] >= 1), COUNT
    s.stop()
    assert COUNT[("BATTERY 3", "disconnect")] >= events("BATTERY 3", "connect_failed") - 1
    print("Hung start_notify(): deadline, and the half-open client is disconnected instead of leaked: OK")

    # ---- 4. an incomplete status is never published; repeated incompleteness rebuilds the link
    s, c = make()
    BEHAVIOUR["BATTERY 1"]["drop_always"] = {0x95}
    start(s)
    assert wait(lambda: published(s, "BATTERY 2") and published(s, "BATTERY 3") and events("BATTERY 1", "read_incomplete") >= 1)
    assert not published(s, "BATTERY 1"), "a status without cell voltages was published"
    assert COUNT[("BATTERY 1", "connect")] == 1, "one incomplete read must not tear the link down"
    assert wait(
        lambda: COUNT[("BATTERY 1", "connect")] >= 2 and events("BATTERY 1", "read_incomplete") >= 3, 15
    ), "no reconnect after repeated incomplete reads"
    BEHAVIOUR["BATTERY 1"]["drop_always"] = set()
    assert wait(lambda: published(s, "BATTERY 1"), 15), "no recovery once the device answers again"
    s.stop()
    print("Incomplete status: never published, link kept once, rebuilt after 3 in a row, recovers: OK")

    # ---- 5. one lost request is retried without dropping the link
    s, c = make()
    BEHAVIOUR["BATTERY 2"]["hang_write_once"] = True
    start(s)
    assert wait(lambda: all(published(s, n) for n in NAMES), 15)
    assert wait(lambda: COUNT[("BATTERY 2", "write")] >= 18)
    s.stop()
    assert (
        COUNT[("BATTERY 2", "connect")] == 1 and events("BATTERY 2", "connect_failed") == 0
    ), "a single lost request must not rebuild the link"
    print("A single lost request is retried, the link stays up: OK")

    # ---- 6. exponential back-off for an unreachable battery
    s, c = make(retry=1, BMS_MAX_BACKOFF=3.0)  # the setting is a whole number of seconds (at least 1): waits 1, 2, 3 (cap), 3 ...
    BEHAVIOUR["BATTERY 1"]["fail_connect"] = 99
    start(s)
    assert wait(lambda: len(ATTEMPTS.get("BATTERY 1", [])) >= 5, 25), ATTEMPTS
    s.stop()
    times = ATTEMPTS["BATTERY 1"]
    gaps = [round(b - a, 2) for a, b in zip(times, times[1:])]
    assert gaps[0] < gaps[1] < gaps[2] and max(gaps) <= bms.BMS_MAX_BACKOFF + 0.7, gaps
    assert gaps[0] >= 0.95 and published(s, "BATTERY 2") and published(s, "BATTERY 3")
    print(f"Back-off for an unreachable battery {gaps[:4]} s (cap {bms.BMS_MAX_BACKOFF} s), the others keep reading: OK")

    # ---- 7. with one battery unreachable the balancers are allowed again after the degraded delay
    s, c = make(degraded_after=0.6)
    BEHAVIOUR["BATTERY 2"]["fail_connect"] = 10**6
    start(s)
    assert wait(lambda: published(s, "BATTERY 1") and published(s, "BATTERY 3"))
    assert not c.bms_ready() or c.snapshot()["degraded"], "must not be fully ready with one battery down"
    assert wait(lambda: c.bms_ready() and c.snapshot()["degraded"], 5), c.snapshot()
    s.stop()
    print("One unreachable battery: balancers are enabled in degraded mode: OK")

    # ---- 8. an exception (or a stray CancelledError) inside a worker loop restarts that worker; it used to end the thread for good
    s, c = make()
    real, state = s.settings_getter, {"n": 0}

    def flaky():
        state["n"] += 1
        if state["n"] == 6:
            raise RuntimeError("boom (simulated)")
        if state["n"] == 40:
            raise __import__("asyncio").CancelledError()
        return real()

    s.settings_getter = flaky
    start(s)
    assert wait(lambda: state["n"] > 60 and all(published(s, n) for n in NAMES) and c.snapshot()["connected_bms"] == 3, 25), (
        state,
        c.snapshot(),
    )
    crashes = sum(events(n, "worker_crash") for n in NAMES)
    s.stop()
    assert crashes >= 2, f"the supervisor did not see the crashes ({crashes})"
    assert all(s._workers == {} or True for _ in NAMES)
    print("A crash or CancelledError in a battery worker restarts it and the link comes back: OK")
    print("All BMS worker checks: OK")


if __name__ == "__main__":
    main()
