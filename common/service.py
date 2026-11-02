"""The module contract for the FastAPI module servers (refactoring phase 3: the washer first, then BoatGuard, the anchor
watch and MasterVolt). Needs FastAPI and uvicorn, so only those modules import it; the rest of common/ is stdlib.

- Plain HTTP on 127.0.0.1 only (net.check_bind): only the Drifter gateway on this PC talks to a module.
- Every request but GET /health must carry X-Drifter-Token = DRIFTER_TOKEN, which drifterd makes at its start and gives
  to the gateway and every module in their environment. Without the variable a module refuses everything but /health
  (fail closed). A page in a browser cannot know the token, so neither cross-site requests nor DNS rebinding reach a
  module; the gateway keeps its own host, origin and CSRF checks for the app.
- GET /health: {"ok": true, "module", "version", "uptime_s"} for drifterd's health check (no token: it says nothing).
- JSON answers are never cached.
"""
from __future__ import annotations

import logging, os, secrets, time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from common import net

TOKEN_ENV, TOKEN_HEADER = "DRIFTER_TOKEN", "X-Drifter-Token"
log = logging.getLogger("drifter")


def contract(app: FastAPI, module: str, version: str, token: str | None = None) -> FastAPI:
    """Adds the token check, /health and no-store to `app`. `token` defaults to $DRIFTER_TOKEN."""
    token = token if token is not None else os.environ.get(TOKEN_ENV, "").strip()
    started = time.time()
    if not token: log.warning("%s: no %s set: every request but /health is refused", module, TOKEN_ENV)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if request.url.path != "/health":
            given = request.headers.get(TOKEN_HEADER, "")
            if not token or not secrets.compare_digest(given, token):
                return JSONResponse({"ok": False, "error": "Request not sent by the Drifter gateway"}, status_code=403)
        response = await call_next(request)
        if response.headers.get("content-type", "").startswith("application/json"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health")
    def health():
        return {"ok": True, "module": module, "version": version, "uptime_s": round(time.time() - started)}

    return app


def start(app: FastAPI, host: str, port: int):
    """Serve in a daemon thread (for a module whose main thread runs its own asyncio loops, like the anchor watch);
    returns the uvicorn server: set `.should_exit = True` to stop it."""
    import threading, uvicorn
    server = uvicorn.Server(uvicorn.Config(app, host=net.check_bind(host, "bind"), port=port, log_config=None, access_log=False,
                                           timeout_graceful_shutdown=5))
    threading.Thread(target=server.run, name="api", daemon=True).start()
    return server


def run(app: FastAPI, port: int, bind_env: str) -> None:
    """Serve on 127.0.0.1 (or another private address in $bind_env, never a public one), plain HTTP."""
    import uvicorn
    host = net.check_bind(os.environ.get(bind_env) or "127.0.0.1", bind_env)
    uvicorn.run(app, host=host, port=port, log_config=None, access_log=False, timeout_graceful_shutdown=5)
