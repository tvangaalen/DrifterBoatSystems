"""The maintenance schedule: the periodic items of the Yanmar 4JH80 with its KM4A marine gear, and when each is due.

The items and intervals are Yanmar's *Periodic Maintenance Schedule* (JH Series Operation Manual 0AJHC-M00011, pages
81-82; the KM4A's oil from the same manual, pages 43 and 85), the user's choice of 2026-11-12. Daily checks are left out
(they are done before leaving), and so are the "initial 50 hours" items of a new engine. An interval is in engine hours,
in months, or both ("whichever comes first"). "dealer": Yanmar marks it for an authorized dealer.

A maintenance entry ticks the items it did (`items`, their ids); an item's last time is the newest entry that ticks it.
"""
from __future__ import annotations

from datetime import date

# (id, system, item, hours, months, action, dealer, note)
ITEMS: list[tuple[str, str, str, float | None, int | None, str, bool, str]] = [
    ("fuel_separator", "Fuel", "Drain the fuel/water separator", 50, 1, "check", False, ""),
    ("fuel_tank", "Fuel", "Drain water and sediment from the fuel tank", 250, 12, "check", False, ""),
    ("fuel_filter", "Fuel", "Replace the fuel filter element", 250, 12, "replace", False, ""),
    ("engine_oil", "Lubrication", "Replace the engine oil", 250, 12, "replace", False, ""),
    ("oil_filter", "Lubrication", "Replace the engine oil filter", 250, 12, "replace", False, ""),
    ("gear_oil", "Lubrication", "Replace the marine gear oil (KM4A)", 250, 12, "replace", False, "API CD or higher, SAE 20 or 30; the KM4A has no oil filter"),
    ("impeller_check", "Cooling", "Check the seawater pump impeller", 250, 12, "check", False, ""),
    ("impeller", "Cooling", "Replace the seawater pump impeller", 1000, 48, "replace", False, ""),
    ("coolant", "Cooling", "Replace the coolant", None, 12, "replace", False, "Long Life coolant: every 2 years"),
    ("seawater_passages", "Cooling", "Clean and check the seawater passages", 1000, 48, "check", True, ""),
    ("air_filter", "Air intake and exhaust", "Clean the intake silencer (air cleaner) element", 250, 12, "check", False, ""),
    ("elbow_clean", "Air intake and exhaust", "Clean the exhaust/water mixing elbow", 250, 12, "check", False, ""),
    ("elbow", "Air intake and exhaust", "Replace the exhaust/water mixing elbow", 500, 24, "replace", False, ""),
    ("turbo", "Air intake and exhaust", "Wash the turbocharger blower", 250, 12, "check", True, ""),
    ("battery", "Electrical", "Check the battery electrolyte level", 50, 1, "check", False, "serviceable batteries only"),
    ("belt_check", "Electrical", "Check the alternator V-ribbed belt tension", 250, 12, "check", False, ""),
    ("belt", "Electrical", "Replace the alternator V-ribbed belt", 1000, 48, "replace", False, ""),
    ("wiring", "Electrical", "Check the wiring connectors", 250, 12, "check", False, ""),
    ("bolts", "Cylinder head and block", "Tighten all major nuts and bolts", 250, 12, "check", True, ""),
    ("valves", "Cylinder head and block", "Adjust the intake/exhaust valve clearance", 1000, 48, "check", True, ""),
    ("remote", "Other", "Check the remote control cables", 1000, 48, "check", True, ""),
    ("shaft", "Other", "Adjust the propeller shaft alignment", 1000, 48, "check", True, ""),
    ("hoses", "Other", "Replace the rubber hoses (fuel and water)", None, 24, "replace", False, ""),
]
IDS = {i[0] for i in ITEMS}


def add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    days = [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return date(y, m, min(d.day, days))


def clean_items(value) -> list[str]:
    """The ticked items of a maintenance entry: known ids, each once, in the schedule's order."""
    if value is None: return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value): raise ValueError("Items must be a list of schedule items")
    bad = [v for v in value if v not in IDS]
    if bad: raise ValueError(f"Unknown schedule item: {bad[0]}")
    return [i[0] for i in ITEMS if i[0] in value]


def status(maintenance: list[dict], hours_now: float | None, today: date) -> list[dict]:
    """Per item: its last time (the newest entry that ticks it), when it is due next and how far off that is.
    state: "due" (overdue or due now), "soon" (within 10 % of the interval, at least 10 h or 7 days), "never" (no entry
    ticks it yet), "ok"."""
    out = []
    for iid, system, name, hours, months, action, dealer, note in ITEMS:
        done = [e for e in maintenance if iid in (e.get("items") or [])]
        last = max(done, key=lambda e: (e["date"], e.get("engine_hours") or 0), default=None)
        r = {"id": iid, "system": system, "name": name, "hours": hours, "months": months, "action": action, "dealer": dealer, "note": note,
             "last_date": last["date"] if last else None, "last_hours": last.get("engine_hours") if last else None,
             "due_hours": None, "due_date": None, "left_hours": None, "left_days": None, "state": "never"}
        if last:
            states = []
            if hours and r["last_hours"] is not None:
                r["due_hours"] = round(r["last_hours"] + hours, 1)
                if hours_now is not None:
                    r["left_hours"] = round(r["due_hours"] - hours_now, 1)
                    states.append("due" if r["left_hours"] <= 0 else "soon" if r["left_hours"] <= max(10, hours * .1) else "ok")
            if months:
                due = add_months(date.fromisoformat(last["date"]), months)
                r["due_date"], r["left_days"] = due.isoformat(), (due - today).days
                states.append("due" if r["left_days"] <= 0 else "soon" if r["left_days"] <= max(7, months * 3) else "ok")
            r["state"] = "due" if "due" in states else "soon" if "soon" in states else "ok"
        out.append(r)
    return out
