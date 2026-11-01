"""Non-hardware tests for mastervolt/soc.py: the age of each DALY reading, the average of the fresh ones, the cell-voltage
statistics and the Float decision table (a pure function of the highest cell voltage)."""

from datetime import UTC, datetime

from mastervolt import soc

NOW = 1_800_000_000.0


def stamp(age):
    return datetime.fromtimestamp(NOW - age, UTC).isoformat()


def bank(*items):
    return {f"BATTERY {i + 1}": {"state_of_charge_percent": soc, "captured_at": stamp(age)} for i, (soc, age) in enumerate(items)}


def cell_bank(*items):
    """items: (cells_mv list, age). captured_at only - state_of_charge_percent deliberately omitted (house_soc()
    and cell_voltage_stats() must work independently of each other, from the same battery dict)."""
    return {f"BATTERY {i + 1}": {"cells_mv": cells, "captured_at": stamp(age)} for i, (cells, age) in enumerate(items)}


def main():
    limit = soc.max_age_seconds(30)
    assert limit == 120 and soc.max_age_seconds(60) == 240 and soc.max_age_seconds("x") == 120 and soc.max_age_seconds(5) == 120

    d = soc.house_soc(bank((96, 5), (98, 10), (94, 20)), NOW, limit)
    assert abs(d["soc"] - 96) < 1e-9 and d["fresh_batteries"] == 3 and d["stale_batteries"] == 0 and d["youngest_age_seconds"] == 5

    d = soc.house_soc(bank((96, 5), (98, 900), (94, 20)), NOW, limit)  # one battery silent for 15 minutes
    assert abs(d["soc"] - 95) < 1e-9 and d["fresh_batteries"] == 2 and d["stale_batteries"] == 1
    assert abs(d["last_known_soc"] - 96) < 1e-9

    d = soc.house_soc(bank((96, 500), (98, 900), (94, 700)), NOW, limit)  # everything old: no current SOC at all
    assert d["soc"] is None and d["fresh_batteries"] == 0 and d["stale_batteries"] == 3 and abs(d["last_known_soc"] - 96) < 1e-9

    b = bank((96, 5), (98, 5), (94, 5))
    b["BATTERY 2"]["captured_at"] = None  # no timestamp = age unknown = not fresh
    b["BATTERY 3"]["captured_at"] = "garbage"
    d = soc.house_soc(b, NOW, limit)
    assert d["soc"] == 96 and d["stale_batteries"] == 2
    b = bank((96, 5), (150, 5), (-3, 5))  # out-of-range values are ignored
    assert soc.house_soc(b, NOW, limit)["soc"] == 96
    assert soc.house_soc({}, NOW, limit)["soc"] is None
    naive = {
        "BATTERY 1": {
            "state_of_charge_percent": 90,
            "captured_at": datetime.fromtimestamp(NOW - 10, UTC).replace(tzinfo=None).isoformat(),
        }
    }
    assert soc.house_soc(naive, NOW, limit)["fresh_batteries"] == 1, "timestamps without a zone are treated as UTC"
    future = bank((90, -30))
    assert soc.house_soc(future, NOW, limit)["fresh_batteries"] == 1, "a small clock difference must not make a reading stale"
    print("Freshness and averaging of the house SOC: OK")

    # ---- cell_voltage_stats(): the highest single cell and the worst per-battery spread, from the same freshness gate
    banks = cell_bank(([3380, 3395, 3388, 3390], 5), ([3900, 3382, 3379, 3376], 10), ([3370, 3365, 3372, 3368], 20))
    d = soc.cell_voltage_stats(banks, NOW, limit)  # reproduces the reported incident: one runaway cell
    assert d["max_cell_mv"] == 3900 and d["max_cell_battery"] == "BATTERY 2"
    assert d["max_spread_mv"] == 3900 - 3376 and d["max_spread_battery"] == "BATTERY 2"

    stale = cell_bank(([3900, 3382, 3379, 3376], 900), ([3370, 3365, 3372, 3368], 10))  # the hot battery's link is down
    d = soc.cell_voltage_stats(stale, NOW, limit)
    assert (
        d["max_cell_mv"] == 3372 and d["max_cell_battery"] == "BATTERY 2"
    ), "a stale battery must not contribute its (possibly dangerous) last reading"

    assert soc.cell_voltage_stats({}, NOW, limit) == {
        "max_cell_mv": None,
        "max_cell_battery": None,
        "max_spread_mv": None,
        "max_spread_battery": None,
    }
    pre_computed = {
        "BATTERY 1": {"cells_mv": [3400, 3410], "cell_spread_mv": 999, "captured_at": stamp(5)}
    }  # trust an existing cell_spread_mv field
    assert soc.cell_voltage_stats(pre_computed, NOW, limit)["max_spread_mv"] == 999
    print("cell_voltage_stats(): highest cell and worst spread, stale batteries excluded: OK")

    # ---- float_decision(): (active, resume, held, trigger) - purely from the highest cell voltage; the SOC
    # trigger was removed in 1.17.0 (see CHANGELOG), so the SOC average plays no part in this decision any more.
    f = soc.float_decision  # (enabled, latched, max_cell_mv, cell_trigger_mv, cell_resume_mv)
    assert f(True, False, 3550, 3500, 3420) == (True, False, False, "cell_voltage"), "a cell at or above the trigger forces Float"
    assert f(True, False, 3400, 3500, 3420) == (False, False, False, None), "a normal cell (below the trigger) does not force Float"
    assert f(True, True, 3450, 3500, 3420) == (
        False,
        False,
        False,
        None,
    ), "between the trigger and the resume level nothing is forced and Bulk is not resumed"
    assert f(True, True, 3400, 3500, 3420) == (False, True, False, None), "every cell at or below the resume level ends Float"
    assert f(True, True, None, 3500, 3420) == (
        True,
        False,
        True,
        "held",
    ), "unknown cell reading while latched: hold Float, never resume Bulk"
    assert f(True, False, None, 3500, 3420) == (False, False, False, None), "an unknown cell reading must not start Float protection"
    assert f(False, True, None, 3500, 3420) == (False, False, False, None) and f(False, True, 3600, 3500, 3420) == (
        False,
        False,
        False,
        None,
    )
    print("Cell-voltage Float trigger: starts, resumes, and holds on an unknown reading: OK")


if __name__ == "__main__":
    main()
