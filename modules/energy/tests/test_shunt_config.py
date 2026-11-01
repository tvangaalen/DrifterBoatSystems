"""MasterShunt configuration discovery: a long, bus-hogging conversation that is only repeated when its result is old."""

import json
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path

from mastervolt.config import PATHS
from mastervolt.masterbus import shunt_config
from mastervolt.masterbus.io import BusIO
from tests.masterbus_fakes import FakeBus, FakeClock

SCHEMA = [
    {"index": 19, "name": "Battery capacity", "unit": "Ah"},
    {"index": 20, "name": "Battery  Type", "unit": ""},
    {"index": 3, "name": "Voltage", "unit": "V"},
]
OPTIONS = [{"index": 0, "string_id": 1, "label": "Flooded"}, {"index": 3, "string_id": 4, "label": "MLI"}]


def main():
    calls = []

    class StubDiscovery:
        def __init__(self, io):
            pass

        def schema(self, addr, max_index):
            calls.append(addr)
            return SCHEMA

    class StubControlDiscovery:
        def __init__(self, io):
            pass

        def list_options(self, addr, field, protocol="btm1"):
            return OPTIONS

    shunt_config.Discovery, shunt_config.ControlDiscovery = StubDiscovery, StubControlDiscovery
    folder = Path(tempfile.mkdtemp())
    path = folder / "mastershunt_config_maps.json"
    io = BusIO(FakeBus(FakeClock()))
    stop = threading.Event()

    # no saved result: discover, remember, and describe from it
    config = shunt_config.MasterShuntConfig(io, path)
    assert not config.is_fresh()
    config.discover(stop)
    assert len(calls) == 3 and path.exists() and set(json.loads(path.read_text())) == {"house", "start", "bow"}
    assert (0x6DB09B, 19) in config.extra_poll_fields() and (0x6DB09B, 20) in config.extra_poll_fields()
    io.put(0x6DB09B, 20, 3.0)
    io.put(0x6DB09B, 19, 960.0)
    described = config.describe("house", 0x6DB09B, "LiFePO4")
    assert described["battery_type"] == "MLI" and described["capacity"] == 960.0 and described["config_discovered"] is True
    print("Discovery with no saved result: found by name, saved, used for the dashboard: OK")

    # a fresh saved result is trusted: no conversation with the devices at all
    calls.clear()
    again = shunt_config.MasterShuntConfig(io, path)
    assert again.is_fresh()
    again.discover(stop)
    assert not calls, "a recent result must not trigger discovery (it starved the poller for a minute after every start)"
    print("A recent saved result is trusted: no discovery at start-up: OK")

    # an old result (or force) is refreshed
    old = time.time() - 31 * 86400
    os.utime(path, (old, old))
    assert not shunt_config.MasterShuntConfig(io, path).is_fresh()
    stale = shunt_config.MasterShuntConfig(io, path)
    stale.discover(stop)
    assert len(calls) == 3 and shunt_config.MasterShuntConfig(io, path).is_fresh()
    calls.clear()
    shunt_config.MasterShuntConfig(io, path).discover(stop, force=True)
    assert len(calls) == 3
    print("An old result (over 30 days) or force=True is discovered again: OK")

    # the tracked mapping file in the project is a real, non-empty result
    shutil.copy(PATHS.mastershunt_maps_file, folder / "copy.json")
    assert shunt_config.MasterShuntConfig(io, folder / "copy.json").maps


if __name__ == "__main__":
    main()
