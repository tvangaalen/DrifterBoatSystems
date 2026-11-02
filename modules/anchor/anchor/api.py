"""The anchor watch's HTTP API on FastAPI (2.0; the stdlib server of 1.17 until then), under the module contract
(common/service.py: X-Drifter-Token, /health, 127.0.0.1). Only the Drifter gateway calls it; the answers are the same
as 1.17's (test_api_contract.py): state, track, commands and map tiles."""
import json

from fastapi import FastAPI, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from anchor.settings import VERSION, log
from anchor.tiles import TILE_RE, TileCache
from common.service import contract

MAX_COMMAND = 10000          # bytes: a command is a small JSON object


def _json(obj, code=200):
    return Response(json.dumps(obj, default=lambda o: None), status_code=code, media_type="application/json")   # odd values as null


def _text(body: bytes, code=404, cache=None):
    return Response(body, status_code=code, media_type="text/plain", headers={"Cache-Control": cache} if cache else None)


def create_app(watch, tiles, token=None) -> FastAPI:
    app = contract(FastAPI(title="Anchor watch", version=VERSION, docs_url=None, redoc_url=None, openapi_url=None), "anchor", VERSION, token)

    @app.get("/api/state")
    def state(): return _json(watch.state())

    @app.get("/api/track")
    def track(request: Request):
        q = request.query_params
        try: return _json(watch.track_since(float(q.get("since", 0)), int(q.get("gen", -1))))
        except ValueError: return _json({"error": "bad query"}, 400)

    @app.get("/tiles/{rest:path}")
    def tile(request: Request):            # fetched on demand by TileCache, in the thread pool (it may wait on the tile server)
        m = TILE_RE.match(request.url.path)
        if not (m and m[1] in TileCache.SOURCES): return _text(b"not found")
        t = tiles.get(m[1], int(m[2]), int(m[3]), int(m[4]))
        if t: return Response(t[0], media_type=t[1], headers={"Cache-Control": "max-age=86400"})
        return _text(b"", cache="max-age=300")

    @app.post("/api/command")
    async def command(request: Request):
        try:
            body = await request.body()
            if len(body) > MAX_COMMAND: raise ValueError("request too large")
            await run_in_threadpool(watch.command, json.loads(body or b"{}"))
            return _json({"ok": True, "state": await run_in_threadpool(watch.state)})
        except ValueError as e: return _json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            log.exception("command failed"); return _json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)

    @app.exception_handler(404)
    async def not_found(request, exc): return _text(b"not found")

    return app
