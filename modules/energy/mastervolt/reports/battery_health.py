#!/usr/bin/env python3
"""Battery health report from the MasterVolt measurement history (read-only).

Reads data/history.sqlite3 (opened read-only, safe while the server runs) and the BMS control
backups, and writes a Markdown report: per-battery verdict, cell resistance signature, current
sharing, cell/voltage exposure, alarms, connection reliability, balancers, Start/Bow batteries
and usage.

    py battery_health.py --project C:\\Temp\\mastervoltproject
    py battery_health.py --project C:\\Temp\\mastervoltproject --days 7 --save
    py battery_health.py --project C:\\Temp\\mastervoltproject --split "2026-09-20 12:40"

--split compares the periods before and after a moment you changed something (for example
after re-tightening a busbar). Times are local. Only the standard library is used.

The verdict thresholds below are practical heuristics tuned on this installation, not
manufacturer limits. Treat ATTENTION/CRITICAL as "go and look", not as a diagnosis.
"""
import argparse
import bisect
import json
import sqlite3
import statistics as st
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # mastervolt/reports/battery_health.py -> the project folder

# ---- heuristics -----------------------------------------------------------------------
CELL_HIGH_MV = 3650          # LiFePO4 absolute charge limit per cell
CELL_LOW_MV = 3000
MIN_STEP_A = 2.0             # smallest load step (between consecutive samples) used for resistance
MIN_STEPS = 15               # load steps needed before a resistance figure is reported
PLATEAU_SOC = (30, 90)       # flat part of the LiFePO4 curve; excludes the end-of-charge knee
REST_A = 0.5
R_ATTENTION_MOHM = 1.0       # excess resistance of the worst cell vs the other cells (healthy pack: 0.3-0.5)
R_CRITICAL_MOHM = 5.0
SHARE_TOLERANCE = 0.25       # +/- of the fair share before a battery is flagged
REST_SPREAD_MEDIAN_MV = 10
REST_SPREAD_P95_MV = 50
TEMP_ATTENTION_C = 45
GAP_SECONDS = 300
MIN_SAMPLES = 40


# ---- helpers --------------------------------------------------------------------------
def local(ts):
    return datetime.fromtimestamp(ts)


def fmt(ts):
    return local(ts).strftime("%d-%m %H:%M")


def median(xs):
    xs = list(xs)
    return st.median(xs) if xs else None


def pctl(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * (len(xs) - 1)))] if xs else None


def num(x, nd=1, unit=""):
    return "–" if x is None else f"{x:.{nd}f}{unit}"


def table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return out


def parse_local(s):
    return datetime.fromisoformat(s).timestamp()


# ---- loading --------------------------------------------------------------------------
def open_ro(db_path):
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=30)


def load_history(db_path, since_ts=None):
    con = open_ro(db_path)
    since = datetime.fromtimestamp(since_ts, timezone.utc).isoformat() if since_ts else ""
    data = {"bms": defaultdict(list), "bal": defaultdict(list), "dash": []}
    ts = lambda s: datetime.fromisoformat(s).timestamp()
    q = "select device, captured_at, payload from measurements where source=? and captured_at>=? order by captured_at"
    for dev, cap, payload in con.execute(q, ("bms", since)):
        d = json.loads(payload)
        data["bms"][dev].append({
            "t": ts(d.get("captured_at") or cap), "state": d.get("state"), "i": d.get("current_a"),
            "soc": d.get("state_of_charge_percent"), "rem": d.get("remaining_capacity_ah"),
            "temp": (d.get("temperatures_c") or [None])[0], "cells": d.get("cells_mv"),
            "spread": d.get("cell_spread_mv"), "chg": d.get("charge_mosfet_on"), "dis": d.get("discharge_mosfet_on"),
            "alarms": d.get("alarms") or [], "cycles": d.get("cycles")})
    for dev, cap, payload in con.execute(q, ("balancer", since)):
        d = json.loads(payload)
        s = d.get("status") or {}
        data["bal"][dev].append({
            "t": ts(cap), "state": d.get("state"), "active": s.get("balance_active"), "cells": s.get("cells_mv"),
            "delta": s.get("cell_delta_mv"), "temp": (s.get("temperatures_c") or [None])[0],
            "cur": s.get("reported_current_a"), "alarms": s.get("alarms") or []})
    q2 = "select captured_at, payload from measurements where source='dashboard' and captured_at>=? order by captured_at"
    for cap, payload in con.execute(q2, (since,)):
        d = json.loads(payload)
        stg = d.get("storage") or {}
        h, s_, b = stg.get("house") or {}, stg.get("start") or {}, stg.get("bow") or {}
        data["dash"].append({"t": ts(cap), "h_i": h.get("current"), "h_soc": h.get("soc"), "h_temp": h.get("temperature"),
                             "s_v": s_.get("voltage"), "s_i": s_.get("current"), "s_soc": s_.get("soc"),
                             "b_v": b.get("voltage"), "b_i": b.get("current"), "b_soc": b.get("soc")})
    ok = con.execute("select min(captured_at), max(captured_at), count(*) from measurements").fetchone()
    con.close()
    data["db_range"] = ok
    return data


def load_backups(folder):
    out = []
    if folder and Path(folder).is_dir():
        for f in Path(folder).glob("*.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                out.append({"t": datetime.fromisoformat(d["captured_at"]).timestamp(), "bat": d.get("battery"), "cycles": d.get("cycles")})
            except Exception:
                pass
    return sorted(out, key=lambda b: b["t"])


# ---- per-sample helpers ---------------------------------------------------------------
def good(rows):
    out = [r for r in rows if r["state"] == "connected" and isinstance(r["cells"], list) and len(r["cells"]) >= 2
           and all(isinstance(c, (int, float)) for c in r["cells"]) and isinstance(r["i"], (int, float))]
    if not out:
        return out
    n = Counter(len(r["cells"]) for r in out).most_common(1)[0][0]
    return [r for r in out if len(r["cells"]) == n]


def dev(r, k):
    others = [c for j, c in enumerate(r["cells"]) if j != k]
    return r["cells"][k] - sum(others) / len(others)


def in_soc(r, lo, hi):
    return isinstance(r["soc"], (int, float)) and lo <= r["soc"] <= hi


def window(rows, a=None, b=None):
    return [r for r in rows if (a is None or r["t"] >= a) and (b is None or r["t"] < b)]


# ---- metrics --------------------------------------------------------------------------
def excess_resistance(rs):
    """mOhm per cell: how much more each cell moves with current than the mean of the other cells.
    A cell (or its busbar/sense lead) with a bad connection stands out with a large positive value."""
    if not rs:
        return None
    n = len(rs[0]["cells"])
    # Use load steps between consecutive samples: the change in each cell's deviation divided by the
    # change in current. Differences cancel static offsets (a cell the balancer keeps bleeding, sensor
    # offsets) and slow drift, so only the dynamic, resistive response remains.
    steps = []
    for a, b in zip(rs, rs[1:]):
        if b["t"] - a["t"] > 60 or a["alarms"] or b["alarms"]:
            continue
        if (a["chg"], a["dis"]) != (b["chg"], b["dis"]):
            continue                                   # a MOSFET switched: not a plain load step
        if not (in_soc(a, *PLATEAU_SOC) and in_soc(b, *PLATEAU_SOC)):
            continue
        di = b["i"] - a["i"]
        if abs(di) >= MIN_STEP_A:
            steps.append((di, [dev(b, k) - dev(a, k) for k in range(n)]))
    if len(steps) < MIN_STEPS:
        return None
    den = sum(di * di for di, _ in steps)
    slopes = [sum(di * d[k] for di, d in steps) / den for k in range(n)]
    worst = max(range(n), key=lambda k: slopes[k])
    return {"slopes": slopes, "worst": worst + 1, "worst_mohm": slopes[worst], "n": len(steps)}


def current_shares(rows_by, min_bank=8.0, tol=12.0):
    """Per-sample share of the bank current carried by each battery (all read within `tol` seconds)."""
    names = sorted(rows_by)
    data = {n: sorted((r["t"], r["i"]) for r in good(rows_by[n])) for n in names}
    if not names or any(not v for v in data.values()):
        return []
    ref = max(names, key=lambda n: len(data[n]))
    keys = {n: [t for t, _ in data[n]] for n in names}
    out = []
    for t, i in data[ref]:
        cur = {ref: i}
        for n in names:
            if n == ref:
                continue
            j = bisect.bisect_left(keys[n], t)
            c = [x for x in (j - 1, j) if 0 <= x < len(keys[n])]
            x = min(c, key=lambda x: abs(keys[n][x] - t))
            if abs(keys[n][x] - t) > tol:
                break
            cur[n] = data[n][x][1]
        else:
            tot = sum(cur.values())
            if abs(tot) >= min_bank:
                out.append((t, {n: v / tot for n, v in cur.items()}))
    return out


def share_median(samples):
    if len(samples) < 10:
        return {}
    names = samples[0][1].keys()
    return {n: median(s[n] for _, s in samples) for n in names}


def episodes(rows, pred):
    out, cur = [], None
    for r in rows:
        if pred(r):
            if cur is None:
                cur = {"s": r["t"], "e": r["t"], "first": r}
            else:
                cur["e"] = r["t"]
        elif cur:
            out.append(cur)
            cur = None
    if cur:
        out.append(cur)
    return out


def own_gaps(name, rows_by):
    t = [r["t"] for r in good(rows_by[name])]
    others = sorted(r["t"] for n, rs in rows_by.items() if n != name for r in good(rs))
    gaps = []
    for a, b in zip(t, t[1:]):
        if b - a > GAP_SECONDS:
            j = bisect.bisect_right(others, a)
            if j < len(others) and others[j] < b:
                gaps.append((a, b))
    return gaps


def battery_metrics(name, rows, rows_by_window, shares):
    g = good(rows)
    m = {"n": len(g)}
    if not g:
        return m
    cells = [c for r in g for c in r["cells"]]
    rest = [r for r in g if abs(r["i"]) < REST_A and in_soc(r, 20, 90)]
    spreads = [(r["spread"] if isinstance(r["spread"], (int, float)) else max(r["cells"]) - min(r["cells"])) for r in rest]
    m.update({
        "excess": excess_resistance(g), "max_cell": max(cells), "min_cell": min(cells),
        "over": sum(1 for r in g if max(r["cells"]) > CELL_HIGH_MV), "under": sum(1 for r in g if min(r["cells"]) < CELL_LOW_MV),
        "alarm_samples": sum(1 for r in g if r["alarms"]), "alarm_types": Counter(a for r in g for a in r["alarms"]),
        "rest_median": median(spreads), "rest_p95": pctl(spreads, .95), "rest_n": len(spreads),
        "temps": [r["temp"] for r in g if isinstance(r["temp"], (int, float))],
        "soc": [r["soc"] for r in g if isinstance(r["soc"], (int, float))], "cur": [r["i"] for r in g],
        "share": share_median(shares).get(name) if shares else None,
        "gaps": own_gaps(name, rows_by_window) if rows_by_window else []})
    return m


def verdict(m, fair):
    flags = []
    if m.get("n", 0) < MIN_SAMPLES:
        return "NO DATA", [("info", "too few samples in this window")]
    ex = m["excess"]
    if ex:
        if ex["worst_mohm"] >= R_CRITICAL_MOHM:
            flags.append(("critical", f"cell {ex['worst']} shows {ex['worst_mohm']:.1f} mΩ excess resistance (loose/dirty busbar or sense lead, or a failing cell)"))
        elif ex["worst_mohm"] >= R_ATTENTION_MOHM:
            flags.append(("attention", f"cell {ex['worst']} shows {ex['worst_mohm']:.1f} mΩ excess resistance – check its busbar/sense-lead connections"))
    if m["over"]:
        flags.append(("critical", f"{m['over']} sample(s) with a cell above {CELL_HIGH_MV} mV (max {m['max_cell']} mV)"))
    if m["under"]:
        flags.append(("attention", f"{m['under']} sample(s) with a cell below {CELL_LOW_MV} mV (min {m['min_cell']} mV)"))
    if m["alarm_samples"]:
        flags.append(("attention", f"{m['alarm_samples']} sample(s) with an active BMS alarm: {', '.join(m['alarm_types'])}"))
    sh = m.get("share")
    if sh is not None and fair and not (fair * (1 - SHARE_TOLERANCE) <= sh <= fair * (1 + SHARE_TOLERANCE)):
        flags.append(("attention", f"carries {sh*100:.0f}% of the bank current (fair share {fair*100:.0f}%) – its connection resistance differs from the others"))
    if m["rest_median"] is not None and (m["rest_median"] > REST_SPREAD_MEDIAN_MV or (m["rest_p95"] or 0) > REST_SPREAD_P95_MV):
        flags.append(("attention", f"cell spread at rest median {m['rest_median']:.0f} mV / p95 {m['rest_p95']:.0f} mV (imbalance)"))
    if m["temps"] and max(m["temps"]) >= TEMP_ATTENTION_C:
        flags.append(("attention", f"temperature reached {max(m['temps']):.0f} °C"))
    if m["gaps"]:
        lost = sum(b - a for a, b in m["gaps"]) / 3600
        flags.append(("info", f"{len(m['gaps'])} battery-specific Bluetooth gap(s), {lost:.1f} h without data"))
    status = "CRITICAL" if any(f[0] == "critical" for f in flags) else "ATTENTION" if any(f[0] == "attention" for f in flags) else "OK"
    return status, flags


# ---- analysis of one window -----------------------------------------------------------
def analyse_window(data, a=None, b=None):
    rows_by = {n: window(rs, a, b) for n, rs in sorted(data["bms"].items())}
    shares = current_shares(rows_by)
    fair = 1 / len(rows_by) if rows_by else None
    metrics = {n: battery_metrics(n, rs, rows_by, shares) for n, rs in rows_by.items()}
    return {"rows_by": rows_by, "shares": shares, "fair": fair, "metrics": metrics,
            "verdicts": {n: verdict(m, fair) for n, m in metrics.items()}}


# ---- report ---------------------------------------------------------------------------
ICON = {"OK": "OK", "ATTENTION": "ATTENTION", "CRITICAL": "CRITICAL", "NO DATA": "no data"}


def report(data, backups, args):
    now = max([r["t"] for rs in data["bms"].values() for r in rs] or [0])
    first = min([r["t"] for rs in data["bms"].values() for r in rs] or [0])
    L = []
    L.append("# Battery health report")
    L.append("")
    L.append(f"Generated {datetime.now():%d-%m-%Y %H:%M} (local time). Data: {fmt(first)} → {fmt(now)} "
             f"({(now - first) / 86400:.1f} days), {sum(len(v) for v in data['bms'].values())} BMS records, "
             f"{sum(len(v) for v in data['bal'].values())} balancer records, {len(data['dash'])} dashboard records.")
    if not data["bms"]:
        return "\n".join(L + ["", "No BMS data found."])
    # With --split the "recent" window is everything after that moment (the state you want to judge).
    recent_a = args.split_ts if args.split_ts else now - args.recent_hours * 3600
    recent_label = f"since {fmt(args.split_ts)}" if args.split_ts else f"last {args.recent_hours:g} h"
    full, recent = analyse_window(data), analyse_window(data, recent_a)
    names = sorted(full["metrics"])
    manual = sorted(b["t"] for b in backups)

    # -- summary
    L += ["", "## Verdict", "", f"Status uses the period \"{recent_label}\" when there is enough data, otherwise the whole period."]
    rows = []
    for n in names:
        use = recent if recent["metrics"][n].get("n", 0) >= MIN_SAMPLES else full
        status, flags = use["verdicts"][n]
        fl = [f for f in flags if f[0] != "info"] or flags
        rows.append((n, f"**{ICON[status]}**", recent_label if use is recent else "whole period", "; ".join(f[1] for f in fl) or "no issues found"))
    L += table(["Battery", "Status", "Based on", "Findings"], rows)
    hist = []
    for n in names:
        fs = full["verdicts"][n][1]
        hist.append(f"- **{n}**, whole period: " + ("; ".join(f[1] for f in fs if f[0] != 'info') or "no issues"))
    L += ["", "Over the whole period:", ""] + hist

    # -- cell resistance
    L += ["", "## Cell connection / resistance signature", "",
          "Excess resistance in mΩ of each cell compared with the mean of the other cells of the same battery, from load steps between "
          f"consecutive samples (change in current ≥ {MIN_STEP_A:g} A, SOC {PLATEAU_SOC[0]}–{PLATEAU_SOC[1]}%, no alarm, no MOSFET change; "
          f"at least {MIN_STEPS} steps). A healthy pack is within ±1 mΩ; one cell far above the rest points to "
          "a loose or corroded connection at that cell (or a failing cell). \"Samples\" below counts load steps."]
    ncell = max((len(m["excess"]["slopes"]) for res in (full, recent) for m in res["metrics"].values() if m.get("excess")), default=4)
    rows = []
    for n in names:
        for lab, res in (("whole period", full), (recent_label, recent)):
            ex = res["metrics"][n].get("excess")
            if ex:
                rows.append((n, lab, ex["n"], *[f"{s:+.1f}" for s in ex["slopes"]], f"cell {ex['worst']}: {ex['worst_mohm']:+.1f}"))
            else:
                rows.append((n, lab, "–", *["–"] * ncell, "–"))
    L += table(["Battery", "Window", "Samples"] + [f"Cell {k + 1}" for k in range(ncell)] + ["Worst"], rows)
    # daily trend
    days = defaultdict(lambda: defaultdict(list))
    for n in names:
        for r in good(full["rows_by"][n]):
            days[local(r["t"]).strftime("%d-%m")][n].append(r)
    trend = []
    for d in sorted(days, key=lambda s: (s[3:], s[:2])):
        cells = []
        for n in names:
            ex = excess_resistance(days[d][n]) if days[d][n] else None
            cells.append(f"cell {ex['worst']} {ex['worst_mohm']:+.1f}" if ex else "–")
        trend.append((d, *cells))
    L += ["", "Worst cell per day (mΩ):", ""] + table(["Day"] + names, trend)

    # -- current sharing
    L += ["", "## Current sharing between the parallel batteries", "",
          f"Median share of the bank current per battery when the bank carries ≥ 8 A (fair share {full['fair']*100:.0f}%). A battery with a worse connection carries less."]
    perday = defaultdict(list)
    for t, s in full["shares"]:
        perday[local(t).strftime("%d-%m")].append((t, s))
    rows = []
    for d in sorted(perday, key=lambda s: (s[3:], s[:2])):
        sm = share_median(perday[d])
        rows.append((d, len(perday[d])) + tuple(f"{sm[n]*100:.0f}%" if n in sm else "–" for n in names))
    tot = share_median(full["shares"])
    rows.append(("**all**", len(full["shares"])) + tuple(f"{tot[n]*100:.0f}%" if n in tot else "–" for n in names))
    L += table(["Day", "Samples"] + names, rows)

    # -- cells / voltage / alarms
    L += ["", "## Cells, voltage and alarms (whole period)", ""]
    rows = []
    for n in names:
        m = full["metrics"][n]
        if not m.get("n"):
            continue
        rows.append((n, m["n"], f"{m['min_cell']}–{m['max_cell']}", m["over"], m["under"], num(m["rest_median"], 0), num(m["rest_p95"], 0),
                     f"{min(m['soc']):.0f}–{max(m['soc']):.0f}" if m["soc"] else "–", f"{min(m['temps']):.0f}–{max(m['temps']):.0f}" if m["temps"] else "–",
                     f"{min(m['cur']):+.0f} / {max(m['cur']):+.0f}", m["alarm_samples"]))
    L += table(["Battery", "Samples", "Cell mV min–max", f">{CELL_HIGH_MV}", f"<{CELL_LOW_MV}", "Rest spread median mV", "p95", "SOC %", "Temp °C", "Current A min / max", "Alarm samples"], rows)
    for n in names:
        eps = episodes(good(full["rows_by"][n]), lambda r: bool(r["alarms"]))
        if eps:
            L += ["", f"**{n} alarm episodes** ({len(eps)}):", ""]
            for e in eps[:15]:
                r = e["first"]
                L.append(f"- {fmt(e['s'])}–{fmt(e['e'])}: {', '.join(r['alarms'])} | cells {r['cells']} mV, I {r['i']:+.1f} A, SOC {r['soc']}")
            if len(eps) > 15:
                L.append(f"- … and {len(eps) - 15} more")
    L += ["", "MOSFET-off episodes (a charge/discharge MOSFET reported OFF). Episodes within minutes of a manual-control backup are your own switching, not BMS protection:", ""]
    rows = []
    for n in names:
        g = good(full["rows_by"][n])
        for lab, key in (("charge", "chg"), ("discharge", "dis")):
            eps = episodes(g, lambda r, key=key: r[key] is False)
            man = sum(1 for e in eps if any(e["s"] - 180 <= t <= e["e"] + 60 for t in manual))
            prot = sum(1 for e in eps if e["first"]["alarms"])
            rows.append((n, lab, len(eps), man, prot))
    L += table(["Battery", "MOSFET", "Episodes", "Manual", "With alarm active"], rows)

    # -- reliability, SOC, cycles
    L += ["", "## Reliability, SOC consistency and cycles", ""]
    rows = []
    for n in names:
        g = good(full["rows_by"][n])
        if len(g) < 2:
            continue
        dts = [b["t"] - a["t"] for a, b in zip(g, g[1:]) if b["t"] - a["t"] <= GAP_SECONDS]
        gaps = own_gaps(n, full["rows_by"])
        jumps = [(b["t"], a["soc"], b["soc"]) for a, b in zip(g, g[1:]) if b["t"] - a["t"] <= 60 and isinstance(a["soc"], (int, float)) and isinstance(b["soc"], (int, float)) and abs(b["soc"] - a["soc"]) > 3]
        cy = [r["cycles"] for r in g if isinstance(r["cycles"], int)]
        bk = [b for b in backups if b["bat"] == n and isinstance(b["cycles"], int)]
        firsts = ([(bk[0]["t"], bk[0]["cycles"])] if bk else []) + ([(g[0]["t"], cy[0])] if cy else [])
        c0 = min(firsts, key=lambda x: x[0]) if firsts else None
        c1 = (g[-1]["t"], cy[-1]) if cy else None
        rows.append((n, f"{median(dts) or 0:.0f} s", len(gaps), f"{sum(b - a for a, b in gaps) / 3600:.1f} h", len(jumps),
                     f"{c0[1]} ({fmt(c0[0])}) → {c1[1]} ({fmt(c1[0])})" if c0 and c1 else "–"))
    L += table(["Battery", "Median interval", "Battery-specific gaps", "Time lost", "SOC jumps >3 pts", "Cycle counter"], rows)
    L += ["", "SOC jumps are manual SOC writes or BMS full/empty recalibrations; after many of them, SOC-based conclusions are unreliable."]

    # -- before / after
    if args.split_ts:
        before, after = analyse_window(data, None, args.split_ts), analyse_window(data, args.split_ts)
        L += ["", f"## Before / after {fmt(args.split_ts)}", ""]
        rows = []
        for n in names:
            for lab, res in (("before", before), ("after", after)):
                m = res["metrics"][n]
                if not m.get("n"):
                    rows.append((n, lab, 0, "–", "–", "–", "–", "–", "–"))
                    continue
                ex = m["excess"]
                sh = m["share"]
                rows.append((n, lab, m["n"], f"cell {ex['worst']}: {ex['worst_mohm']:+.1f}" if ex else "–", f"{sh*100:.0f}%" if sh is not None else "–",
                             num(m["rest_median"], 0), m["alarm_samples"], f"{m['min_cell']}–{m['max_cell']}", ICON[res['verdicts'][n][0]]))
        L += table(["Battery", "Period", "Samples", "Worst-cell excess mΩ", "Current share", "Rest spread median mV", "Alarm samples", "Cell mV", "Verdict"], rows)

    # -- balancers
    L += ["", "## Balancers (independent cell sensing)", ""]
    if data["bal"]:
        rows = []
        for n, rs in sorted(data["bal"].items()):
            ok = [r for r in rs if r["state"] == "connected" and isinstance(r["cells"], list) and r["cells"]]
            if not ok:
                continue
            dl = [r["delta"] for r in ok if r["delta"] is not None]
            tp = [r["temp"] for r in ok if r["temp"] is not None]
            act = [r["temp"] for r in ok if r["active"] and r["temp"] is not None]
            rows.append((n, len(ok), f"{sum(1 for r in ok if r['active']) / len(ok) * 100:.0f}%", num(median(dl), 0), num(pctl(dl, .95), 0), max(dl) if dl else "–",
                         num(median(tp), 0), num(median(act), 0) if act else "–", max(tp) if tp else "–", sum(1 for r in ok if r["alarms"])))
        L += table(["Balancer", "Reads", "Balancing", "Cell delta median mV", "p95", "max", "Temp median °C", "Temp while balancing", "Temp peak", "Alarm reads"], rows)
    else:
        L.append("No balancer data.")

    # -- start / bow
    L += ["", "## Start and Bow batteries (MasterShunt)", ""]
    rows = []
    for pre, nm in (("s", "Start"), ("b", "Bow")):
        d = [x for x in data["dash"] if isinstance(x[pre + "_v"], (int, float))]
        if not d:
            continue
        rest = [x[pre + "_v"] for x in d if isinstance(x[pre + "_i"], (int, float)) and abs(x[pre + "_i"]) < 0.1]
        soc = [x[pre + "_soc"] for x in d if isinstance(x[pre + "_soc"], (int, float))]
        cur = [x[pre + "_i"] for x in d if isinstance(x[pre + "_i"], (int, float))]
        rows.append((nm, len(d), f"{min(x[pre + '_v'] for x in d):.2f}–{max(x[pre + '_v'] for x in d):.2f}", num(median(rest), 2), f"{min(soc):.0f}" if soc else "–", f"{min(cur):+.1f} / {max(cur):+.1f}" if cur else "–"))
    L += table(["Battery", "Samples", "Voltage min–max", "Rest voltage median", "SOC min %", "Current A min / max"], rows) if rows else ["No data."]
    L.append("")
    L.append("Sampling is every ~10 s, so short events such as starter cranking are not captured.")

    # -- usage
    L += ["", "## House bank usage", ""]
    h = [x for x in data["dash"] if isinstance(x["h_i"], (int, float))]
    caps = []
    for n in names:
        r = [x["rem"] / (x["soc"] / 100) for x in data["bms"][n] if isinstance(x["rem"], (int, float)) and isinstance(x["soc"], (int, float)) and x["soc"] > 5]
        if r:
            caps.append(median(r))
    if len(h) > 2:
        ah_in = ah_out = cov = 0.0
        for a, b in zip(h, h[1:]):
            dt = b["t"] - a["t"]
            if dt <= 120:
                x = (a["h_i"] + b["h_i"]) / 2 * dt / 3600
                ah_in += max(x, 0)
                ah_out += max(-x, 0)
                cov += dt
        cov_d = cov / 86400
        cap = sum(caps) if caps else None
        socs = [x["h_soc"] for x in h if isinstance(x["h_soc"], (int, float))]
        L.append(f"- Observed {cov_d:.1f} days: charged {ah_in:.0f} Ah, discharged {ah_out:.0f} Ah, average load {ah_out / max(cov_d * 24, 1e-9):.1f} A.")
        if cap:
            L.append(f"- Bank capacity as configured in the BMSs: {cap:.0f} Ah → {ah_out / cap:.2f} equivalent full cycles ({ah_out / cap / max(cov_d, 1e-9):.2f} per day).")
        if socs:
            L.append(f"- House SOC (DALY average) {min(socs):.0f}–{max(socs):.0f}%; ≥ 95% for {sum(s >= 95 for s in socs) / len(socs) * 100:.0f}% of the time, < 60% for {sum(s < 60 for s in socs) / len(socs) * 100:.0f}%.")
    else:
        L.append("No dashboard data.")

    L += ["", "## Notes and limits", "",
          "- The BMS SOC is coulomb-counted against a configured capacity, so it cannot reveal capacity loss; the dashboard House SOC is that same DALY average, not an independent measurement.",
          "- Real capacity needs a controlled full discharge (known load, shunt and BMS logged). Shunt zero offset and manual SOC writes make Ah-vs-SOC comparisons unreliable.",
          "- Resistance figures are relative (cell vs its own pack), so they detect bad connections and weak cells, not absolute internal resistance.",
          "- Cell readings are 1 mV / ~30 s samples; brief transients are missed.",
          "- History is kept for the retention period set in Settings; rerun periodically and compare (`--split`) to see trends."]
    return "\n".join(L) + "\n"


# ---- CLI ------------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="Battery health report from the MasterVolt history (read-only).")
    ap.add_argument("--project", default=str(PROJECT_ROOT), help="folder containing data/history.sqlite3 and backups/ (default: the project folder)")
    ap.add_argument("--db", help="history database (default: <project>/data/history.sqlite3)")
    ap.add_argument("--backups", help="BMS control backups folder (default: <project>/backups)")
    ap.add_argument("--days", type=float, help="only use the last N days")
    ap.add_argument("--recent-hours", type=float, default=48, help="window for the current-status verdict (default 48)")
    ap.add_argument("--split", help="local time 'YYYY-MM-DD HH:MM' to compare before/after (e.g. when you re-tightened a connection)")
    ap.add_argument("--save", action="store_true", help="also write reports/battery_health_<timestamp>.md")
    ap.add_argument("--out", help="write the report to this file instead of printing")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    proj = Path(args.project)
    db = Path(args.db) if args.db else proj / "data" / "history.sqlite3"
    if not db.exists():
        sys.exit(f"History database not found: {db}\nUse --project <live folder> or --db <file>.")
    args.split_ts = parse_local(args.split) if args.split else None
    since = datetime.now().timestamp() - args.days * 86400 if args.days else None
    data = load_history(db, since)
    text = report(data, load_backups(Path(args.backups) if args.backups else proj / "backups"), args)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"Report written to {args.out}")
    else:
        print(text)
    if args.save:
        folder = proj / "reports"
        folder.mkdir(exist_ok=True)
        path = folder / f"battery_health_{datetime.now():%Y%m%d_%H%M}.md"
        path.write_text(text, encoding="utf-8")
        print(f"Saved {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
