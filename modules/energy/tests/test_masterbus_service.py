"""The MasterBus service: the background poller fills the cache, and a USB Link that is missing at start-up or vanishes
later is reopened by itself (it used to need a server restart)."""

import random
import shutil
import tempfile
import time
from pathlib import Path

from mastervolt.config import PATHS, Paths
from mastervolt.masterbus import service as svc
from tests.ble_fakes import wait
from tests.masterbus_fakes import ALTERNATOR, COMBIMASTER, HOUSE, FakeBus, FakeClock, default_values


def make(**bus_options):
    folder = Path(tempfile.mkdtemp())
    for name in ("control_maps.json", "mastershunt_config_maps.json"):
        shutil.copy(PATHS.base / name, folder / name)
    values = default_values(random.Random(1))
    values[(HOUSE, 1)] = 13.4
    values[(COMBIMASTER, 2)] = 230.0
    bus = FakeBus(FakeClock(), values=values)
    for name, value in bus_options.items():
        setattr(bus, name, value)
    service = svc.MasterBusService(Paths(folder), bus=bus)
    service.shunts.discover = (
        lambda stop: None
    )  # start-up discovery is a long read-only conversation with real devices; not what is tested here
    return service, bus


def house_voltage(service):
    """The house voltage, rounded: the bus carries 32-bit floats (13.4 arrives as 13.3999996)."""
    value = service.energy()["storage"]["house"]["voltage"]
    return None if value is None else round(value, 2)


def main():
    svc.POLL_FIELD_GAP, svc.POLL_CYCLE_SECONDS, svc.REOPEN_PAUSE_SECONDS = 0.0005, 0.01, 0.05

    # ---- 1. the poller fills the cache; the dashboard is built from it
    s, bus = make()
    s.start()
    assert wait(lambda: house_voltage(s) == 13.4 and s.energy()["sources"]["shore"]["voltage"] == 230.0, 20), "the cache was not filled"
    assert bus.opens == 1
    s.close()
    print("The poller opens the Link and fills the cache the dashboard is built from: OK")

    # ---- 2. the Link is not there at start-up: retried until it is, no restart needed
    s, bus = make(open_failures=3)
    s.start()
    assert wait(lambda: bus.opens == 1 and house_voltage(s) == 13.4, 20), (bus.opens, bus.open_failures)
    s.close()
    print("A USB Link that is not there at start-up is retried until it appears: OK")

    # ---- 3. the Link vanishes while running: closed and opened again, polling resumes
    s, bus = make()
    s.start()
    assert wait(lambda: house_voltage(s) == 13.4, 20)
    bus.broken = True
    bus.values[(HOUSE, 1)] = 12.9
    assert wait(lambda: bus.opens >= 2 and bus.closes >= 1, 20), "the Link was not reopened"
    assert wait(lambda: house_voltage(s) == 12.9, 20), "polling did not resume after the reopen"
    s.close()
    print("A USB Link that vanishes while running is reopened and polling resumes: OK")

    # ---- 4. a device that just does not answer (an unpowered regulator) is not a bus error
    s, bus = make()
    bus.values.pop((ALTERNATOR, 5))
    s.start()
    assert wait(lambda: house_voltage(s) == 13.4, 20)
    time.sleep(0.5)
    assert bus.opens == 1 and bus.closes == 0, "an unanswered field must not make the service reopen the Link"
    s.close()
    print("An unanswered field is not mistaken for a lost Link: OK")

    # ---- 5. stopping ends the retry loop promptly
    s, bus = make(open_failures=10**6)
    s.start()
    time.sleep(0.2)
    started = time.monotonic()
    s.close()
    time.sleep(0.2)
    assert time.monotonic() - started < 1.0
    print("Stopping while the Link is missing returns promptly: OK")


if __name__ == "__main__":
    main()
