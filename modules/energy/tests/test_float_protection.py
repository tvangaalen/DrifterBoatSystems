"""Non-hardware test of the real Float-protection loop (`FloatProtection.run`) with stubbed hardware access: no USB, no writes.

Float is triggered purely by the highest single cell voltage of the three BMS units (the SOC trigger was removed in
1.17.0); an unknown (stale) reading never starts it and holds it while latched; every fresh start sets all batteries to
100% once. The exact frames the loop sends are covered by tests/test_masterbus_golden.py.
"""

import time

from mastervolt.masterbus.float_policy import FloatProtection


class Clock:
    """Stands in for stop_event: every 3 s wait becomes a few milliseconds and the loop ends after `ticks`."""

    def __init__(self, ticks, hook=None):
        self.ticks, self.count, self.hook = ticks, 0, hook

    def wait(self, seconds):
        self.count += 1
        if self.hook:
            self.hook(self.count)
        time.sleep(0.002)
        return self.count > self.ticks

    def set(self):
        self.count = 10**9


class StubIO:
    """Only what the loop reads from the bus layer: the cached charger states."""

    def __init__(self, current):
        self.current = current

    def cached(self, addr, field):
        return self.current["state"]


def run_loop(cell_at_tick, ticks, state=3, details=True, tick_action=None, soc_at_tick=None, enabled=True):
    """Run the real loop. cell_at_tick(n) -> (max_cell_mv or None, battery name); this alone drives the decision.
    soc_at_tick(n) -> SOC percent, purely informational (defaults to a constant 70%, far below the old 95% threshold,
    to prove the SOC average does not affect Float protection). Returns the protection, the writes and the state."""
    settings = {"float_protection_enabled": enabled, "float_cell_trigger_mv": 3500.0, "float_cell_resume_mv": 3420.0}
    current = {"n": 0, "state": state}
    seen = []
    protection = FloatProtection(StubIO(current), lambda: dict(settings), Clock(ticks))
    writes = []
    protection.force_float = lambda name, *args: writes.append(("float", name)) or {"changed": True, "state": 3}
    protection.force_bulk = lambda name, *args: writes.append(("bulk", name)) or {"changed": True, "state": 1}
    protection.started_calls = []
    protection.started_callback = lambda: protection.started_calls.append(current["n"])

    def hook(n):
        current["n"] = n
        if tick_action:
            tick_action(n, protection, current)
        status = dict(protection.status)
        seen.append((n, status.get("soc_source"), status.get("float_latched"), status.get("soc_held")))

    protection.stop_event = Clock(ticks, hook)
    soc_fn = soc_at_tick or (lambda n: 70.0)
    protection.soc_getter = lambda: soc_fn(current["n"])

    def detail_getter():
        max_cell_mv, battery = cell_at_tick(current["n"])
        stale = max_cell_mv is None
        return {
            "soc": soc_fn(current["n"]),
            "fresh_batteries": 0 if stale else 3,
            "stale_batteries": 3 if stale else 0,
            "youngest_age_seconds": 30.0 if stale else 4.0,
            "last_known_soc": 96.0,
            "max_cell_mv": max_cell_mv,
            "max_cell_battery": battery,
        }

    if details:
        protection.details_getter = detail_getter
    protection.run()
    return protection, writes, seen, current


def main():
    # a) a fresh cell at or above the trigger: Float is forced on a charging source
    p, writes, _, _ = run_loop(lambda n: (3550, "BATTERY 1"), 4, state=1)
    assert ("float", "charger_house") in writes and p.status["soc_source"] == "daly_bms" and not p.status["soc_held"]
    assert p.status["trigger"] == "cell_voltage"
    assert p.started_calls == [1], "Float starting for the first time must trigger the all-batteries-to-100% callback exactly once"

    # b) latched, then the cell reading goes stale while a source is charging again: Float is still forced, Bulk is not resumed
    def stale_after_three(n):
        return (3550, "BATTERY 1") if n <= 3 else (None, None)

    def source_restarts(n, protection, current):  # the solar charger starts a new charge cycle in the hold
        if n == 6:
            current["state"] = 1
            protection.last_attempt.clear()

    p, writes, seen, _ = run_loop(stale_after_three, 12, state=3, tick_action=source_restarts)
    st = p.status
    assert st["soc_source"] == "stale_hold" and st["soc_held"] and st["float_latched"] and st["active"], st
    assert ("float", "charger_house") in writes, "a source that restarts while the cell reading is unknown must be put back in Float"
    assert not [w for w in writes if w[0] == "bulk"], "Bulk must never be resumed on stale data"
    assert p.started_calls == [1], "holding Float on a stale reading must not re-trigger the 100% callback"

    # c) latched, the cell reading returns cooled down: Bulk resumes on fresh data only
    def recover(n):
        return (3550, "BATTERY 1") if n <= 2 else ((None, None) if n <= 6 else (3400, "BATTERY 1"))

    p, writes, _, current = run_loop(recover, 12, state=3)
    assert ("bulk", "charger_house") in writes and not p.status["float_latched"] and p.status["soc_source"] == "daly_bms"

    # d) never latched (for example just after a restart) and no fresh cell reading: nothing is started
    p, writes, _, _ = run_loop(lambda n: (None, None), 6, state=1)
    assert not writes and not p.status["float_latched"] and p.status["max_cell_mv"] is None

    # e) no details getter at all (a service that cannot report cell voltage): Float can never be told to start
    p, writes, _, _ = run_loop(lambda n: (3550, "BATTERY 1"), 4, state=1, details=False)
    assert not writes and p.status["max_cell_mv"] is None

    # f) protection disabled: never writes, latch cleared
    p, writes, _, _ = run_loop(lambda n: (3600, "BATTERY 1"), 4, state=1, enabled=False)
    assert not writes and not p.status["float_latched"]
    print("Float loop: a fresh hot cell acts, a stale cell holds Float without resuming Bulk, an unknown cell never starts anything: OK")

    # g) the failure mode this was built for (CHANGELOG 1.13.0): the pack-average SOC stays far below the old 95% threshold,
    #    but one battery's cell reaches the trigger - Float must engage on that alone
    p, writes, _, _ = run_loop(lambda n: (3400, None) if n <= 2 else (3550, "BATTERY 1"), 6, state=1, soc_at_tick=lambda n: 70.0)
    st = p.status
    assert st["house_soc"] == 70.0 and st["active"] and st["trigger"] == "cell_voltage", st
    assert ("float", "charger_house") in writes, "Float must engage on a hot cell even while the SOC average stays low the whole time"
    assert st["max_cell_mv"] == 3550 and st["max_cell_battery"] == "BATTERY 1"

    # h) latched on a hot cell: Bulk must not resume while the cell stays above the resume level
    p, writes, _, _ = run_loop(lambda n: (3550, "BATTERY 1"), 6, state=3, soc_at_tick=lambda n: 80.0)
    assert not [w for w in writes if w[0] == "bulk"], "must not resume to Bulk while a cell is still above the resume level"
    assert p.status["float_latched"] and p.status["trigger"] == "cell_voltage"

    # i) ... and does resume once the cell has cooled down too
    p, writes, _, _ = run_loop(lambda n: (3550, "BATTERY 1") if n <= 3 else (3400, "BATTERY 1"), 8, state=3)
    assert ("bulk", "charger_house") in writes and not p.status["float_latched"]

    # j) the cell reading is exactly what latched Float; if it goes stale, hold rather than resume blind
    p, writes, _, _ = run_loop(lambda n: (3550, "BATTERY 1") if n <= 2 else (None, None), 6, state=3)
    assert p.status["float_latched"] and p.status["trigger"] == "held", p.status
    assert not [w for w in writes if w[0] == "bulk"], "must not resume while the cell reading that latched Float has gone stale"
    print("Cell-voltage trigger wired into the real loop: engages, blocks resume, holds on a stale cell reading: OK")

    # k) the all-batteries-to-100% callback fires again on a fresh re-latch after a resume, but never while merely held
    #    or while already latched (charging -> Float -> cooled, Bulk resumed -> charging again -> hot again)
    def start_resume_restart(n):
        if n <= 2:
            return (3550, "BATTERY 1")  # Float starts
        if n <= 5:
            return (3400, "BATTERY 1")  # cools down, Bulk resumes
        return (3550, "BATTERY 1")  # heats up again: a second, independent Float start

    def stage_transitions(n, protection, current):
        if n == 2:
            current["state"] = 3  # hardware confirms Float, as commanded at n=1
        elif n == 6:
            current["state"] = 1  # back to charging before the second trigger

    p, writes, _, _ = run_loop(start_resume_restart, 8, state=1, tick_action=stage_transitions)
    assert ("float", "charger_house") in writes and ("bulk", "charger_house") in writes
    assert p.started_calls == [1, 6], "a resume followed by a fresh trigger must fire the 100% callback again, once per rising edge"
    print("The all-batteries-to-100% callback fires once per fresh Float start, never on hold or while already latched: OK")


if __name__ == "__main__":
    main()
