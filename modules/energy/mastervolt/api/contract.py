"""The Drifter module contract (Drifter Boat Systems, refactoring phase 3), added by `python -m mastervolt`.

MasterVolt keeps its own copy instead of importing Drifter's `common/service.py` (it stays a package of its own), but
the contract is the same for every module:

* plain HTTP on 127.0.0.1: only the Drifter gateway on this PC talks to the server, and the gateway serves HTTPS;
* every request but `GET /health` must carry `X-Drifter-Token` equal to `DRIFTER_TOKEN`, which drifterd makes at its
  start and gives to the gateway and every module. Without the variable everything but `/health` is refused (fail
  closed), so a page in a browser can neither send commands nor read the API, whatever the host name;
* `GET /health` answers `{"ok", "module", "version", "uptime_s"}` for drifterd's health check;
* JSON answers are never cached.

`create_app()` itself is unchanged, so the golden API tests still compare it with the hardware-verified release.
"""

from __future__ import annotations

import logging
import os
import secrets
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .. import __version__

TOKEN_ENV = "DRIFTER_TOKEN"
TOKEN_HEADER = "X-Drifter-Token"
logger = logging.getLogger("mastervolt.contract")


def add_contract(app: FastAPI, token: str | None = None) -> FastAPI:
    """Add the token check, `/health` and no-store to `app`. `token` defaults to $DRIFTER_TOKEN."""
    token = token if token is not None else os.environ.get(TOKEN_ENV, "").strip()
    started = time.time()
    if not token:
        logger.warning("No %s set: every request but /health is refused", TOKEN_ENV)

    @app.middleware("http")
    async def check_token(request: Request, call_next):
        if request.url.path != "/health":
            given = request.headers.get(TOKEN_HEADER, "")
            if not token or not secrets.compare_digest(given, token):
                return JSONResponse({"ok": False, "error": "Request not sent by the Drifter gateway"}, status_code=403)
        response = await call_next(request)
        if response.headers.get("content-type", "").startswith("application/json"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health", include_in_schema=False)
    def health():
        return {"ok": True, "module": "energy", "version": __version__, "uptime_s": round(time.time() - started)}

    return app
