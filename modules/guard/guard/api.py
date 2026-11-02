"""BoatGuard's API for the Drifter app, on FastAPI with Drifter's module contract (token from the gateway, /health,
plain HTTP on 127.0.0.1): the routes, answers and messages of the stdlib server of 1.x (test_api_contract.py)."""
from __future__ import annotations

import json, threading, time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from common.service import contract
from guard import VERSION


def tail(path: Path, n: int) -> list[str]:
    try: lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError: return []
    return lines[-n:]


def create_app(guard, log_path: Path, token: str | None = None) -> FastAPI:
    app = FastAPI(title="BoatGuard", version=VERSION, docs_url=None, redoc_url=None, openapi_url=None)
    contract(app, "guard", VERSION, token)
    last_test: dict = {}

    def run_test():
        last_test.clear(); last_test.update(guard.test(), finished=time.time())

    @app.get("/api/status")
    def status():
        return dict(guard.status(), camera=guard.camera_status(), last_test=last_test or None)

    @app.get("/api/log")
    def log(n: int = 200):
        return {"lines": tail(log_path, max(1, min(n, 2000)))}

    async def body(request: Request):
        """JSON only (as before); returns the body or an error answer."""
        raw = await request.body()
        if request.headers.get("content-type", "").split(";")[0].strip() != "application/json": return JSONResponse({"error": "json only"}, 415)
        try: return json.loads(raw or b"{}")
        except ValueError: return JSONResponse({"error": "invalid JSON"}, 400)

    @app.post("/api/enabled")
    async def enabled(request: Request):
        b = await body(request)
        if isinstance(b, JSONResponse): return b
        guard.set_enabled(bool(b.get("enabled"))); return {"enabled": guard.enabled}

    @app.post("/api/settings")
    async def settings(request: Request):
        b = await body(request)
        if isinstance(b, JSONResponse): return b
        try: return guard.update_settings(b)
        except ValueError as e: return JSONResponse({"error": str(e)}, 400)

    @app.post("/api/notify-test")
    async def notify_test(request: Request):
        b = await body(request)
        if isinstance(b, JSONResponse): return b
        try: return {"sent": guard.notify_test(str(b.get("event")), str(b.get("sound", "")), b.get("priority"))}
        except ValueError as e: return JSONResponse({"error": str(e)}, 400)

    @app.post("/api/test")
    async def test(request: Request):
        b = await body(request)
        if isinstance(b, JSONResponse): return b
        if guard.test_running: return JSONResponse({"error": "test already running"}, 409)
        if guard.armed_by_us: return JSONResponse({"error": "camera is armed by BoatGuard (phone away); test not possible now"}, 409)
        threading.Thread(target=run_test, daemon=True).start(); return {"started": True}

    @app.exception_handler(404)
    async def not_found(request: Request, exc):
        return JSONResponse({"error": "not found"}, 404)

    return app
