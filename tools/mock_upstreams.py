"""Fake module servers with made-up data, for developing and testing the Drifter page without the boat.

Never point this at, or run it instead of, the real servers: it only simulates. Commands change the fake state so
the page's controls can be tried. Positions are a made-up spot, not an anchorage of this boat.
Usage: py tools/mock_upstreams.py  (ports 18000 power, 18766 anchor, 18095 guard, 18080 washer, localhost only)
"""
from __future__ import annotations

import json, math, random, sys, threading, time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = (ROOT / "modules" / "anchor" / "static" / "vendor").resolve()
LAT0, LON0 = 50.0, -30.0          # mid-Atlantic: obviously not a real anchorage
T0 = time.time()


def wobble(a, b, period=40.0):
    return a + (b - a) * (0.5 + 0.5 * math.sin((time.time() - T0) / period))


class Power:
    def __init__(self):
        self.c = {"inverter": 0.0, "charger": 1.0, "support": 0.0, "limit": 10.0, "alt": False,
                  "dev": {"solar": True, "charger_start": True, "charger_bow": False, "engine_ecu": True}}
        self.mos = {n: {"c": True, "d": True} for n in (1, 2, 3)}
        self.settings = {"default_ac_limit": 10, "float_protection_enabled": True, "house_battery_soc": 95.0, "bulk_resume_soc": 90.0,
                         "float_cell_trigger_mv": 3450.0, "float_cell_resume_mv": 3380.0, "warning_popup_seconds": 8, "bms_refresh_interval": 30,
                         "bms_popup_seconds": 5, "bms_connection_retry_seconds": 5, "balancer_refresh_interval": 60,
                         "balancer_connection_retry_seconds": 30, "history_retention_days": 31}

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
                                  "chemistry": "LiFePO4", "soc_source": "daly_bms_average", "soc_age_seconds": 12, "max_cell_mv": 3341, "max_cell_battery": "BATTERY 1",
                                  "max_spread_mv": 18, "max_spread_battery": "BATTERY 1"},
                        "start": {"label": "Start Battery", "soc": None, "voltage": 13.4, "current": 0.4, "power": 5.4, "chemistry": "AGM"},
                        "bow": {"label": "Bow Battery", "soc": None, "voltage": 12.9, "current": 0.0, "power": 0.0, "chemistry": "AGM"}},
            "consumers": loads, "totals": {"dc_input_power": solar, "consumer_power": total, "ac_consumer_power": 92.0},
            "settings": self.settings,
            "high_soc_float_policy": {"enabled": self.settings["float_protection_enabled"], "threshold_soc": self.settings["house_battery_soc"],
                                      "bulk_resume_soc": self.settings["bulk_resume_soc"], "cell_trigger_mv": self.settings["float_cell_trigger_mv"],
                                      "cell_resume_mv": self.settings["float_cell_resume_mv"], "active": False, "trigger": None},
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
        return {"devices": {f"DL-BAL{n}": {"state": "connected", "stale": False, "error": None, "last_success_age_seconds": 20 + n,
                                           "values": {"pack_voltage_v": 13.33, "cells_mv": [3331, 3335, 3329 + n, 3333], "cell_delta_mv": 6 + n}} for n in (1, 2, 3)}}

    def post(self, path, body):
        if path == "/api/control/inverter": self.c["inverter"] = 1.0 if body["enabled"] else 0.0
        elif path == "/api/control/charger": self.c["charger"] = 1.0 if body["enabled"] else 0.0
        elif path == "/api/control/ac-support": self.c["support"] = 1.0 if body["enabled"] else 0.0
        elif path == "/api/control/ac-limit":
            if not 3 <= body.get("amps", 0) <= 15: return 422, {"detail": "amps must be 3-15"}
            self.c["limit"] = float(body["amps"])
        elif path == "/api/control/alternator": self.c["alt"] = bool(body["enabled"])
        elif path.startswith("/api/control/device/"): self.c["dev"][path.rsplit("/", 1)[1]] = bool(body["enabled"])
        elif path == "/api/control/mode": time.sleep(1.5); return 200, {"mode": body["mode"], "ok": True, "actions": []}
        elif path == "/api/settings":
            if body.get("bulk_resume_soc", 0) >= body.get("house_battery_soc", 100): return 400, {"detail": "Bulk resume SOC must be below the Float SOC"}
            self.settings.update(body); return 200, self.settings
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
        self.track = []; self.gen = 1

    def pos(self):
        a = (time.time() - T0) / 60
        return {"lat": LAT0 + 0.00018 * math.sin(a), "lon": LON0 + 0.00025 * math.cos(a * .8), "source": "254", "name": "Orca Core"}

    def state(self):
        p = self.pos(); now = time.time()
        if not self.track or now - self.track[-1][0] > 5: self.track.append([round(now, 1), p["lat"], p["lon"]])
        out = {"time": now, "core": {"connected": True, "last_error": None, "last_message_age": 0.4},
               "ais_stream": {"connected": True, "last_error": None}, "boat": {"pos": p, "heading": (now * 2) % 360, "depth": 6.4, "tws": 12.3, "twd": 230, "sog": 0.3},
               "gps_rows": [{"source": "254", "name": "Orca Core", "status": "in_use", "sats": 11, "hdop": 0.8, "last_seen": None, "listed": True},
                            {"source": "2", "name": "B&G ZG100", "status": "active", "sats": 9, "hdop": 1.1, "last_seen": None, "listed": False}],
               "anchor": self.anchor, "settings": self.settings,
               "alarms": [{"id": k, "text": {"drag": "Anchor drag"}.get(k, k), "detail": v, "since": now - 20} for k, v in self.alarms.items()],
               "pending": {}, "sounding": bool(self.alarms) and now > self.silenced, "silenced_until": self.silenced if self.alarms else 0,
               "max_dist": 18.0, "events": self.events[-40:], "track_gen": self.gen,
               "push": {"configured": True, "last_error": None}, "alive": {"configured": True, "last_ok": now - 300, "last_error": None, "note": None},
               "nfl": {"configured": False}, "nmea": {"on": False, "port": 10110, "error": None}, "track_points": len(self.track), "version": "mock", "gps_age": 0.6,
               "ais": [{"mmsi": "000000001", "name": "MOCK VESSEL", "lat": LAT0 + 0.002, "lon": LON0 + 0.001, "length": 14, "heading": 90, "cog": 90, "sog": 0.0, "age": 30,
                        "src": "local", "dist": 240.0, "bearing": 18}],
               "net_ais": {"configured": True, "connected": True, "ships": 4, "last_error": None},
               "tide": {"available": True, "level": 0.42, "trend": "rising", "next": [{"type": "high", "t": now + 7200, "h": 1.1}, {"type": "low", "t": now + 29000, "h": -0.8}]},
               "depth_plan": {"available": True, "min": 5.6, "max": 7.4, "source": "sounder", "chain": 43, "formula": "5*(D+B)", "clearance_min": 4.0}}
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
                r = {"/api/energy": obj.energy, "/api/bms": obj.bms, "/api/balancers": obj.balancers, "/api/settings": lambda: obj.settings}.get(path)
                return self._j(200, r()) if r else self._j(404, {"detail": "not found"})
            if name == "anchor":
                if path == "/api/state": return self._j(200, obj.state())
                if path == "/api/track": return self._j(200, {"gen": obj.gen, "points": obj.track})
                vendor = VENDOR / path[len("/vendor/"):] if path.startswith("/vendor/leaflet/") else None
                if vendor and vendor.is_file() and VENDOR in vendor.resolve().parents:   # Leaflet from the OrcaCore2 checkout, if present
                    b = vendor.read_bytes(); self.send_response(200); self.send_header("Content-Type", "text/css" if path.endswith(".css") else "application/javascript")
                    self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b); return
                if path.startswith(("/tiles/", "/vendor/")):   # no map tiles in the mock
                    self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers(); return
            if name == "guard":
                if path == "/api/status": return self._j(200, obj.status())
                if path == "/api/log": return self._j(200, {"lines": obj.log})
            if name == "washer":
                if path in ("/api/status", "/api/start-check"): return self._j(200, obj.status())
                if path == "/api/schedule": return self._j(200, {"ok": True, "schedule": obj.schedule})
                if path == "/diagnostics/export": return self._j(200, {"recent_events": obj.events})
                if path == "/": b = b"<html>diagnostics</html>"; self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b); return
            self._j(404, {"error": "not found"})

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0); body = json.loads(self.rfile.read(n) or b"{}")
            if name == "washer" and self.headers.get("X-Viomi-Request") != "1": return self._j(403, {"ok": False, "error": "missing X-Viomi-Request"})
            if name == "anchor":
                try: obj.command(body); return self._j(200, {"ok": True, "state": obj.state()})
                except ValueError as e: return self._j(400, {"ok": False, "error": str(e)})
            code, out = obj.post(self.path, body); self._j(code, out)
    return H


if __name__ == "__main__":
    for name, port, obj in (("power", 18000, Power()), ("anchor", 18766, Anchor()), ("guard", 18095, Guard()), ("washer", 18080, Washer())):
        s = ThreadingHTTPServer(("127.0.0.1", port), make(name, obj)); s.daemon_threads = True
        threading.Thread(target=s.serve_forever, daemon=True).start(); print(f"mock {name} on http://127.0.0.1:{port}")
    if "--gateway" in sys.argv:          # also run the Drifter gateway against these mocks (config.mock.json, port 8101)
        import logging; sys.path.insert(0, str(ROOT)); import drifter
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
        # A supervisor that only watches the mock ports and only pretends to stop/start: it can never touch a real server.
        import supervisor, tempfile
        fake = supervisor.Supervisor(ports={"energy": 18000, "anchor": 18766, "guard": 18095, "washer": 18080}, data=tempfile.mkdtemp(),
                                     start=lambda n: logging.info("mock supervisor: would start %s", n),
                                     stop=lambda n: (logging.info("mock supervisor: would stop %s", n), time.sleep(1)))
        fake.start_thread()
        drifter.serve(drifter.load_config(Path(__file__).resolve().parent / "config.mock.json"), supervisor=fake).serve_forever()
    threading.Event().wait()
