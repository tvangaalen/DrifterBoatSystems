"""DALY decoding, House SOC and history results must be identical to the verified 1.22.2 release.

py -m tests.test_misc_golden                        # verify
py -m tests.test_misc_golden --generate <old-tree>  # regenerate from an old checkout
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from tests.test_masterbus_golden import differences

GOLDEN = Path(__file__).resolve().parent / "golden" / "misc.json"


def old_modules(tree):
    sys.path.insert(0, tree)
    import daly_balancer_service as balancer
    import daly_bms_service as bms
    import history_service
    import house_soc

    class Protocol:
        request = staticmethod(bms.request)
        write_frame = staticmethod(bms.write_frame)
        decode = staticmethod(bms.decode)
        decode_alarm_bytes = staticmethod(bms.decode_alarm_bytes)
        snapshot_from_frames = staticmethod(bms.snapshot_from_frames)
        soc_from_average_mv = staticmethod(bms.soc_from_average_mv)
        charging_points, discharging_points = bms.SOC_CHARGING_POINTS, bms.SOC_DISCHARGING_POINTS

    # the balancer service builds its own request and decodes with the BMS decoder
    assert balancer.status_request(0x90) == bms.request(0x90)
    return Protocol, house_soc, history_service.HistoryService


def new_modules():
    from mastervolt import soc
    from mastervolt.bluetooth import daly_protocol as dp
    from mastervolt.history.service import HistoryService

    class Protocol:
        request = staticmethod(dp.status_request)
        write_frame = staticmethod(dp.write_frame)
        decode = staticmethod(dp.decode)
        decode_alarm_bytes = staticmethod(dp.decode_alarm_bytes)
        snapshot_from_frames = staticmethod(dp.snapshot_from_frames)
        soc_from_average_mv = staticmethod(dp.soc_from_average_mv)
        charging_points, discharging_points = dp.SOC_CHARGING_POINTS, dp.SOC_DISCHARGING_POINTS

    return Protocol, soc, HistoryService


def collect(protocol, house, history):
    from tests import golden_misc as g

    return {"daly": g.run_daly(protocol), "house_soc": g.run_house_soc(house), "history": g.run_history(history)}


def main():
    if "--generate" in sys.argv:
        result = collect(*old_modules(sys.argv[sys.argv.index("--generate") + 1]))
        GOLDEN.write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
        print(f"golden file written: {GOLDEN} ({GOLDEN.stat().st_size} bytes)")
        return
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    actual = json.loads(json.dumps(collect(*new_modules()), sort_keys=True))
    problems = list(differences(expected, actual))
    for line in problems[:40]:
        print("DIFFERENCE", line)
    assert not problems, f"{len(problems)} differences from the verified 1.22.2 behaviour"
    print(
        f"DALY decoding ({len(expected['daly']['decode'])} frames), House SOC ({len(expected['house_soc']['soc'])} cases) and history "
        f"({expected['history']['count']} records, charts, contributions) - identical to 1.22.2: OK"
    )


if __name__ == "__main__":
    main()
