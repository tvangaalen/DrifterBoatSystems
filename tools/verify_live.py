"""After a deploy or restart: is everything live really back? Read-only GETs only, one line per check, in seconds.

    py -3.12 tools/verify_live.py [module ...] [--wait 240] [--config C:\\Drifter\\config.json]

Modules: gateway, energy, anchor, guard, washer, enginelog (default: all). Per module: /health on 127.0.0.1 (version, uptime), a
403 without the token (the module contract), the supervisor's state and health check, the gateway's upstream state, and
what that module needs to be useful: energy - all 3 BMS units connected, no BMS control busy, Float not latched; anchor -
Orca Core connected, network GPS (NMEA) listening, Pushover and still-alive configured, no alarm; guard - router and
camera reachable; washer - its status answers (the device can be slow for a moment). Checks that can still come right (the BMS units take ~2 minutes after a
restart) are retried until --wait runs out; the rest are not. Never sends a command. Exit code = number of failed checks.
"""
from __future__ import annotations

import argparse, json, socket, ssl, sys, time, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAMES = ("gateway", "energy", "anchor", "guard", "washer", "enginelog")
UPSTREAM = {"energy": "power", "anchor": "anchor", "guard": "guard", "washer": "washer", "enginelog": "enginelog"}   # the gateway's names
PROBE = {"energy": "/api/energy", "anchor": "/api/state", "guard": "/api/status", "washer": "/api/status", "enginelog": "/api/log"}   # must say 403


def need(ok, text): return (bool(ok), text)


# Module-specific checks: payloads (as the gateway passes them on) -> [(ok, text)]. Pure functions, tested on their own.
def check_energy(bms: dict, energy: dict) -> list:
    n, total = bms.get("connected_count"), len(bms.get("batteries") or {})
    return [need(n == total and total == 3, f"BMS units connected: {n}/{total}"), need(bms.get("ble_available"), "Bluetooth available"),
            need(not (bms.get("control_status") or {}).get("busy"), "no BMS control busy"),
            need(not (energy.get("high_soc_float_policy") or {}).get("float_latched"), "Float not latched")]


def check_anchor(state: dict) -> list:
    core, nmea, push, alive = (state.get(k) or {} for k in ("core", "nmea", "push", "alive"))
    alarms = state.get("alarms") or []
    return [need(core.get("connected"), f"Orca Core connected{'' if core.get('connected') else ': ' + str(core.get('last_error'))}"),
            need(nmea.get("on") and not nmea.get("error"), f"network GPS (NMEA) on :{nmea.get('port')}"),
            need(push.get("configured"), "Pushover configured"), need(alive.get("configured"), "still-alive configured"),
            need(not alarms, "no anchor alarm" if not alarms else "ALARM: " + ", ".join(a.get("text", "?") for a in alarms))]


def check_guard(status: dict) -> list:
    cam = status.get("camera") or {}
    return [need(status.get("router_ok"), "router reachable"), need(cam.get("online"), f"camera online (battery {cam.get('battery')}%)")]


def check_washer(status: dict) -> list:
    return [need("status_text" in status, f"washer answers: {status.get('power_text', '?')}, {status.get('status_text', '?')}")]


# Right after a restart a server does not answer yet, the supervisor says "starting" and the gateway has not polled it yet:
# those come right by themselves, so they are retried too. A 200 without the token, Float latched or an alarm is not.
WARN_DAYS = 60                                      # a certificate this close to its end fails the check


def cert_end(f) -> float:
    """When the PEM certificate in `f` ends (seconds since the epoch)."""
    return ssl.cert_time_to_seconds(ssl._ssl._test_decode_cert(str(f))["notAfter"])


def check_certificates(files: dict, now: float | None = None, end_of=cert_end) -> list:
    """files: name -> PEM path. Fails a certificate that is missing or ends within WARN_DAYS (the app and the CA: an
    expired one locks every phone out until it is renewed)."""
    out, now = [], now or time.time()
    for name, f in files.items():
        try: end = end_of(f)
        except (OSError, KeyError, ValueError, ssl.SSLError): out.append(need(False, f"{name} certificate unreadable: {f}")); continue
        days = (end - now) / 86400
        out.append(need(days > WARN_DAYS, f"{name} certificate valid until {time.strftime('%Y-%m-%d', time.localtime(end))}"
                                         + ("" if days > WARN_DAYS else f" ({max(0, days):.0f} days left: renew it, docs/RUNBOOK.md)")))
    return out


RETRY = {"BMS units connected", "Bluetooth available", "Orca Core connected", "router reachable", "camera online", "washer answers",
         "/health: no answer", "supervisor:", "gateway reaches it", "app answers", "drifterd None"}


def retryable(text: str) -> bool:
    return any(text.startswith(p) for p in RETRY) or text.endswith("(HTTP 0)")   # HTTP 0: no answer yet


class Live:
    def __init__(self, cfg: dict, specs: dict):
        self.base = f"https://{cfg['bind']}:{cfg['port']}"
        ca = cfg.get("ca_file")
        self.ctx = ssl.create_default_context(cafile=ca) if ca and Path(ca).exists() else ssl._create_unverified_context()
        self.specs = specs
        self.certs = {}                                 # name -> PEM file, set by main()

    def get(self, url: str, timeout=10):
        """(status, parsed JSON or None); status 0 = no answer."""
        try:
            with urllib.request.urlopen(url, timeout=timeout, context=self.ctx if url.startswith("https") else None) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e: return e.code, None
        except (OSError, ValueError): return 0, None

    def gw(self, path): return self.get(self.base + path)

    def module(self, name: str, systems: dict) -> list:
        out, port = [], self.specs[name]["port"]
        if name == "gateway":
            code, _ = self.gw("/api/systems")
            sup = (systems.get("supervisor") or {})
            return [need(code == 200, f"app answers on {self.base}"), need((sup.get("drifterd") or {}).get("version"), f"drifterd {(sup.get('drifterd') or {}).get('version')}")] \
                + check_certificates(self.certs)
        code, h = self.get(f"http://127.0.0.1:{port}/health")
        out.append(need(code == 200 and h and h.get("ok"), f"/health: {h.get('version')} up {h.get('uptime_s')} s" if h else f"/health: no answer (HTTP {code})"))
        code, _ = self.get(f"http://127.0.0.1:{port}{PROBE[name]}")
        out.append(need(code == 403, f"refused without token (HTTP {code})"))
        m = ((systems.get("supervisor") or {}).get("modules") or {}).get(name) or {}
        out.append(need(m.get("state") == "running" and (m.get("health") or {}).get("ok"), f"supervisor: {m.get('state')}, health {(m.get('health') or {}).get('detail')}"))
        up = (systems.get("upstream") or {}).get(UPSTREAM[name]) or {}
        out.append(need(up.get("ok"), f"gateway reaches it{'' if up.get('ok') else ': ' + str(up.get('error'))}"))
        p = f"/api/{UPSTREAM[name]}"
        if name == "energy": out += check_energy(self.gw(p + "/api/bms")[1] or {}, self.gw(p + "/api/energy")[1] or {})
        elif name == "anchor":
            out += check_anchor(self.gw(p + "/api/state")[1] or {})
            out.append(need(_listens((self.specs["anchor"].get("lan") or "")), "NMEA port accepts TCP"))
        elif name == "guard": out += check_guard(self.gw(p + "/api/status")[1] or {})
        elif name == "washer": out += check_washer(self.gw(p + "/api/status")[1] or {})
        elif name == "enginelog":
            log = self.gw(p + "/api/log")[1] or {}
            out.append(need("fuel" in log and "maintenance" in log, f"log answers: {len(log.get('fuel') or [])} fills, {len(log.get('maintenance') or [])} maintenance"))
        return out


def _listens(addr: str) -> bool:
    if not addr: return True
    host, port = addr.rsplit(":", 1)
    try:
        with socket.create_connection((host, int(port)), timeout=3): return True
    except OSError: return False


def specs(cfg: dict) -> dict:
    m = json.loads((ROOT / "modules.json").read_text(encoding="utf-8"))["modules"]
    out = {n: {"port": m[n]["port"]} for n in NAMES}
    out["anchor"]["lan"] = f"{cfg['bind']}:10110"
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("modules", nargs="*", metavar="module", help=", ".join(NAMES) + " (default: all)")
    ap.add_argument("--wait", type=float, default=240, help="seconds to keep retrying checks that can still come right (default 240)")
    ap.add_argument("--config", default=r"C:\Drifter\config.json", help="the live gateway config (bind, port, ca_file)")
    a = ap.parse_args(argv)
    names = a.modules or list(NAMES)
    if bad := [n for n in names if n not in NAMES]: ap.error(f"unknown module: {', '.join(bad)}")
    cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))
    live, deadline, t0 = Live(cfg, specs(cfg)), time.time() + a.wait, time.time()
    home = Path(a.config).parent
    live.certs = {"app": home / cfg.get("certfile", "certs/drifter-cert.pem"), "Mastervolt Local CA": home / "modules/energy/certs/ca-cert.pem"}
    while True:
        systems = live.gw("/api/systems")[1] or {}
        results = {n: live.module(n, systems) for n in names}
        pending = [t for r in results.values() for ok, t in r if not ok and retryable(t)]
        hard = [t for r in results.values() for ok, t in r if not ok and not retryable(t)]
        if not pending or hard or time.time() >= deadline: break
        time.sleep(10)
    failed = 0
    for n, r in results.items():
        for ok, text in r:
            failed += not ok
            print(f"{'ok  ' if ok else 'FAIL'} {n:8} {text}")
    print(f"\n{'all ' + str(sum(len(r) for r in results.values())) + ' checks ok' if not failed else str(failed) + ' failed'} ({time.time() - t0:.0f} s)")
    return failed


if __name__ == "__main__":
    sys.exit(main())
