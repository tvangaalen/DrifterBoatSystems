"""The anchor watch itself: AnchorWatch (state, settings, alarms in tick(), commands), its loops and the PC beep."""
import asyncio, json, math, os, re, threading, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime
from collections import deque
from pathlib import Path
from orca_reader import CORE_SOURCE
from common import pushover

from anchor.ais import read_ais
from anchor.chain import ChainFormula, chain_advice
from anchor.geo import dist_bearing_m, offset
from anchor.gps import NetGPS, position_sources, read_boat
from anchor.settings import AIS_ALARM_AGE_S, BOOT_JITTER_S, CORE_INFO_S, DEFAULTS, DEFAULT_GPS, DIAG_S, FRESH_S, FROZEN_S, HOLD_LOG_S, HOLD_M, HOLD_MERGE_S, HOLD_NEAR_M, HOLD_SOON_S, NET_AWAY_M, ROUTE_KEYS, SETTING_LIMITS, SLOW_GPS, TRACK_EVERY_S, VERSION, log
from anchor.tide import depth_window


try: import winsound
except ImportError: winsound = None


# ---------------------------------------------------------------- the watch


class AnchorWatch:
    ALARM_TEXT = {"drag": "Anchor drag", "gps": "GPS position lost", "core": "No data from Orca Core", "ais": "AIS target close",
                  "depth": "Shallow water", "wind": "Wind limit"}

    def __init__(self, store, state_file, diag_dir=None):
        self.store, self.state_file = store, Path(state_file)
        self.diag_dir = Path(diag_dir) if diag_dir else None   # GPS values of held sources go here (None = off)
        self.diag = {}                     # source -> (file, recording ends at)
        self.raw = set()                   # sources whose navigation.position is held, own fix used instead
        self.hold = set()                  # the Core's GPS on static hold: still used (within HOLD_M)
        self.dt_seen = {}                  # source -> (fix time, time it last changed): is the receiver still alive?
        self.hold_soon = set()             # 254 probably on hold (own fix unchanged HOLD_SOON_S): live receivers first
        self.hold_logged = None; self.hold_was = set()
        self.route_seen = None             # last route state of the Core (ROUTE_KEYS label -> value)
        self.hold_since = None             # start of the current 254 hold (releases included)
        self.hold_left = None              # 254 left its hold here; the hold ends when it is not back within HOLD_MERGE_S
        self.hold_fix = None               # 254's held own fix, to measure the jump at a release
        self.hold_releases = 0             # releases (jumps of about HOLD_M) during the current hold
        self.stationary_seen = None        # last value of the Core's stationary flag
        self.core_boot = None              # when the Core last started (from its uptime; kept in the state file)
        self.core_fw = None                # the Core's firmware version
        self.lock = threading.RLock()
        self.settings = dict(DEFAULTS)
        self.anchor = None                 # {"lat", "lon", "radius", "set_at"}
        self.track = deque()               # [t, lat, lon]
        self.track_gen = 0                 # bumped when the track is cleared, so pages refetch it
        self.events = deque(maxlen=300)
        self.alarms = {}                   # id -> {"since", "text"}
        self.pending = {}                  # id -> time the condition started
        self.silenced_until = 0
        self.max_dist = 0.0
        self.boat = {"pos": None, "heading": None, "depth": None, "depth_transducer": None, "tws": None, "twd": None, "sog": None}
        self.last_pos_t = None
        self.last_source = None
        self.pos_seen = {}                 # (kind, source) -> (lat, lon, time the value last changed)
        self.frozen = set()                # sources whose position stopped changing (FROZEN_S)
        self.gps_list = []                 # every position source, for the page
        self.gps_seen = {}                 # every GPS source ever seen: src -> {"name", "first", "last"} (kept in the state file)
        self.away = set()                  # network GPS far from every other active GPS: not used
        self.nmea_on = False               # network GPS listener running (off with --no-nmea, e.g. test servers)
        self.netgps = NetGPS(store, on_event=lambda text, kind: self.event(text, kind=kind), on_new=self.net_gps_new)
        self.core_down_since = None
        self.started = time.time()
        self.dirty = False
        self.notifier = None               # Pushover, set by main() (tests use a fake)
        self.alive = None                  # StillAlive, set by main()
        self.netais = None                 # InternetAIS, set by main()
        self.tide = None                   # TideFeed, set by main()
        self.nfl = None                    # NoForeignLand, set by main()
        self.nfl_sent = None               # last point noforeignland.com accepted (kept in the state file)
        self.last_depth = None             # {"d", "t", "surface"}: last sounder reading, used while the sounder is off
        self.load()

    # ---- persistence
    def load(self):
        try: d = json.loads(self.state_file.read_text(encoding="utf-8"))
        except FileNotFoundError: return
        except Exception as e: log.warning("could not read %s: %s", self.state_file, e); return
        self.settings.update({k: v for k, v in d.get("settings", {}).items() if k in DEFAULTS})
        old_scope = d.get("settings", {}).get("scope_ratio")
        if old_scope is not None and "chain_formula" not in d.get("settings", {}):        # fixed scope before 1.9.0
            self.settings["chain_formula"] = f"{old_scope:g}*(D+B)"
        if self.settings["gps_sources"] == "4,127,3": self.settings["gps_sources"] = DEFAULT_GPS   # old default (< 1.2.0)
        self.anchor = d.get("anchor"); self.max_dist = d.get("max_dist", 0.0)
        self.track = deque(d.get("track", [])); self.events.extend(d.get("events", [])); self.last_depth = d.get("last_depth")
        self.gps_seen = {str(k): v for k, v in (d.get("gps_seen") or {}).items() if isinstance(v, dict)}
        self.nfl_sent = d.get("nfl_sent") if isinstance(d.get("nfl_sent"), dict) else None
        if isinstance(d.get("core_boot"), (int, float)): self.core_boot = d["core_boot"]
        if isinstance(d.get("net_gps"), dict):
            self.netgps.sources = {str(ip): str(s) for ip, s in d["net_gps"].items() if str(s).isdigit()}
        if self.anchor: log.info("anchor watch restored: %.6f, %.6f radius %.0f m", self.anchor["lat"], self.anchor["lon"], self.anchor["radius"])

    def save(self):
        with self.lock:
            d = {"settings": self.settings, "anchor": self.anchor, "max_dist": self.max_dist,
                 "track": list(self.track), "events": list(self.events), "last_depth": self.last_depth, "gps_seen": self.gps_seen,
                 "nfl_sent": self.nfl.sent if self.nfl is not None else self.nfl_sent, "core_boot": self.core_boot,
                 "net_gps": dict(self.netgps.sources)}
            self.dirty = False
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, separators=(",", ":")), encoding="utf-8"); os.replace(tmp, self.state_file)

    def event(self, text, now=None, kind="info"):
        self.events.append({"t": now or time.time(), "text": text, "kind": kind}); log.info(text); self.dirty = True

    # ---- evaluation, once per second
    def tick(self, now=None):
        now = now or time.time()
        with self.store.lock:
            sensors = dict(self.store.values["sensors"]); connected = self.store.status["sensors"]["connected"]
            ais = dict(self.store.values["ais"]) if self.settings["min_ais_dist"] > 0 else None
        with self.lock:
            s = self.settings
            prefs = [x.strip() for x in str(s["gps_sources"]).split(",") if x.strip()]
            srcs = position_sources(sensors, now); gsrcs = position_sources(sensors, now, "gnss")
            held = {}
            for kind, d in (("position", srcs), ("gnss", gsrcs)):
                for src, c in d.items():
                    seen = self.pos_seen.get((kind, src))
                    if not seen or (seen[0], seen[1]) != (c["lat"], c["lon"]): self.pos_seen[(kind, src)] = (c["lat"], c["lon"], now)
                held[kind] = {src for src, c in d.items() if c["age"] <= FRESH_S and now - self.pos_seen[(kind, src)][2] >= self.frozen_after(src)}
            # navigation.position held: use the receiver's own fix while that still changes; frozen only when both are held
            raw = {src for src in held["position"] if src in gsrcs and gsrcs[src]["age"] <= FRESH_S and src not in held["gnss"]}
            for src in gsrcs:
                dt = sensors.get(f"navigation.gnss.{src}.datetime"); dt = dt[0] if dt else None
                if dt is not None and (src not in self.dt_seen or self.dt_seen[src][0] != dt): self.dt_seen[src] = (dt, now)
            # the Core's GPS on static hold: its own fix held while the receiver keeps producing fixes; navigation.position
            # is held too, or flickers within HOLD_NEAR_M of that fix
            hold = {src for src in held["gnss"] if src == CORE_SOURCE and src in srcs and srcs[src]["age"] <= FRESH_S
                    and src in self.dt_seen and now - self.dt_seen[src][1] <= FRESH_S
                    and (src in held["position"] or dist_bearing_m(srcs[src]["lat"], srcs[src]["lon"], gsrcs[src]["lat"], gsrcs[src]["lon"])[0] <= HOLD_NEAR_M)}
            frozen = held["position"] - raw - hold
            # not confirmed yet, but a live receiver goes first: the hold holds again at once after a release
            soon = hold | {src for src in gsrcs if src == CORE_SOURCE and src in srcs and srcs[src]["age"] <= FRESH_S
                           and src not in frozen and now - self.pos_seen[("gnss", src)][2] >= HOLD_SOON_S
                           and src in self.dt_seen and now - self.dt_seen[src][1] <= FRESH_S
                           and dist_bearing_m(srcs[src]["lat"], srcs[src]["lon"], gsrcs[src]["lat"], gsrcs[src]["lon"])[0] <= HOLD_NEAR_M}
            # a phone that went ashore in the dinghy: a network GPS far from every other active GPS is not used
            others = [c for src, c in srcs.items() if not self.netgps.is_net(src) and c["age"] <= FRESH_S]
            away = {src for src, c in srcs.items() if self.netgps.is_net(src) and c["age"] <= FRESH_S and others
                    and min(dist_bearing_m(c["lat"], c["lon"], o["lat"], o["lon"])[0] for o in others) > NET_AWAY_M}
            for src in away - self.away:
                self.event(f"GPS {self.source_name(src)} is more than {NET_AWAY_M} m from the other GPS: not used (taken off the boat?)", now, "warn")
            for src in self.away - away:
                if src in srcs and srcs[src]["age"] <= FRESH_S: self.event(f"GPS {self.source_name(src)} is back near the other GPS", now, "ok")
            route = self.route_state(sensors)
            if route != self.route_seen:
                if route and self.route_seen:
                    ch = ", ".join(f"{k} {self.route_seen.get(k)} → {v}" for k, v in route.items() if self.route_seen.get(k) != v)
                    self.event(f"Orca Core route: {ch}", now)
                elif route: self.event("Orca Core route: " + ", ".join(f"{k} {v}" for k, v in route.items()), now)
                if route or self.route_seen: self.core_log(now, "route", sensors, route)   # not the empty state before the first data
                self.route_seen = route
            st = sensors.get(f"navigation.motion.{CORE_SOURCE}.stationary"); st = st[0] if st else None
            if st is not None and st != self.stationary_seen:
                sog = sensors.get(f"navigation.cogsog.{CORE_SOURCE}.speed")
                self.core_log(now, f"stationary {self.stationary_seen} → {st}", sensors, route,
                              sog_kn=round(sog[0] * 1.943844, 2) if sog and sog[0] is not None else None, on_hold=CORE_SOURCE in self.hold)
                self.stationary_seen = st
            if CORE_SOURCE in hold and CORE_SOURCE not in self.hold:
                fix = (gsrcs[CORE_SOURCE]["lat"], gsrcs[CORE_SOURCE]["lon"])
                if self.hold_since is not None and self.hold_left is not None:        # back within HOLD_MERGE_S: a release
                    self.hold_releases += 1
                    self.core_log(now, "hold release", sensors, route, jump_m=round(dist_bearing_m(*self.hold_fix, *fix)[0], 1),
                                  away_s=round(now - self.hold_left))
                else:
                    self.hold_since, self.hold_releases = now, 0; self.core_log(now, "hold start", sensors, route)
                self.hold_left, self.hold_fix = None, fix
            elif CORE_SOURCE in self.hold and CORE_SOURCE not in hold: self.hold_left = now
            if self.hold_left is not None and now - self.hold_left > HOLD_MERGE_S:
                if self.hold_since is not None:
                    self.core_log(now, "hold end", sensors, route, held_s=round(self.hold_left - self.hold_since), releases=self.hold_releases)
                self.hold_since = self.hold_left = None
            if hold - self.hold and (self.hold_logged is None or now - self.hold_logged >= HOLD_LOG_S):
                self.hold_logged = now
                self.event(f"GPS {self.source_name(CORE_SOURCE)} on hold: the Core keeps its fix while the boat lies still and moves it "
                           f"on after about {HOLD_M} m. Still used; position within about {HOLD_M} m", now)
                if self.diag_dir and CORE_SOURCE not in self.diag: self.start_diag(CORE_SOURCE, now)
            for src in raw - self.raw - self.frozen:
                self.event(f"GPS {self.source_name(src)}: position unchanged for {self.frozen_after(src)} s, its own GNSS fix still changes: using that", now)
            for src in frozen - self.frozen:
                self.event(f"GPS {self.source_name(src)} has not moved at all for {self.frozen_after(src)} s"
                           + (" (position and own GNSS fix)" if src in gsrcs else "") + ": treated as frozen, not used", now, "warn")
            for src in (self.frozen | self.raw) - frozen - raw:
                if src in srcs: self.event(f"GPS {self.source_name(src)} is updating again", now, "ok")
            if self.diag_dir:
                for src in (frozen | raw) - set(self.diag): self.start_diag(src, now)
                self.record_diag(sensors, now)
            self.hold_was = self.hold_soon
            self.frozen, self.raw, self.hold, self.hold_soon, self.away = frozen, raw, hold, soon, away
            boat = read_boat(sensors, now, prefs, frozen | away, float(s["transducer_depth"]), raw, soon); self.boat = boat; pos = boat["pos"]
            if pos: pos["hold"] = pos["source"] in soon
            if boat["depth"] is not None:
                if not self.last_depth or now - self.last_depth["t"] >= 60: self.dirty = True       # persisted about once a minute
                self.last_depth = {"d": boat["depth"], "t": now, "lat": pos["lat"] if pos else None, "lon": pos["lon"] if pos else None}
            self.gps_list = [{"source": src, "name": self.source_name(src), "sats": c["sats"], "hdop": c["hdop"],
                              "age": round(c["age"], 1), "frozen": src in frozen, "raw": src in raw, "hold": src in soon, "away": src in away, "in_use": bool(pos and pos["source"] == src)}
                             for src, c in sorted(srcs.items(), key=lambda kv: (kv[0] != CORE_SOURCE, int(kv[0])))]
            for src, c in srcs.items():
                if c["age"] > FRESH_S: continue
                g = self.gps_seen.get(src)
                if g is None: g = self.gps_seen[src] = {"name": self.source_name(src), "first": round(now), "last": round(now)}; self.dirty = True
                if now - g["last"] >= 60: g["last"] = round(now); self.dirty = True     # persisted about once a minute
                name = self.source_name(src)
                if name != g["name"] and name != str(src): g["name"] = name; self.dirty = True
            self.core_down_since = None if connected else (self.core_down_since or now)
            if pos:
                self.last_pos_t = now
                if pos["source"] != self.last_source:
                    # switches caused by the 254 hold come and go every few minutes: the hold message covers them
                    if self.last_source is not None and CORE_SOURCE not in soon and not (pos["source"] == CORE_SOURCE and CORE_SOURCE in self.hold_was):
                        self.event(f"Position source now {self.source_name(pos['source'])}", now, "warn")
                    self.last_source = pos["source"]
                if not self.track or now - self.track[-1][0] >= TRACK_EVERY_S:
                    self.track.append([round(now, 1), round(pos["lat"], 7), round(pos["lon"], 7)]); self.dirty = True
                while self.track and self.track[0][0] < now - s["track_hours"] * 3600: self.track.popleft()
            if self.nfl is not None and self.nfl.sent != self.nfl_sent: self.nfl_sent = self.nfl.sent; self.dirty = True

            cond = {}
            if self.anchor:
                a = self.anchor
                core_down = self.core_down_since is not None
                cond["core"] = (core_down, s["core_timeout_s"], "")
                no_pos = pos is None
                cond["gps"] = (no_pos and not core_down, s["gps_timeout_s"], "")
                if pos:
                    d, b = dist_bearing_m(a["lat"], a["lon"], pos["lat"], pos["lon"])
                    self.max_dist = max(self.max_dist, d)
                    cond["drag"] = (d > a["radius"], s["confirm_s"], f"{d:.0f} m from anchor (limit {a['radius']:.0f} m)")
                if s["min_depth"] > 0 and boat["depth"] is not None:
                    cond["depth"] = (boat["depth"] < s["min_depth"], 10, f"{boat['depth']:.2f} m (limit {s['min_depth']:.2f} m)")
                if ais is not None and pos:
                    # closest AIS target (own receiver, or internet AIS younger than AIS_ALARM_AGE_S: an older internet
                    # position could be anywhere by now)
                    net = self.netais.snapshot(now) if self.netais is not None and s["internet_ais"] else None
                    near = [t for t in read_ais(ais, now, pos["lat"], pos["lon"], str(s["own_mmsi"]), None, net)
                            if t["src"] == "local" or t["age"] <= AIS_ALARM_AGE_S]
                    if near:
                        t = near[0]
                        cond["ais"] = (t["dist"] < s["min_ais_dist"], 10, f"{t['name'] or t['mmsi']} {t['dist']:.0f} m (limit {s['min_ais_dist']:.0f} m)")
                    else: cond["ais"] = (False, 10, "")
                if s["max_wind_kn"] > 0 and boat["tws"] is not None:
                    cond["wind"] = (boat["tws"] > s["max_wind_kn"], 10, f"{boat['tws']:.0f} kn (limit {s['max_wind_kn']:.0f} kn)")
            for aid, (on, hold, detail) in cond.items():
                if on:
                    self.pending.setdefault(aid, now)
                    if aid not in self.alarms and now - self.pending[aid] >= hold:
                        self.alarms[aid] = {"since": now}; self.event(f"ALARM: {self.ALARM_TEXT[aid]}" + (f" – {detail}" if detail else ""), now, "alarm")
                        self._push_alarm(aid, detail, now)
                    if aid in self.alarms: self.alarms[aid]["detail"] = detail
                else:
                    self.pending.pop(aid, None)
                    if aid in self.alarms:
                        del self.alarms[aid]; self.event(f"Cleared: {self.ALARM_TEXT[aid]}", now, "ok")
                        self._push_cleared(aid, now)
            for aid in [x for x in self.alarms if x not in cond]:                          # condition switched off
                del self.alarms[aid]; self._push_cancel(aid)
            for aid in [x for x in self.pending if x not in cond]: del self.pending[aid]
            if not self.alarms: self.silenced_until = 0

    def _push_ok(self): return self.notifier is not None and self.notifier.configured and self.settings["push_alerts"]

    def _push_alarm(self, aid, detail, now):
        if not self._push_ok() or not self.settings.get(f"push_on_{aid}", True): return
        b = self.boat
        extra = [x for x in (f"Depth {b['depth']:.1f} m" if b.get("depth") is not None else "",
                             f"wind {b['tws']:.0f} kn" if b.get("tws") is not None else "") if x]
        msg = (detail or self.ALARM_TEXT[aid]) + "." + (" " + ", ".join(extra) + "." if extra else "")
        s = self.settings
        self.notifier.alarm(aid, f"\u2693 {self.ALARM_TEXT[aid]}", msg, now, priority=2 if aid == "drag" else s.get(f"push_prio_{aid}", 1),
                            sound=s.get(f"push_sound_{aid}", ""))

    def _push_cleared(self, aid, now):
        if self._push_ok() and self.settings.get(f"push_on_{aid}", True) and self.settings["push_on_cleared"]: self.notifier.cleared(aid, f"Cleared: {self.ALARM_TEXT[aid]}", "The alarm condition has ended.", now,
                                                  priority=self.settings["push_prio_cleared"], sound=self.settings["push_sound_cleared"])

    def _push_cancel(self, aid=None):
        if self.notifier is not None: self.notifier.cancel(aid)

    # ---- GPS diagnostics: what a held source sends, for finding out why it holds (local file, never committed)
    def start_diag(self, src, now):
        try:
            self.diag_dir.mkdir(exist_ok=True)
            f = self.diag_dir / f"gps_held_{src}_{datetime.fromtimestamp(now).strftime('%Y%m%d_%H%M%S')}.jsonl"
            self.diag[src] = (f, now + DIAG_S)
            self.event(f"Recording the values of GPS {self.source_name(src)} for {DIAG_S // 60} min to {self.diag_dir.name}/{f.name}", now)
        except OSError as e: log.warning("GPS diagnostics: %s", e)

    def record_diag(self, sensors, now):
        for src, (f, end) in list(self.diag.items()):
            if now > end: del self.diag[src]; continue
            keys = [k for k in sensors if f".{src}." in k and k.startswith(("navigation.position.", "navigation.gnss.",
                    "navigation.motion.", "navigation.cogsog.", "navigation.time.", "historical.", "navigation.data.",
                    "navigation.state.", "navigation.xte."))]
            row = {"t": round(now, 1), "values": {k: [sensors[k][0], round(now - sensors[k][1], 1)] for k in sorted(keys)}}
            try:
                with open(f, "a", encoding="utf-8") as fh: fh.write(json.dumps(row) + "\n")
            except OSError as e: log.warning("GPS diagnostics: %s", e); del self.diag[src]

    @staticmethod
    def route_state(sensors):
        """The Core's route state (ROUTE_KEYS label -> value), {} without route data."""
        return {label: sensors[k][0] for k, label in ROUTE_KEYS.items() if k in sensors}

    def frozen_after(self, src):
        """Seconds without any change before a source counts as frozen: FROZEN_S, longer only for SLOW_GPS models."""
        name = self.source_name(src)
        return next((secs for model, secs in SLOW_GPS.items() if model in name), FROZEN_S)

    def core_log(self, now, what, sensors, route, **extra):
        """One line in recordings/core_gps_log.jsonl: a 254 hold starting, releasing or ending, a change of the
        stationary flag or of the route, with the other GPS receivers that are active (does the hold need them?)."""
        if not self.diag_dir: return
        st = sensors.get(f"navigation.motion.{CORE_SOURCE}.stationary")
        others = sorted((src for src, c in position_sources(sensors, now).items() if src != CORE_SOURCE and c["age"] <= FRESH_S), key=int)
        row = {"t": round(now, 1), "time": datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S"), "what": what,
               "stationary": st[0] if st else None, "route": route, "other_gps": others,
               "core_up_s": round(now - self.core_boot) if self.core_boot else None, **extra}
        try:
            self.diag_dir.mkdir(exist_ok=True)
            with open(self.diag_dir / "core_gps_log.jsonl", "a", encoding="utf-8") as fh: fh.write(json.dumps(row) + "\n")
        except OSError as e: log.warning("GPS diagnostics: %s", e)

    def core_info(self, info, now=None):
        """The Core's /info page (read every CORE_INFO_S): a new boot time means the Core restarted; logged with the
        hold state, so the log shows whether a restart keeps the 254 hold away."""
        now = now or time.time()
        up = info.get("uptime")
        if not isinstance(up, (int, float)) or up < 0: return
        boot, fw = now - up, info.get("version_fw")
        with self.lock:
            with self.store.lock: sensors = dict(self.store.values["sensors"])
            known = self.core_boot
            if known is not None and abs(boot - known) <= BOOT_JITTER_S:
                if fw != self.core_fw and self.core_fw is not None: self.event(f"Orca Core firmware {self.core_fw} → {fw}", now)
                self.core_fw = fw
                return
            self.core_boot, self.core_fw = boot, fw; self.dirty = True
            when = datetime.fromtimestamp(boot).strftime("%Y-%m-%d %H:%M:%S")
            if known is None:
                self.core_log(now, "core running", sensors, self.route_state(sensors), booted=when, firmware=fw)
            else:
                self.core_log(now, "core restart", sensors, self.route_state(sensors), booted=when, firmware=fw,
                              previous_boot=datetime.fromtimestamp(known).strftime("%Y-%m-%d %H:%M:%S"),
                              hold_before=self.hold_since is not None)
                self.event(f"Orca Core restarted at {datetime.fromtimestamp(boot).strftime('%H:%M')}", now)

    def gps_rows(self, now):
        """Every GPS source ever seen, in the order they are tried (gps_sources first, then the others as read_boat
        tries them), with its status: in_use, active, hold, raw (own GNSS fix), frozen, inactive or never (not seen)."""
        prefs = [x.strip() for x in str(self.settings["gps_sources"]).split(",") if x.strip()]
        live = {g["source"]: g for g in self.gps_list if g["age"] <= FRESH_S}
        rest = sorted((s for s in set(self.gps_seen) | set(live) if s not in prefs),
                      key=lambda s: (s not in live, -(self.gps_seen.get(s, {}).get("last") or 0)))
        rows = []
        for i, src in enumerate(prefs + rest):
            g, seen = live.get(src), self.gps_seen.get(src)
            if g: status = "in_use" if g["in_use"] else "away" if g.get("away") else "frozen" if g["frozen"] else "hold" if g["hold"] else "raw" if g["raw"] else "active"
            else: status = "inactive" if seen else "never"
            rows.append({"source": src, "name": (g or {}).get("name") or (seen or {}).get("name") or self.source_name(src), "status": status,
                         "sats": g["sats"] if g and g["sats"] is not None and 0 < g["sats"] < 100 else None,   # 253-255 = not available (NMEA 2000)
                         "hdop": g["hdop"] if g else None,
                         "last_seen": None if g or not seen else round(now - seen["last"]), "listed": src in prefs})
        return rows

    def net_gps_new(self, ip, src):
        self.event(f"Network GPS from {ip} (NMEA over the LAN) is source {src}"); self.dirty = True

    def source_name(self, src):
        if src == CORE_SOURCE: return "254 (Orca Core 2)"
        ip = self.netgps.ip_of(src)
        if ip: return f"{src} (Network GPS {ip})"
        label = self.store.source_label(src)
        label = " ".join(re.sub(r"\s*(https?://|www\.)\S+", "", label or "").split())   # some devices put their web address in the model name
        return f"{src} ({label})" if label and not label.startswith("Source ") else str(src)

    def sounding(self, now=None):
        return bool(self.alarms) and (now or time.time()) >= self.silenced_until

    # ---- commands from the page
    def command(self, c):
        now = time.time(); act = c.get("action")
        with self.lock:
            pos, hdg, s = self.boat["pos"], self.boat["heading"], self.settings
            if act == "drop":
                if not pos: raise ValueError("No GPS position – cannot drop the anchor here")
                ahead = s["bow_offset"] + (_num(c, "distance", 0, 2000) if c.get("mode") == "ahead" else 0)
                if ahead and hdg is None: raise ValueError("No heading – cannot place the anchor ahead of the boat")
                lat, lon = offset(pos["lat"], pos["lon"], hdg or 0, ahead) if ahead else (pos["lat"], pos["lon"])
                radius = _num(c, "radius", 5, 2000) if c.get("radius") is not None else s["default_radius"]
                self.anchor = {"lat": lat, "lon": lon, "radius": radius, "set_at": now, "depth": self.boat["depth"]}
                self.max_dist = dist_bearing_m(lat, lon, pos["lat"], pos["lon"])[0]
                self._push_cancel(); self.alarms.clear(); self.pending.clear()
                self.event(f"Anchor down at {lat:.6f}, {lon:.6f}" + (f", {ahead:.0f} m ahead of the GPS" if ahead else "") + f", radius {radius:.0f} m", now)
                if self.nfl is not None and self.nfl.configured and s["nfl_on_anchor"]: self.nfl.dropped()
            elif act == "move":
                if not self.anchor: raise ValueError("Anchor is not set")
                self.anchor["lat"], self.anchor["lon"] = _num(c, "lat", -90, 90), _num(c, "lon", -180, 180)
                self.max_dist = 0.0; self.event(f"Anchor position moved to {self.anchor['lat']:.6f}, {self.anchor['lon']:.6f}", now)
            elif act == "radius":
                if not self.anchor: raise ValueError("Anchor is not set")
                self.anchor["radius"] = _num(c, "radius", 5, 2000); self.event(f"Radius set to {self.anchor['radius']:.0f} m", now)
            elif act == "raise":
                if self.anchor: self.event("Anchor up – watch stopped", now)
                self._push_cancel(); self.anchor = None; self.alarms.clear(); self.pending.clear(); self.silenced_until = 0
            elif act == "silence":
                mins = _num(c, "minutes", 0.5, 60)
                if self.alarms:
                    self.silenced_until = now + mins * 60; self.event(f"Alarm silenced for {mins:g} min", now)
                    self._push_cancel()                      # someone is on it: stop the repeating phone alert
            elif act == "settings":
                new = {}
                for k, v in (c.get("settings") or {}).items():
                    if k not in DEFAULTS: continue
                    if isinstance(DEFAULTS[k], bool): v = bool(v)
                    elif k == "pos_format":
                        v = str(v).strip()
                        if v not in ("dmm", "dms", "dd"): raise ValueError("Position format must be dmm, dms or dd")
                    elif k == "chain_formula":
                        v = ChainFormula(v).text                             # raises ValueError with a clear message
                    elif k == "own_mmsi":
                        v = str(v).strip()
                        if v and not (v.isdigit() and len(v) == 9): raise ValueError("My MMSI must be 9 digits (or empty)")
                    elif k.startswith("push_sound_"):
                        v = str(v)
                        if v not in pushover.SOUNDS: raise ValueError(f"Unknown Pushover sound {v!r}")
                    elif k.startswith("push_prio_"):
                        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != int(v) or not -2 <= v <= 1:
                            raise ValueError("A push alert's priority must be -2, -1, 0 or 1 (only anchor drag is an emergency)")
                        v = int(v)
                    elif k.startswith("col_"):
                        v = str(v).strip().lower()
                        if not re.fullmatch(r"#[0-9a-f]{6}", v): raise ValueError("A map colour must be #rrggbb")
                    elif k == "nmea_port":
                        try: f = float(v); v = int(f)
                        except (TypeError, ValueError, OverflowError): raise ValueError("NMEA port must be a whole number") from None
                        if f != v: raise ValueError("NMEA port must be a whole number")
                        lo, hi = SETTING_LIMITS[k]
                        if not lo <= v <= hi: raise ValueError(f"NMEA port must be between {lo} and {hi}")
                    elif isinstance(DEFAULTS[k], str): v = ",".join(x.strip() for x in str(v).split(",") if x.strip().isdigit())
                    else:
                        lo, hi = SETTING_LIMITS[k]; v = float(v)
                        if not (math.isfinite(v) and lo <= v <= hi): raise ValueError(f"{k} must be between {lo} and {hi}")
                    new[k] = v
                # the page sends every field on Save: only real changes are applied, logged and acted on
                changed = {k: v for k, v in new.items() if v != self.settings[k]}
                if changed:
                    self.event("Settings changed: " + ", ".join(f"{k} {self.settings[k]!r} → {v!r}".replace("'", "") for k, v in changed.items()), now)
                    self.settings.update(changed)
                    if self.alive is not None and "alive_minutes" in changed: self.alive.poke()
                    if self.nfl is not None and changed.get("nfl_tracking"): self.nfl.poke()
            elif act in ("push_alarm_test", "push_alarm_stop"):
                if self.notifier is None: raise ValueError("Push alerts are not available")
                err = self.notifier.reload()
                if err: raise ValueError(f"Pushover is not set up: {err}")
                snd = c.get("sound")
                if snd is not None and snd not in pushover.SOUNDS: raise ValueError(f"Unknown Pushover sound {snd!r}")
                if act == "push_alarm_test": self.notifier.test_alarm(sound=snd); self.event("Test alarm (emergency) sent to Pushover", now, "warn")
                else: self.notifier.cancel("test"); self.event("Test alarm stopped", now)
            elif act == "push_test":
                if self.notifier is None: raise ValueError("Push alerts are not available")
                err = self.notifier.reload()
                if err: raise ValueError(f"Pushover is not set up: {err}")
                key = c.get("key")
                if key is None:
                    self.notifier.test(); self.event("Test push sent to Pushover", now)
                else:      # one alert (not anchor drag: that one is the emergency test alarm)
                    text = {**self.ALARM_TEXT, "cleared": "Alarm cleared"}.get(key)
                    if text is None or key == "drag": raise ValueError(f"No test for {key!r}" + (" (anchor drag: use the test alarm)" if key == "drag" else ""))
                    snd, pr = c.get("sound", self.settings.get(f"push_sound_{key}", "")), c.get("priority", self.settings.get(f"push_prio_{key}", 1))
                    if snd not in pushover.SOUNDS: raise ValueError(f"Unknown Pushover sound {snd!r}")
                    if isinstance(pr, bool) or pr not in (-2, -1, 0, 1): raise ValueError("Priority must be -2, -1, 0 or 1")
                    self.notifier.test(f"\u2693 Test: {text}", priority=pr, sound=snd); self.event(f"Test push \"{text}\" sent to Pushover", now)
            elif act == "alive_check":
                if self.alive is None: raise ValueError("The still-alive check is not available")
                err = self.alive.reload()
                if err: raise ValueError(f"Still-alive check is not set up: {err}")
                self.alive.poke(ping_now=True); self.event("Still-alive ping requested", now)
            elif act == "net_ais_check":
                if self.netais is None: raise ValueError("Internet AIS is not available")
                err = self.netais.reload()
                if err: raise ValueError(f"Internet AIS is not set up: {err}")
                self.event("Internet AIS: key re-read, reconnecting", now)
            elif act == "gps_forget":
                src = str(c.get("source", "")).strip()
                if not src: raise ValueError("No GPS given")
                if any(g["source"] == src and g["age"] <= FRESH_S for g in self.gps_list):
                    raise ValueError(f"GPS {self.source_name(src)} is active: only a GPS that is not active can be removed")
                name = (self.gps_seen.get(src) or {}).get("name") or self.source_name(src)
                self.gps_seen.pop(src, None); self.netgps.forget(src)
                prefs = [x.strip() for x in str(s["gps_sources"]).split(",") if x.strip()]
                if src in prefs: s["gps_sources"] = ",".join(p for p in prefs if p != src)
                with self.store.lock:
                    for k in [k for k in self.store.values["sensors"] if k.startswith("navigation.") and k.split(".")[2:3] == [src]]:
                        del self.store.values["sensors"][k]
                self.event(f"GPS {name} removed from the list (it comes back if it is seen again)", now); self.dirty = True
            elif act == "nfl_send":
                if self.nfl is None: raise ValueError("noforeignland.com tracking is not available")
                err = self.nfl.reload()
                if err: raise ValueError(f"noforeignland.com tracking is not set up: {err}")
                if not s["nfl_tracking"] and not s["nfl_on_anchor"]: raise ValueError("noforeignland.com tracking is off")
                if s["nfl_tracking"]: self.nfl.poke()
                else: self.nfl.dropped()            # only-at-anchor mode: send the track up to here
                self.event("noforeignland.com upload requested", now)
            elif act == "clear_track":
                self.track.clear(); self.track_gen += 1; self.max_dist = 0.0; self.event("New track started (old track and max swing deleted)", now)
            else: raise ValueError(f"Unknown action {act!r}")
            self.dirty = True
        self.save()

    # ---- what the page shows
    def state(self):
        now = time.time()
        with self.store.lock:
            ais = dict(self.store.values["ais"]); st = self.store.status["sensors"]
            core = {"connected": st["connected"], "last_error": st["last_error"], "last_message_age": now - st["last_message"] if st["last_message"] else None}
            sa = self.store.status["ais"]
            ais_stream = {"connected": sa["connected"], "last_error": sa["last_error"], "reconnects": sa["reconnects"],
                          "last_message_age": now - sa["last_message"] if sa["last_message"] else None}
        with self.lock:
            b = self.boat; pos = b["pos"]; a = self.anchor
            out = {"time": now, "core": core, "ais_stream": ais_stream, "boat": b, "gps_list": self.gps_list, "gps_rows": self.gps_rows(now), "gps_default": DEFAULT_GPS, "anchor": a, "settings": self.settings,
                   "alarms": [{"id": k, "text": self.ALARM_TEXT[k], "detail": v.get("detail", ""), "since": v["since"]} for k, v in self.alarms.items()],
                   "pending": {k: now - t for k, t in self.pending.items() if k not in self.alarms},
                   "sounding": self.sounding(now), "silenced_until": self.silenced_until if self.alarms else 0,
                   "max_dist": self.max_dist, "events": list(self.events)[-40:], "track_gen": self.track_gen,
                   "push": {"configured": bool(self.notifier and self.notifier.configured),
                            "last_error": self.notifier.last_error if self.notifier else None,
                            "last_sent": self.notifier.last_sent if self.notifier else None},
                   "alive": {"configured": bool(self.alive and self.alive.configured),
                             "last_ok": self.alive.last_ok if self.alive else None,
                             "last_error": self.alive.last_error if self.alive else None,
                             "note": self.alive.sync_note if self.alive else None,
                             "every_s": self.alive.ping_every(self.settings["alive_minutes"]) if self.alive else None},
                   "nfl": {"configured": bool(self.nfl and self.nfl.configured),
                           "last_ok": self.nfl.last_ok if self.nfl else None, "last_count": self.nfl.last_count if self.nfl else 0,
                           "last_error": self.nfl.last_error if self.nfl else None,
                           "sent_t": (self.nfl.sent or {}).get("t") if self.nfl else None},
                   "nmea": {"on": self.nmea_on, "port": self.netgps.port, "error": self.netgps.error},
                   "track_points": len(self.track), "track_start": self.track[0][0] if self.track else None, "version": VERSION,
                   "gps_age": now - self.last_pos_t if self.last_pos_t else None}
            if a and pos:
                out["distance"], out["bearing"] = dist_bearing_m(a["lat"], a["lon"], pos["lat"], pos["lon"])
            ref = (pos or a or {})
        near_us = []
        net = self.netais.snapshot(now) if self.netais is not None and self.settings["internet_ais"] else None
        out["ais"] = read_ais(ais, now, ref.get("lat"), ref.get("lon"), str(self.settings["own_mmsi"]), near_us, net)
        n = self.netais
        out["net_ais"] = {"configured": bool(n and n.configured), "connected": bool(n and n.connected),
                          "last_message": n.last_message if n else None, "last_error": n.last_error if n else None,
                          "ships": len(net) if net is not None else 0}
        out["own_candidate"] = min(near_us, key=lambda t: t["dist"]) if near_us else None
        out["tide"] = self.tide.summary(now) if self.tide is not None else {"available": False}
        out["depth_plan"] = self.depth_plan(now)
        return out

    def depth_plan(self, now):
        """Depth now, lowest and highest over the next 24 h and the chain advice, from the sounder (or its last reading)
        and the tide. {"available": False, "reason": ...} when it cannot be worked out."""
        s = self.settings; series = (self.tide.data or {}).get("series") if self.tide is not None else None
        b = self.boat; live = b.get("depth") is not None
        if live: d, t = b["depth"], now
        elif self.last_depth:
            ld, here = self.last_depth, b.get("pos") or self.anchor
            far = max(150.0, 2 * self.anchor["radius"]) if self.anchor else 150.0
            if not (here and ld.get("lat") is not None and dist_bearing_m(ld["lat"], ld["lon"], here["lat"], here["lon"])[0] <= far):
                return {"available": False, "reason": "no depth reading here (sounder off; the last reading was taken elsewhere)"}
            d, t = ld["d"], ld["t"]
        else: return {"available": False, "reason": "no depth reading yet"}
        if not series: return {"available": False, "reason": "no tide data"}
        w = depth_window(series, now, d, t)
        if not w: return {"available": False, "reason": "last depth reading is older than the tide data" if not live else "tide data does not cover the next 24 h"}
        dr = float(s["draught"])
        return {"available": True, **w, "source": "sounder" if live else "last reading", "reading_t": round(t),
                "chain": chain_advice(s["chain_formula"], w["max"], s["bow_height"], s["loa"]), "formula": s["chain_formula"],
                "bow_height": s["bow_height"], "loa": s["loa"],
                "draught": dr or None, "clearance_min": round(w["min"] - dr, 2) if dr else None}

    def track_since(self, t, gen):
        with self.lock:
            if gen != self.track_gen: t = 0
            return {"gen": self.track_gen, "points": [p for p in self.track if p[0] > t]}


def _bad(key): raise ValueError(f"{key} must be digits")


def _num(c, key, lo, hi):
    v = c.get(key)
    try: v = float(v)
    except (TypeError, ValueError): raise ValueError(f"{key} must be a number")
    if not (math.isfinite(v) and lo <= v <= hi): raise ValueError(f"{key} must be between {lo} and {hi}")
    return v

# ---------------------------------------------------------------- loops and web server


async def core_info_loop(watch, host):
    """Read the Core's uptime (GET only) so its restarts show up in the GPS log."""
    while True:
        try:
            info = await asyncio.to_thread(lambda: json.load(urllib.request.urlopen(f"http://{host}:8080/info", timeout=10)))
            watch.core_info(info)
        except Exception as e: log.debug("core info: %s", e)
        await asyncio.sleep(CORE_INFO_S)


async def watch_loop(watch):
    last_save = time.time()
    while True:
        try:
            watch.tick()
            if watch.dirty and time.time() - last_save > 30: await asyncio.to_thread(watch.save); last_save = time.time()
        except Exception: log.exception("watch tick failed")
        await asyncio.sleep(1)


def sound_loop(watch):
    """Beeps on this PC while an alarm sounds (Windows only)."""
    while True:
        if winsound and watch.sounding() and watch.settings["pc_sound"]:
            try: winsound.Beep(1800, 350); winsound.Beep(1200, 350)
            except RuntimeError: time.sleep(1)
            time.sleep(0.3)
        else: time.sleep(0.5)
