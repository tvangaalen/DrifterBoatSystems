"""Non-hardware self-test for the Bluetooth event log: counters, timings, percentiles, slow-connect logging, JSON output."""

import json
import tempfile
import time
from pathlib import Path

from mastervolt.bluetooth import events as ble_events
from mastervolt.bluetooth.events import BleEventLog


def main():
    log = BleEventLog()
    for seconds in (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0):
        log.timing("DL-BAL1", "read", seconds, True)
    log.timing("DL-BAL1", "read", 30.0, False)
    t = log.snapshot()["counters"]["DL-BAL1"]["timings"]["read"]
    assert t["count"] == 11 and t["ok"] == 10 and t["failed"] == 1 and t["avg_ok_seconds"] == 5.5 and t["max_ok_seconds"] == 10.0
    assert (
        t["p50_ok_seconds"] == 6.0
        and t["p95_ok_seconds"] == 10.0
        and t["max_failed_seconds"] == 30.0
        and t["median_failed_seconds"] == 30.0
    )
    assert t["last_seconds"] == 30.0 and t["last_ok"] is False
    json.dumps(log.snapshot())  # everything must be serialisable for the API
    print("Timing statistics (average, median, p95, maxima, failed samples): OK")

    # only the most recent samples decide the percentiles, the totals keep counting
    log = BleEventLog()
    for _ in range(ble_events.TIMING_SAMPLES):
        log.timing("A", "connect", 20.0, True)
    for _ in range(ble_events.TIMING_SAMPLES):
        log.timing("A", "connect", 2.0, True)
    t = log.snapshot()["counters"]["A"]["timings"]["connect"]
    assert t["count"] == 2 * ble_events.TIMING_SAMPLES and t["p95_ok_seconds"] == 2.0 and t["max_ok_seconds"] == 20.0
    print("Percentiles follow the recent samples, totals keep counting: OK")

    # the context manager: success, exception and time-out are recorded as ok / failed, exceptions still propagate
    log = BleEventLog()
    with log.timed("A", "notify"):
        time.sleep(0.02)
    try:
        with log.timed("A", "notify"):
            raise TimeoutError("boom")
    except TimeoutError:
        pass
    else:
        raise AssertionError("the exception must propagate")
    t = log.snapshot()["counters"]["A"]["timings"]["notify"]
    assert t["ok"] == 1 and t["failed"] == 1 and t["avg_ok_seconds"] >= 0.02
    print("timed(): success and failure recorded, exceptions propagate: OK")

    # a slow but successful connect is written to the event list, a normal one and a failed one are not
    log = BleEventLog()
    log.timing("A", "connect", 1.5, True)
    log.timing("A", "connect", ble_events.SLOW_CONNECT_SECONDS + 1, True)
    log.timing("A", "connect", 18.0, False)
    log.timing("A", "read", 30.0, True)
    events = log.snapshot()["events"]
    assert [e["kind"] for e in events] == ["slow_connect"] and "9.0 s" in events[0]["detail"], events
    print("Slow connects are logged, normal, failed and other timings stay quiet: OK")

    # timings for a device without other events, counters untouched, clear() empties everything
    log = BleEventLog()
    log.timing("balancers", "scan", 12.0, True)
    snap = log.snapshot()["counters"]["balancers"]
    assert snap["timings"]["scan"]["count"] == 1 and snap["events"] == {} and snap["consecutive_failures"] == 0
    log.clear()
    assert log.snapshot() == {"counters": {}, "events": []}
    print("Timings of a device without events; clear(): OK")

    # logging never raises, also with rubbish and with a log file
    log = BleEventLog()
    log.timing("A", "connect", "not a number", True)
    log.timing("A", "connect", None, True)
    with tempfile.TemporaryDirectory() as folder:
        log.configure(Path(folder) / "logs" / "bluetooth.log")
        log.timing("A", "connect", 9.5, True)
        for handler in list(log._logger.handlers):
            handler.flush()
            handler.close()
        text = (Path(folder) / "logs" / "bluetooth.log").read_text(encoding="utf-8")
        assert "A slow_connect | connected after 9.5 s" in text, text
    print("Logging is failure-proof and slow connects reach the log file: OK")
    # signal strength: statistics, only the recent samples decide the recent average, rubbish and impossible values are ignored
    log = BleEventLog()
    for dbm in (-60, -70, -80):
        log.rssi("DL-BAL1", dbm)
    for bad in (None, "x", 0.5j, -200, 99, 21, -128):
        log.rssi("DL-BAL1", bad)
    s = log.snapshot()["counters"]["DL-BAL1"]["signal"]
    assert (
        s["count"] == 3
        and s["last_dbm"] == -80
        and s["min_dbm"] == -80
        and s["max_dbm"] == -60
        and s["avg_dbm"] == -70.0
        and s["recent_avg_dbm"] == -70.0
    ), s
    assert isinstance(s["last_seen_epoch"], float)
    for _ in range(ble_events.SIGNAL_SAMPLES):
        log.rssi("DL-BAL1", -50)
    s = log.snapshot()["counters"]["DL-BAL1"]["signal"]
    assert s["recent_avg_dbm"] == -50.0 and s["min_dbm"] == -80 and s["count"] == 3 + ble_events.SIGNAL_SAMPLES, s
    log.timing("DL-BAL1", "connect", 2.0, True)  # signal, timings and counters live side by side
    log.log("DL-BAL1", "connect_ok", quiet=True)
    both = log.snapshot()["counters"]["DL-BAL1"]
    assert "signal" in both and "timings" in both and both["events"]["connect_ok"] == 1
    json.dumps(log.snapshot())
    log.clear()
    assert log.snapshot() == {"counters": {}, "events": []}
    print("Signal strength statistics, invalid values ignored, coexists with timings: OK")
    print("All Bluetooth event log checks: OK")


if __name__ == "__main__":
    main()
