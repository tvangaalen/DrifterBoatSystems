"""GET /api/bms adds the curve SOC per battery (display only): the same numbers "Set SOC - charge/discharge" would write."""

from __future__ import annotations

from mastervolt.api.bms import with_curve_soc
from mastervolt.bluetooth.daly_protocol import SOC_CHARGING_POINTS, SOC_DISCHARGING_POINTS, soc_from_average_mv


def main():
    snapshot = {
        "busy": False,
        "batteries": {
            "BATTERY 1": {"battery": "BATTERY 1", "state": "connected", "cells_mv": [3300, 3300, 3320, 3280]},
            "BATTERY 2": {"battery": "BATTERY 2", "state": "not_read"},
        },
    }
    out = with_curve_soc(snapshot)
    one = out["batteries"]["BATTERY 1"]
    assert one["soc_charge_curve_percent"] == round(soc_from_average_mv(3300, SOC_CHARGING_POINTS), 1) == 50.0
    assert one["soc_discharge_curve_percent"] == round(soc_from_average_mv(3300, SOC_DISCHARGING_POINTS), 1) == 70.0
    assert "soc_charge_curve_percent" not in out["batteries"]["BATTERY 2"]  # no cells: unchanged, like 1.22.2
    assert "soc_charge_curve_percent" not in snapshot["batteries"]["BATTERY 1"]  # the service's own data is not touched
    assert out["busy"] is False
    print("Curve SOC per battery in GET /api/bms (charging and discharging curve, display only): OK")


if __name__ == "__main__":
    main()
