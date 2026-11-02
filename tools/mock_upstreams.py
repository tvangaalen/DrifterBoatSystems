"""Fake module servers with made-up data, for developing and testing the Drifter page without the boat.

Never point this at, or run it instead of, the real servers: it only simulates. Commands change the fake state so
the page's controls can be tried. Positions are a made-up spot, not an anchorage of this boat.
Usage: py tools/mock_upstreams.py  (ports 18000 power, 18766 anchor, 18095 guard, 18080 washer, localhost only)
"""
from __future__ import annotations

import json, math, os, random, sys, threading, time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAT0, LON0 = 50.0, -30.0          # mid-Atlantic: obviously not a real anchorage
T0 = time.time()


def wobble(a, b, period=40.0):
    return a + (b - a) * (0.5 + 0.5 * math.sin((time.time() - T0) / period))


class Power:
    def __init__(self):
        self.c = {"inverter": 0.0, "charger": 1.0, "support": 0.0, "limit": 10.0, "alt": False,
                  "dev": {"solar": True, "charger_start": True, "charger_bow": False, "engine_ecu": True}}
        self.mos = {n: {"c": True, "d": True} for n in (1, 2, 3)}
        self.settings = {"default_ac_limit": 10, "float_protection_enabled": True, "float_cell_trigger_mv": 3550.0, "float_cell_resume_mv": 3375.0,
                         "bms_refresh_interval": 30, "bms_popup_seconds": 5, "bms_connection_retry_seconds": 5, "balancer_refresh_interval": 60,
                         "balancer_connection_retry_seconds": 30, "history_retention_days": 31}   # the v2 settings table
        self.active_mode = None; self.report = {"state": "idle", "days": None, "started_at": None, "finished_at": None, "duration_seconds": None, "markdown": None, "error": None}

    def energy(self):
        solar = wobble(80, 420); soc = wobble(71, 74, 300); hv = 13.1 + soc / 1000
        dc = lambda label, w, v=13.2, **k: {"label": label, "kind": "DC", "voltage": v, "current": w / v, "power": w, **k}
        loads = {"house_ac": {"label": "AC Loads", "kind": "AC", "voltage": 230.0, "current": 0.4, "power": 92.0, "output_frequency": 50.0},
                 "inverter": dc("Inverter", 0.0, inverting=False, supporting=False, enabled=self.c["inverter"] >= .5),
                 "charger_start": dc("Charger Start", 6.0, charge_state="Float"), "charger_bow": dc("Charger Bow", 0.0, charge_state="Off"),
                 "engine_ecu": dc("Engine ECU power", 4.2), "alternator_field": dc("Alternator", 0.0, state="Stop Charge"),
                 "other_dc": dc("Other DC Loads", wobble(60, 140, 17), estimated=False)}
        total = sum(x["power"] for x in loads.values() if x["kind"] == "DC"); batt_w = solar - total
        return {
            "sources": {"shore": {"label": "Shore Power", "kind": "AC", "voltage": 0.0, "current": 0.0, "power": 0.0, "input_frequency": None, "connected": False},
                        "charger_house": dc("Charger House", 0.0, charge_state="Off"),
                        "alternator": {**dc("Alternator", 0.0, 13.9), "running": False, "shaft_running": False, "estimated": False, "state": "Stop Charge", "control_on": self.c["alt"]},
                        "solar": {**dc("Solar", solar, hv), "panel_voltage": 38.4, "state": "Bulk"}},
            "storage": {"house": {"label": "House Battery", "soc": round(soc, 1), "voltage": hv, "current": batt_w / hv, "power": batt_w, "temperature": 21.5,
                                  "battery_type": "MLI", "capacity": 960.0, "capacity_unit": "Ah", "soc_source": "daly_bms_average", "soc_age_seconds": 12, "max_cell_mv": 3341, "max_cell_battery": "BATTERY 1",
                                  "max_spread_mv": 18, "max_spread_battery": "BATTERY 1"},
                        "start": {"label": "Start Battery", "soc": None, "voltage": 13.4, "current": 0.4, "power": 5.4, "battery_type": "AGM", "capacity": 110.0, "capacity_unit": "Ah"},
                        "bow": {"label": "Bow Battery", "soc": None, "voltage": 12.9, "current": 0.0, "power": 0.0, "battery_type": "AGM", "capacity": 70.0, "capacity_unit": "Ah"}},
            "consumers": loads, "totals": {"dc_input_power": solar, "consumer_power": total, "ac_consumer_power": 92.0},
            "settings": self.settings,
            "high_soc_float_policy": {"enabled": self.settings["float_protection_enabled"], "cell_trigger_mv": self.settings["float_cell_trigger_mv"],
                                      "cell_resume_mv": self.settings["float_cell_resume_mv"], "active": False, "trigger": None, "max_cell_mv": 3341,
                                      "float_latched": False, "last_check_at": time.time()},
            "active_mode": self.active_mode,
            "combimaster": {"inverter_enabled": self.c["inverter"], "charger_enabled": self.c["charger"], "ac_input_limit": self.c["limit"],
                            "ac_support_enabled": self.c["support"], "inverting": 0.0, "charging": 0.0, "supporting": 0.0, "ac_input_present": 0.0, "alarms": 0.0},
            "controls": {k: {"verified": True, "current": v} for k, v in self.c["dev"].items()},
        }

    def bms(self):
        bats = {}
        for n in (1, 2, 3):
            cells = [3330 + random.randint(-6, 6) + (12 if (n == 1 and i == 2) else 0) for i in range(4)]
            bats[f"BATTERY {n}"] = {"state": "connected", "battery": f"BATTERY {n}", "captured_at": datetime.utcnow().isoformat() + "+00:00",
                                    "pack_voltage_v": sum(cells) / 1000, "current_a": wobble(-4, 8) / 3, "state_of_charge_percent": wobble(70, 75, 300) + n,
                                    "remaining_capacity_ah": 210.0 + n, "temperatures_c": [20 + n], "cells_mv": cells, "cell_spread_mv": max(cells) - min(cells),
                                    "charge_mosfet_on": self.mos[n]["c"], "discharge_mosfet_on": self.mos[n]["d"], "balancing_cells": [3] if n == 1 else [],
                                    "alarms": [], "cycles": 40 + n, "error": None}
        return {"busy": False, "control_status": {"busy": False, "phase": "idle", "message": ""}, "batteries": bats, "connected_count": 3,
                "refresh_interval_seconds": self.settings["bms_refresh_interval"]}

    def balancers(self):
        return {"devices": {f"DL-BAL{n}": {"name": f"DL-BAL{n}", "state": "connected", "stale": False, "error": None, "last_success_age_seconds": 20 + n,
                                           "values": [{"service": "00001800-0000-1000-8000-00805f9b34fb"}],   # v2: the GATT services, not readings
                                           "status": {"balance_active": n == 1, "balance_position": 3 if n == 1 else None, "pack_voltage_v": 13.33, "reported_current_a": 0.4 if n == 1 else 0.0,
                                                      "cells_mv": [3331, 3335, 3329 + n, 3333], "cell_delta_mv": 6 + n, "average_cell_mv": 3332, "temperatures_c": [22],
                                                      "alarms": [], "valid_frame_count": 6}} for n in (1, 2, 3)}}

    def chart_data(self, hours):
        """A made-up history sample in the shape of MasterVolt 2.x /api/history/chart-data."""
        now = time.time(); n = 400; dash, bms = [], []
        for i in range(n):
            t = now - hours * 3600 * (1 - i / (n - 1)); day = math.sin((t % 86400) / 86400 * 2 * math.pi - math.pi / 2)
            solar = max(0.0, 380 * day); alt = 600.0 if 0.30 < (i / n) % 0.5 < 0.36 else 0.0; ch = 0.0 if alt else (120.0 if (i // 40) % 3 == 0 else 0.0)
            iso = datetime.fromtimestamp(t).astimezone().isoformat()
            dash.append({"id": i, "captured_at": iso, "source_power": [ch, alt, solar], "source_current": [ch / 13.3, alt / 13.9, solar / 13.3],
                         "load_power": [0.0, 6.0, 0.0, 4.2, 9.0 if alt else 0.0, 80 + 40 * math.sin(i / 7)], "shore_power": ch * 1.1, "shore_connected": ch > 0})
            for b in (1, 2, 3):
                cur = (solar + alt + ch - 140) / 13.3 / 3 + (b - 2) * 0.4
                bms.append({"id": i * 3 + b, "captured_at": iso, "battery": f"BATTERY {b}", "voltage": 13.3, "current": round(cur, 1),
                            "remaining": 240 + 50 * math.sin(i / 60) + b * 3, "cell_spread": 8 + b * 3 + (6 if alt else 0)})
        cut = datetime.fromtimestamp(now - hours * 3600).astimezone().isoformat()
        return {"bms": bms, "dashboard": dash, "bms_count": len(bms), "dashboard_count": n, "latest": datetime.fromtimestamp(now).astimezone().isoformat(),
                "cutoff": cut, "zoom_hours": hours, "max_hours": 744.0, "server_cached": True}

    def contributions(self, start, end):
        span = max(1.0, (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()); k = span / 86400
        src = [("charger_house", 1164.2), ("alternator", 3417.4), ("solar", 1520.4)]; loads = [("inverter", 0.0), ("charger_start", 90.0), ("charger_bow", 103.4),
                                                                                               ("engine_ecu", 327.6), ("alternator_field", 152.9), ("other_dc", 2624.5)]
        e = lambda key, wh: {"key": key, "wh": wh * k, "avg_w": wh / 24}
        return {"start": start, "end": end, "span_seconds": span, "sources": [e(*x) for x in src], "shore": e("shore", 1978.3), "sources_covered_seconds": span * 0.97,
                "consumers": [e(*x) for x in loads], "consumers_covered_seconds": span * 0.97,
                "batteries": [{"key": f"BATTERY {b}", "charge_wh": 950 * k, "discharge_wh": 578 * k, "covered_seconds": span} for b in (1, 2, 3)]}

    def coordinator(self):
        return {"active": None, "active_for_seconds": None, "waiting": {"bms_control": 0, "bms_manual_read": 0, "bms": 0, "balancer": 0}, "connected_bms": 3,
                "refreshed_bms": 3, "bms_stable_seconds": 8600, "balancers_allowed": True, "degraded": False, "forced_releases": 0}

    def ble_events(self):
        now = time.time(); t = lambda s: datetime.fromtimestamp(now - s).astimezone().isoformat()
        dev = lambda ok: {"events": {"read_ok": 240}, "failures": {}, "consecutive_failures": 0 if ok else 3, "last_success_epoch": now - 20, "last_error": None if ok else "not found; retrying automatically",
                          "timings": {"connect": {"count": 1, "avg_ok_seconds": 4.9}, "radio_wait": {"count": 200, "p95_ok_seconds": 4.6}}, "signal": {"rssi": -71}}
        return {"counters": {"BATTERY 1": dev(True), "BATTERY 2": dev(True), "BATTERY 3": dev(True), "DL-BAL2": dev(False), "balancers": {}},
                "events": [{"time": t(300), "device": "DL-BAL2", "kind": "connect_failed", "detail": "RuntimeError: DL-BAL2 not found; retrying automatically"},
                           {"time": t(120), "device": "DL-BAL1", "kind": "slow_connect", "detail": "connected after 8.6 s"}]}

    def history_status(self):
        return {"file": "history.sqlite3", "size_bytes": 1768214528, "reusable_bytes": 19922944, "disk_free_bytes": 290960031744, "records": 541557,
                "oldest": "2026-10-01T22:40:20+00:00", "newest": datetime.now().astimezone().isoformat(), "span_days": 31.0, "retention_days": self.settings["history_retention_days"],
                "records_per_day": 17469.3, "projected_bytes_at_retention": 1748263719}

    def post(self, path, body):
        if path == "/api/control/inverter": self.c["inverter"] = 1.0 if body["enabled"] else 0.0
        elif path == "/api/control/charger": self.c["charger"] = 1.0 if body["enabled"] else 0.0
        elif path == "/api/control/ac-support": self.c["support"] = 1.0 if body["enabled"] else 0.0
        elif path == "/api/control/ac-limit":
            if not 3 <= body.get("amps", 0) <= 15: return 422, {"detail": "amps must be 3-15"}
            self.c["limit"] = float(body["amps"])
        elif path == "/api/control/alternator": self.c["alt"] = bool(body["enabled"])
        elif path.startswith("/api/control/device/"): self.c["dev"][path.rsplit("/", 1)[1]] = bool(body["enabled"])
        elif path == "/api/control/mode": time.sleep(1.5); self.active_mode = body["mode"]; return 200, {"mode": body["mode"], "ok": True, "actions": []}
        elif path == "/api/settings":
            missing = [k for k in self.settings if k not in body]
            if missing: return 422, {"detail": f"missing: {', '.join(missing)}"}       # like the v2 SettingsReq
            if body["float_cell_resume_mv"] > body["float_cell_trigger_mv"] - 30: return 400, {"detail": "Resume level must be at least 30 mV below the trigger"}
            self.settings.update({k: body[k] for k in self.settings}); return 200, self.settings
        elif path == "/api/reports/battery-health":
            days = body.get("days"); started = datetime.now().astimezone()
            self.report = {"state": "running", "days": days, "started_at": started.isoformat(), "finished_at": None, "duration_seconds": None, "markdown": None, "error": None}
            def done():
                time.sleep(4)
                self.report = {**self.report, "state": "idle", "finished_at": datetime.now().astimezone().isoformat(), "duration_seconds": 4.0,
                               "markdown": f"# Battery health ({days} days, mock)\n\n## Verdict\n- **Battery 1**: OK\n- **Battery 2**: OK\n- **Battery 3**: cell 3 a little high\n\n| Battery | Resistance | Cycles |\n|---|---|---|\n| 1 | 0.42 mΩ | 87 |\n| 2 | 0.45 mΩ | 86 |\n| 3 | 0.51 mΩ | 85 |\n\nNot from real data: `mock`."}
            threading.Thread(target=done, daemon=True).start(); return 200, self.report
        elif "/set-soc-" in path or path.startswith("/api/bms/set-all-soc/"):
            time.sleep(1); return 200, {"ok": True, "path": path, "percent": body.get("percent")}
        elif path.endswith(("/charge", "/discharge")):
            n = int(path.split("/")[3]); self.mos[n]["c" if path.endswith("/charge") else "d"] = bool(body["enabled"]); time.sleep(1)
        elif path.startswith("/api/bms/set-all/"):
            what, state = path.rsplit("/", 1)[1].split("-")
            for n in self.mos: self.mos[n]["c" if what == "charge" else "d"] = state == "on"
        return 200, {"ok": True}


class Anchor:
    def __init__(self):
        self.anchor = None; self.alarms = {}; self.silenced = 0; self.events = [{"t": time.time() - 600, "text": "Anchor watch started (mock)", "kind": "info"}]
        self.settings = {"default_radius": 40.0, "confirm_s": 10, "gps_timeout_s": 30, "core_timeout_s": 30, "min_depth": 0.0, "max_wind_kn": 0.0,
                         "bow_offset": 0.0, "gps_sources": "254", "own_mmsi": "", "pc_sound": True, "push_alerts": True, "alive_minutes": 60.0,
                         "internet_ais": True, "nfl_tracking": False, "nfl_on_anchor": False, "track_hours": 24, "bow_height": 1.2, "chain_formula": "5*(D+B)",
                         "loa": 11.5, "min_ais_dist": 0.0, "pos_format": "dmm", "draught": 1.6, "transducer_depth": 0.4, "nmea_port": 10110}
        self.track = []; self.gen = 1; self.forgotten = set(); self.pending_mock = False

    def pos(self):
        a = (time.time() - T0) / 60
        return {"lat": LAT0 + 0.00018 * math.sin(a), "lon": LON0 + 0.00025 * math.cos(a * .8), "source": "254", "name": "Orca Core"}

    def state(self):
        p = self.pos(); now = time.time()
        if not self.track or now - self.track[-1][0] > 5: self.track.append([round(now, 1), p["lat"], p["lon"]])
        out = {"time": now, "core": {"connected": True, "last_error": None, "last_message_age": 0.4},
               "ais_stream": {"connected": True, "last_error": None, "last_message_age": 3.0},
               "boat": {"pos": {**p, "sats": 11, "hdop": 0.8, "hold": int(now // 120) % 2 == 1}, "heading": (now * 2) % 360, "depth": 6.4, "tws": 12.3, "twd": 230, "sog": 0.3, "depth_offset": 0.4, "depth_offset_src": "sounder"},
               "gps_rows": [r for r in [{"source": "254", "name": "Orca Core", "status": "in_use", "sats": 11, "hdop": 0.8, "last_seen": None, "listed": True},
                            {"source": "2", "name": "B&G ZG100", "status": "active", "sats": 9, "hdop": 1.1, "last_seen": None, "listed": False},
                            {"source": "net-192.0.2.30", "name": "Network GPS (mock phone)", "status": "inactive", "sats": None, "hdop": None, "last_seen": 3600, "listed": False}]
                            if r["source"] not in self.forgotten],
               "gps_default": "254", "track_start": self.track[0][0] if self.track else None,
               "own_candidate": {"mmsi": "000000002", "name": "MOCK OWN BOAT", "dist": 4.0},
               "anchor": self.anchor, "settings": self.settings,
               "alarms": [{"id": k, "text": {"drag": "Anchor drag"}.get(k, k), "detail": v, "since": now - 20} for k, v in self.alarms.items()],
               "pending": {"drag": 4.0} if self.anchor and self.alarms == {} and self.pending_mock else {}, "sounding": bool(self.alarms) and now > self.silenced, "silenced_until": self.silenced if self.alarms else 0,
               "max_dist": 18.0, "events": self.events[-40:], "track_gen": self.gen,
               "push": {"configured": True, "last_error": None, "last_sent": now - 900}, "alive": {"configured": True, "last_ok": now - 300, "last_error": None, "note": None, "every_s": 300},
               "nfl": {"configured": True, "last_ok": now - 4000, "last_count": 12, "last_error": None, "sent_t": now - 4000}, "nmea": {"on": False, "port": 10110, "error": None}, "track_points": len(self.track), "version": "mock", "gps_age": 0.6,
               "ais": [{"mmsi": "000000001", "name": "MOCK VESSEL", "lat": LAT0 + 0.002, "lon": LON0 + 0.001, "length": 14, "heading": 90, "cog": 90, "sog": 0.0, "age": 30,
                        "src": "local", "dist": 240.0, "bearing": 18}],
               "net_ais": {"configured": True, "connected": True, "ships": 4, "last_error": None},
               "tide": {"available": True, "level": 0.42, "trend": "rising", "range": 1.9, "next": [{"type": "high", "t": now + 7200, "h": 1.1}, {"type": "low", "t": now + 29000, "h": -0.8}],
                        "curve": [[now + h * 3600, 0.95 * math.sin((h + 1.7) / 12.42 * 2 * math.pi)] for h in range(-6, 25)]},
               "depth_plan": {"available": True, "now": 6.4, "min": 5.6, "min_t": now + 29000, "max": 7.4, "max_t": now + 7200, "source": "sounder", "chain": 43, "formula": "5*(D+B)",
                              "bow_height": 1.2, "loa": 11.5, "draught": 1.6, "clearance_min": 4.0, "reading_t": now,
                              "curve": [[now + h * 3600, 6.4 + 0.95 * math.sin((h + 1.7) / 12.42 * 2 * math.pi)] for h in range(-6, 25)]}}
        if self.anchor:
            dy = (p["lat"] - self.anchor["lat"]) * 111320; dx = (p["lon"] - self.anchor["lon"]) * 111320 * math.cos(math.radians(LAT0))
            out["distance"], out["bearing"] = math.hypot(dx, dy), math.degrees(math.atan2(dx, dy)) % 360
        return out

    def command(self, c):
        a = c.get("action"); now = time.time()
        if a == "drop":
            p = self.pos(); self.anchor = {"lat": p["lat"] - 0.0001, "lon": p["lon"], "radius": float(c.get("radius") or 40), "set_at": now, "depth": 6.4}
            self.events.append({"t": now, "text": f"Anchor down, radius {self.anchor['radius']:.0f} m", "kind": "info"})
        elif a == "raise": self.anchor = None; self.alarms.clear(); self.events.append({"t": now, "text": "Anchor up – watch stopped", "kind": "info"})
        elif a == "radius":
            if not self.anchor: raise ValueError("Anchor is not set")
            self.anchor["radius"] = float(c["radius"])
        elif a == "move": self.anchor.update(lat=float(c["lat"]), lon=float(c["lon"]))
        elif a == "silence": self.silenced = now + float(c["minutes"]) * 60
        elif a == "settings": self.settings.update(c.get("settings") or {})
        elif a == "mock_alarm": self.alarms["drag"] = "Boat 52 m from the anchor (radius 40 m)"
        elif a == "mock_pending": self.pending_mock = True
        elif a == "clear_track": self.track = []; self.gen += 1; self.events.append({"t": now, "text": "New track started (old track and max swing deleted)", "kind": "info"})
        elif a == "gps_forget": self.forgotten.add(c["source"])
        elif a in ("push_test", "push_alarm_test", "push_alarm_stop", "alive_check", "net_ais_check", "nfl_send"): self.events.append({"t": now, "text": f"{a} (mock)", "kind": "info"})
        elif a == "mock_clear": self.alarms.clear()


class Guard:
    def __init__(self):
        self.enabled = True; self.present = True; self.armed = False; self.test = False; self.last_test = None
        self.cfg = {"away_after_s": 120, "poll_s": 60, "sounds": {"armed": "pushover", "disarmed": "falling", "unguarded": "siren"},
                    "priorities": {"armed": 0, "disarmed": 0, "unguarded": 1}}
        self.log = [f"{datetime.now():%Y-%m-%d %H:%M:%S} INFO BoatGuard started (mock)", f"{datetime.now():%Y-%m-%d %H:%M:%S} INFO phone on board"]

    def status(self):
        now = time.time()
        return {"enabled": self.enabled, "present": self.present, "router_ok": True, "router_error": None, "router_down_since": None, "last_poll": now - 12,
                "last_seen": now - 12, "away_after_s": self.cfg["away_after_s"], "poll_s": self.cfg["poll_s"], "now": now, "armed_by_us": self.armed,
                "arm_at": None, "test_running": self.test, "limits": {"away_after_s": [30, 3600], "poll_s": [10, 300]}, "notifications": True,
                "sounds": self.cfg["sounds"], "sound_options": ["", "pushover", "bike", "falling", "siren", "none"],
                "events": {"armed": "Camera armed", "disarmed": "Camera disarmed", "unguarded": "Left the boat, monitoring OFF"},
                "priorities": self.cfg["priorities"], "priority_options": {"-2": "Lowest", "-1": "Quiet", "0": "Normal", "1": "High", "2": "Emergency"},
                "emergency": {"retry_s": 60, "expire_s": 3600},
                "camera": {"armed": self.armed, "battery": 97, "online": True, "checked": now - 30, "error": None, "pending": False}, "last_test": self.last_test}

    def post(self, path, body):
        if path == "/api/enabled": self.enabled = bool(body.get("enabled")); self.log.append(f"{datetime.now():%Y-%m-%d %H:%M:%S} INFO monitoring {'ON' if self.enabled else 'OFF'}"); return 200, {"enabled": self.enabled}
        if path == "/api/settings":
            if body.get("poll_s", 0) > body.get("away_after_s", 1e9): return 400, {"error": "poll_s may not exceed away_after_s"}
            self.cfg.update(body); return 200, self.status()
        if path == "/api/notify-test": return 200, {"sent": True}
        if path == "/api/test":
            self.test = True
            def done(): time.sleep(4); self.test = False; self.last_test = {"ok": True, "finished": time.time()}
            threading.Thread(target=done, daemon=True).start(); return 200, {"started": True}
        return 404, {"error": "not found"}


class Washer:
    def __init__(self):
        self.d = {"power": True, "status": 1, "mode": 13, "fault": 0, "left_time": 58, "temperature": 40, "spin": 700, "rinses": 2, "locked": False}
        self.schedule = None; self.events = [{"time": datetime.now().strftime("%H:%M:%S"), "event": "MOCK", "detail": "started"}]

    MODES = {0: "Golden Wash", 16: "Antibacterial", 4: "Spin", 13: "Underwear", 22: "Rinse + Spin", 23: "Drum Clean", 29: "Boil Wash", 31: "Delicate",
             36: "New Clothes", 37: "Socks", 38: "Bra", 39: "Towel Boil Wash", 40: "Gloves"}
    SPIN = {31: 600, 38: 400}

    def status(self):
        d = dict(self.d); st = {0: "Standby", 1: "Standby", 7: "Washing", 9: "Rinsing", 11: "Spinning", 17: "Finished", 26: "Paused"}
        d.update(power_text="On" if d["power"] else "Off", status_text=st.get(d["status"], "?"), mode_text=self.MODES.get(d["mode"], "?"),
                 fault_text="No fault", locked_text="No", errors={}, schedule=self.schedule)
        return d

    def post(self, path, body):
        p = path.split("/"); self.events.insert(0, {"time": datetime.now().strftime("%H:%M:%S"), "event": path, "detail": ""})
        if path == "/api/power/on": self.d["power"] = True
        elif path == "/api/power/off": self.d.update(power=False, status=0)
        elif path == "/api/start": self.d.update(status=7, locked=True)
        elif path == "/api/pause": self.d.update(status=26)
        elif p[2] == "program": self.d.update(mode=int(p[3]), spin=self.SPIN.get(int(p[3]), 700))
        elif p[2] == "temperature": self.d["temperature"] = int(p[3])
        elif p[2] == "rinses": self.d["rinses"] = int(p[3])
        elif path == "/api/schedule/cancel": self.schedule = None
        elif path == "/api/schedule":
            hh, mm = map(int, body["time"].split(":")); now = datetime.now().astimezone(); t = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if t <= now: t += timedelta(days=1)
            start = t if body["mode"] == "start" else t - timedelta(minutes=self.d["left_time"])
            self.schedule = {"status": "pending", "mode": body["mode"], "start_at": start.isoformat(), "finish_at": (start + timedelta(minutes=self.d["left_time"])).isoformat(),
                             "program_name": self.MODES[self.d["mode"]]}
            return 200, {"ok": True, "schedule": self.schedule}
        return 200, {"ok": True}


def make(name, obj):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def _j(self, code, o):
            b = json.dumps(o).encode(); self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

        def do_GET(self):
            path, _, q = self.path.partition("?")
            if name == "power":
                if path == "/manual": b = b"<html><body><h1>MasterVolt manual (mock)</h1></body></html>"; self.send_response(200); self.send_header("Content-Type", "text/html"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b); return
                qs = dict(x.split("=", 1) for x in q.split("&") if "=" in x)
                if path == "/api/history/chart-data": return self._j(200, obj.chart_data(float(qs.get("hours", 24))))
                if path == "/api/history/contributions":
                    from urllib.parse import unquote
                    return self._j(200, obj.contributions(unquote(qs["start"]).replace("Z", "+00:00"), unquote(qs["end"]).replace("Z", "+00:00")))
                r = {"/api/energy": obj.energy, "/api/bms": obj.bms, "/api/balancers": obj.balancers, "/api/settings": lambda: obj.settings,
                     "/api/bluetooth-coordinator": obj.coordinator, "/api/bluetooth-events": obj.ble_events, "/api/history/status": obj.history_status,
                     "/api/reports/battery-health": lambda: obj.report, "/api/version": lambda: {"version": "2.1.2 (mock)"}}.get(path)
                return self._j(200, r()) if r else self._j(404, {"detail": "not found"})
            if name == "anchor":
                if path == "/api/state": return self._j(200, obj.state())
                if path == "/api/track": return self._j(200, {"gen": obj.gen, "points": obj.track})
                if path.startswith("/tiles/"):   # no map tiles in the mock
                    self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers(); return
            if name == "guard":
                if path == "/api/status": return self._j(200, obj.status())
                if path == "/api/log": return self._j(200, {"lines": obj.log})
            if name == "washer":
                if path in ("/api/status", "/api/start-check"): return self._j(200, obj.status())
                if path == "/api/schedule": return self._j(200, {"ok": True, "schedule": obj.schedule})
                if path == "/diagnostics/export": return self._j(200, {"recent_events": obj.events})
                if path == "/api/diagnostics":
                    if "recheck=1" in q: obj.events.insert(0, {"time": datetime.now().strftime("%H:%M:%S"), "event": "DIAGNOSTICS", "detail": "OK", "duration_ms": 812})
                    checks = [{"name": n, "ok": ok, "detail": d, "severity": sev} for n, ok, d, sev in (
                        ("Python runtime", True, "3.12 (mock)", "critical"), ("python-miio", True, "0.5.12", "critical"), ("Configuration file", True, "viomi_config.json", "critical"),
                        ("Washer IP", True, "192.0.2.10", "critical"), ("MIoT token", True, "32 hex characters", "critical"), ("Windows PC network", True, "192.0.2.20", "critical"),
                        ("UDP handshake", True, "192.0.2.10 · 31 ms", "critical"), ("Washer identity", True, "viomi.washer.w1 · firmware 1.0.0 · 140 ms", "critical"),
                        ("MIoT communication", False, "mock warning: slow reply (2100 ms)", "warning"))]
                    return self._j(200, {"checks": checks, "ok": True, "critical_count": 0, "warning_count": 1, "pc_ip": "192.0.2.20", "summary": "Ready with 1 warning(s)",
                                         "summary_class": "warn", "controller_version": "3.8-v59 (mock)", "uptime": "2 h 14 min", "washer_ip": "192.0.2.10",
                                         "expected_model": "viomi.washer.w1", "model": "viomi.washer.w1", "firmware": "1.0.0", "timings_ms": {"UDP handshake": 31}})
            self._j(404, {"error": "not found"})

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0); body = json.loads(self.rfile.read(n) or b"{}")
            if name in ("washer", "guard") and self.headers.get("X-Drifter-Token") != os.environ.get("DRIFTER_TOKEN"):   # the module contract
                return self._j(403, {"ok": False, "error": "Request not sent by the Drifter gateway"})
            if name == "anchor":
                try: obj.command(body); return self._j(200, {"ok": True, "state": obj.state()})
                except ValueError as e: return self._j(400, {"ok": False, "error": str(e)})
            code, out = obj.post(self.path, body); self._j(code, out)
    return H


if __name__ == "__main__":
    for name, port, obj in (("power", 18000, Power()), ("anchor", 18766, Anchor()), ("guard", 18095, Guard()), ("washer", 18080, Washer())):
        s = ThreadingHTTPServer(("127.0.0.1", port), make(name, obj)); s.daemon_threads = True
        threading.Thread(target=s.serve_forever, daemon=True).start(); print(f"mock {name} on http://127.0.0.1:{port}")
    os.environ.setdefault("DRIFTER_TOKEN", "mock-token")        # as drifterd gives it: the mock washer checks it
    if "--gateway" in sys.argv:          # also run the Drifter gateway against these mocks (config.mock.json, port 8101)
        import logging; sys.path.insert(0, str(ROOT)); import drifter
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
        # A supervisor that only watches the mock ports and only pretends to stop/start: it can never touch a real server.
        # "Switch all systems off" runs through, but the mock gateway stays up. Logs are made-up files in a temp folder.
        import supervisor, tempfile
        tmp = Path(tempfile.mkdtemp()); logs = {}
        for n in supervisor.LOG_NAMES:
            logs[n] = tmp / "logs" / f"{n}.console.log"; logs[n].parent.mkdir(exist_ok=True)
            logs[n].write_text("".join(f"2026-11-02 09:{i // 60:02d}:{i % 60:02d} INFO mock {n}: line {i}\n" for i in range(300)), encoding="utf-8")

        class MockSupervisor(supervisor.Supervisor):
            def shutdown_all(self, on_done=None): super().shutdown_all(None)
        fake = MockSupervisor(ports={"energy": 18000, "anchor": 18766, "guard": 18095, "washer": 18080}, data=tmp, logs=logs,
                              start=lambda n: logging.info("mock supervisor: would start %s", n),
                              stop=lambda n: (logging.info("mock supervisor: would stop %s", n), time.sleep(1)))
        fake.start_thread()
        drifter.serve(drifter.load_config(Path(__file__).resolve().parent / "config.mock.json"), supervisor=fake).serve_forever()
    threading.Event().wait()
