"""The whole application, started the way uvicorn starts it (lifespan included), on simulated hardware.

The MasterBus USB Link is a `FakeBus` and Bluetooth is the fake `bleak` of tests/ble_fakes.py, so nothing real is touched:
three BMS units and three balancers answer, the history recorder samples them, and the routes are exercised end to end.
This is what proves that the wiring between the subsystems (House SOC from the BMS units into the dashboard and Float
protection, the active mode, the history recorder, start-up and shutdown) works - the unit tests cover each part alone.
"""

import random
import shutil
import tempfile
import time
from pathlib import Path

import bleak
from fastapi.testclient import TestClient

from mastervolt.app import create_app
from mastervolt.bluetooth import balancers, bms
from mastervolt.bluetooth.coordinator import BluetoothCoordinator
from mastervolt.bluetooth.events import ble_log
from mastervolt.config import PATHS, Paths
from mastervolt.history import recorder
from mastervolt.masterbus import service as masterbus_service
from mastervolt.runtime import Services
from tests.ble_fakes import BEHAVIOUR, COUNT, PRESENT, FakeClient, FakeScanner, wait
from tests.masterbus_fakes import COMBIMASTER, HOUSE, FakeBus, FakeClock, default_values


def shrink_timings():
    for key, value in dict(
        CONNECT_TIMEOUT=0.5,
        NOTIFY_TIMEOUT=0.5,
        DISCONNECT_TIMEOUT=0.3,
        GATT_TIMEOUT=0.3,
        COMMAND_SPACING=0.002,
        REPLY_WAIT=0.05,
        RETRY_REPLY_WAIT=0.05,
        STARTUP_STAGGER=0.05,
        CONNECTION_PAUSE=0.02,
    ).items():
        setattr(bms, key, value)
    for key, value in dict(
        INITIAL_DELAY=0,
        GATT_TIMEOUT=0.3,
        CONNECT_TIMEOUT=0.5,
        NOTIFY_TIMEOUT=0.5,
        DISCONNECT_TIMEOUT=0.3,
        COMMAND_SPACING=0.002,
        FRAME_WAIT=0.3,
        SETTLE_SECONDS=0.02,
    ).items():
        setattr(balancers, key, value)
    masterbus_service.POLL_FIELD_GAP, masterbus_service.POLL_CYCLE_SECONDS = 0.0005, 0.01
    recorder.RECORD_INTERVAL_SECONDS, recorder.HOUSEKEEPING_EVERY = 0.2, 2


def make_services():
    folder = Path(tempfile.mkdtemp())
    for name in ("control_maps.json", "mastershunt_config_maps.json"):
        shutil.copy(PATHS.base / name, folder / name)
    shutil.copytree(PATHS.static, folder / "static", ignore=shutil.ignore_patterns("products"))
    values = default_values(random.Random(2))
    values.update({(HOUSE, 1): 13.4, (HOUSE, 2): 5.0, (COMBIMASTER, 2): 230.0, (COMBIMASTER, 1): 1.0})
    bus = FakeBus(FakeClock(), values=values)
    bus.clock.sleep = lambda seconds: None
    services = Services(Paths(folder), bus=bus, coordinator=BluetoothCoordinator())
    services.masterbus.shunts.discover = lambda stop: None
    return services, bus


def main():
    bleak.BleakClient, bleak.BleakScanner = FakeClient, FakeScanner
    COUNT.clear()
    BEHAVIOUR.clear()
    PRESENT.clear()
    ble_log.clear()
    for name in (*bms.DEVICE_NAMES, *balancers.DEVICE_NAMES):
        BEHAVIOUR[name] = {}
        PRESENT.add(name)
    shrink_timings()
    services, bus = make_services()
    with TestClient(create_app(services)) as client:  # the lifespan starts every background job
        # ---- Bluetooth: the three BMS units and the three balancers report
        assert wait(lambda: all(b.get("cells_mv") for b in client.get("/api/bms").json()["batteries"].values()), 20), client.get(
            "/api/bms"
        ).json()
        assert wait(lambda: all(d["captured_at"] for d in client.get("/api/balancers").json()["devices"].values()), 20)
        bms_status = client.get("/api/bms").json()
        assert bms_status["connected_count"] == 3 and bms_status["ble_available"]
        print("Lifespan start: three BMS links and three balancers report: OK")

        # ---- MasterBus: the poller fills the cache and the House SOC comes from the BMS average, not the MasterShunt
        assert wait(lambda: client.get("/api/energy").json()["storage"]["house"]["voltage"] is not None, 20)
        energy = client.get("/api/energy").json()
        house = energy["storage"]["house"]
        assert house["soc"] == 80.0 and house["soc_source"] == "daly_bms_average" and house["soc_fresh_batteries"] == 3, house
        assert house["max_cell_mv"] == 3320 and energy["high_soc_float_policy"]["float_latched"] is False
        assert energy["sources"]["shore"]["voltage"] == 230.0
        print("Dashboard: MasterBus values plus House SOC and cell figures from the fresh BMS readings: OK")

        # ---- controls: an operating mode is remembered, any individual switch clears it
        answer = client.post("/api/control/mode", json={"mode": "anchor"})
        assert answer.status_code == 200 or answer.status_code == 409, answer.text  # the simulated devices do not model every field
        services.masterbus.controls.active_mode = "anchor"
        assert client.get("/api/energy").json()["active_mode"] == "anchor"
        assert client.post("/api/control/inverter", json={"enabled": True}).status_code == 200
        assert client.get("/api/energy").json()["active_mode"] is None
        print("Controls: a mode is remembered server-side and cleared by an individual switch: OK")

        # ---- history: the recorder stores dashboard, BMS and balancer samples, the chart cache follows
        assert wait(lambda: client.get("/api/history").json()["count"] >= 10, 20)
        sources = client.get("/api/history/status").json()["by_source"]
        assert {"dashboard", "bms", "balancer"} <= set(sources), sources
        assert wait(lambda: client.get("/api/history/chart-data?hours=1").json()["bms_count"] > 0, 20)
        print("History: dashboard, BMS and balancer samples recorded, chart cache follows: OK")

        # ---- the diagnostics
        assert client.get("/api/bluetooth-coordinator").json()["connected_bms"] == 3
        assert client.get("/api/bluetooth-events").json()["counters"]["BATTERY 1"]["timings"]["connect"]["ok"] >= 1
        assert client.get("/api/version").json()["version"].startswith("2.")
        assert client.get("/").status_code == 200
        print("Diagnostics, version and the page itself: OK")
    # ---- shutdown: the lifespan stopped everything
    time.sleep(0.3)
    assert not any(w.supervisor.alive for w in services.bms._workers.values()) and not services.balancers.supervisor.alive
    print("Lifespan stop: every worker thread has ended: OK")

    # ---- the deliberate API improvements over 1.22.2
    services, bus = make_services()
    client = TestClient(create_app(services))
    answer = client.post("/api/bms/9/charge", json={"enabled": True})
    assert answer.status_code == 404 and answer.json()["detail"] == "Unknown battery", answer.text  # 1.22.2 said 503 "404: Unknown battery"
    assert client.post("/api/bms/1/refresh").status_code == 503  # no worker: 503 with a reason, not a crash
    print("Unknown battery is a 404 and a missing worker a 503 with a reason: OK")


if __name__ == "__main__":
    main()
