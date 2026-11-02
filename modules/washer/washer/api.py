"""The HTTP API: the routes, answers, status codes and messages of the Flask controller 3.8 (test_api_contract.py), on
FastAPI with Drifter's module contract (token from the gateway, /health, plain HTTP on 127.0.0.1)."""
from __future__ import annotations

import json, time
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from common.service import contract
from washer import EXPECTED_MODEL, VERSION, config
from washer.device import MODE_MAP, RINSE_VALUES, RUNNING, SPIN_VALUES, TEMPERATURE_VALUES, Washer
from washer.diagnostics import Diagnostics, summary
from washer.events import Events
from washer.schedule import Scheduler, now_local


class Controller:
    """Everything the API works with; tests give a fake device, clock and sleep."""

    def __init__(self, folder: Path | None = None, device_factory=None, clock=now_local, sleep=time.sleep, monotonic=time.monotonic,
                 handshake=None, pc_ip=None):
        folder = Path(folder or config.data_dir()); folder.mkdir(parents=True, exist_ok=True)
        self.started, self.sleep, self.monotonic, self.timings = time.time(), sleep, monotonic, {}
        self.events = Events()
        self.washer = Washer(folder, device_factory)
        self.schedule = Scheduler(self.washer, self.events, folder / "viomi_schedule.json", clock=clock, sleep=sleep, monotonic=monotonic)
        kw = {k: v for k, v in (("handshake", handshake), ("pc_ip", pc_ip)) if v is not None}
        self.diagnostics = Diagnostics(self.washer, self.timings, **kw)

    def uptime(self) -> str:
        s = max(0, int(time.time() - self.started)); d, s = divmod(s, 86400); h, s = divmod(s, 3600); m, _ = divmod(s, 60)
        return " ".join(([f"{d}d"] if d else []) + ([f"{h}h"] if d or h else []) + [f"{m}m"])


def create_app(c: Controller, token: str | None = None) -> FastAPI:
    app = FastAPI(title="VIOMI washer controller", version=VERSION, docs_url=None, redoc_url=None, openapi_url=None)
    contract(app, "washer", VERSION, token)
    sch, ev, w = c.schedule, c.events, c.washer

    def failed(request: Request, exc: Exception) -> JSONResponse:
        ev.log("COMMAND FAILED", f"{request.url.path} · {exc}"); return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

    @app.get("/api/status")
    def status():
        try:
            data = w.read_all(); ev.observe(data); data["schedule"] = sch.public(); return data
        except Exception as e:
            ev.offline(); return JSONResponse({"error": str(e), "diagnostics": "/"}, status_code=503)

    @app.get("/api/start-check")
    def start_check():
        """Polls briefly after Start, so that an open door (fault) shows promptly."""
        deadline, last = c.monotonic() + 3.0, None
        while c.monotonic() < deadline:
            try:
                last = w.read_all(); ev.observe(last)
                if int(last.get("fault") or 0) != 0 or int(last.get("status") or 0) in RUNNING: return last
            except Exception: pass
            c.sleep(0.35)
        return last if last is not None else JSONResponse({"error": "No status response after Start"}, status_code=503)

    @app.post("/api/power/on")
    def power_on(request: Request):
        try: w.set_property(2, 1, True); ev.log("POWER ON"); return {"ok": True}
        except Exception as e: return failed(request, e)

    @app.post("/api/power/off")
    def power_off(request: Request):
        try:
            s = sch.public(); w.set_property(2, 1, False)
            if s and s.get("status") in ("pending", "starting"): sch.cancel("Cancelled by Power Off")
            elif s and s.get("status") in ("started", "running"): sch.interrupt("Interrupted by Power Off")
            ev.log("POWER OFF"); return {"ok": True}
        except Exception as e: return failed(request, e)

    def setting(request, value, allowed, piid, label, what, extra=None):
        try:
            if value not in allowed: return JSONResponse({"ok": False, "error": f"Unsupported {label}: {value}"}, status_code=400)
            w.set_property(2, piid, value); sch.interrupt(f"Interrupted by manual SET/{what} change")
            return {"ok": True, "value": value, **(extra or {})}
        except Exception as e: return failed(request, e)

    @app.post("/api/program/{value}")
    def program(value: int, request: Request):
        return setting(request, value, MODE_MAP, 3, "program code", "program", {"program": MODE_MAP.get(value)})

    @app.post("/api/temperature/{value}")
    def temperature(value: int, request: Request): return setting(request, value, TEMPERATURE_VALUES, 6, "temperature", "temperature")

    @app.post("/api/spin/{value}")
    def spin(value: int, request: Request): return setting(request, value, SPIN_VALUES, 7, "spin speed", "spin")

    @app.post("/api/rinses/{value}")
    def rinses(value: int, request: Request): return setting(request, value, RINSE_VALUES, 9, "rinse count", "rinse")

    @app.post("/api/schedule")
    async def schedule_create(request: Request):
        try:
            try: payload = await request.json()
            except Exception: payload = {}
            payload = payload if isinstance(payload, dict) else {}
            s = sch.create(str(payload.get("mode") or "").strip().lower(), str(payload.get("time") or "").strip())
            return {"ok": True, "schedule": s}
        except Exception as e:
            ev.log("SCHEDULE FAILED", str(e)); return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    @app.post("/api/schedule/cancel")
    def schedule_cancel(): sch.cancel("Cancelled by user"); return {"ok": True}

    @app.get("/api/schedule")
    def schedule_status(): return {"ok": True, "schedule": sch.public()}

    @app.post("/api/start")
    def start(request: Request):
        try:
            s = sch.public()
            if s and s.get("status") in ("pending", "starting"): sch.cancel("Cancelled by manual Start")
            w.action(2, 1); ev.log("START / RESUME"); return {"ok": True}
        except Exception as e: return failed(request, e)

    @app.post("/api/pause")
    def pause(request: Request):
        try: w.action(2, 2); ev.log("PAUSE"); return {"ok": True}
        except Exception as e: return failed(request, e)

    @app.get("/api/diagnostics")
    def diagnostics(recheck: str | None = None):
        """The startup checks for the app; ?recheck=1 runs them again (re-reads the configuration), else the last result."""
        if recheck == "1" or c.diagnostics.last is None:
            started = time.perf_counter(); result = c.diagnostics.run()
            ev.log("DIAGNOSTICS", "OK" if result["ok"] else f"{result['critical_count']} issue(s)", int((time.perf_counter() - started) * 1000))
        else: result = c.diagnostics.last
        text, cls = summary(result)
        return {**result, "summary": text, "summary_class": cls, "controller_version": VERSION, "uptime": c.uptime(), "washer_ip": w.ip or None,
                "expected_model": EXPECTED_MODEL, "model": w.model, "firmware": w.firmware, "timings_ms": dict(c.timings)}

    @app.get("/diagnostics/export")
    def diagnostics_export():
        result = c.diagnostics.last or c.diagnostics.run()
        report = {"generated_at": datetime.now().isoformat(timespec="seconds"), "controller_version": VERSION, "controller_uptime": c.uptime(),
                  "washer_ip": w.ip, "pc_ip": result.get("pc_ip"), "expected_model": EXPECTED_MODEL, "actual_model": w.model, "firmware": w.firmware,
                  "timings_ms": dict(c.timings), "checks": result.get("checks", []), "recent_events": list(ev.items), "schedule": sch.public()}
        return Response(json.dumps(report, indent=2, ensure_ascii=False), media_type="application/json",     # never the MIoT token
                        headers={"Content-Disposition": 'attachment; filename="viomi_diagnostics.json"'})

    return app
