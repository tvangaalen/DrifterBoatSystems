"""The HTTP API (behind the gateway's allowlist, `enginelog` in drifter.py ROUTES):

    GET  /api/log                          {"fuel": [...], "maintenance": [...], "stats": {...}}
    GET  /api/lookup?lat=..&lon=..         {"country", "marina", "marina_distance_m", "error"}
    POST /api/fuel | /api/maintenance      create an entry; answers the entry
    POST /api/<kind>/<id>                  change it
    POST /api/<kind>/<id>/delete           delete it (the page asks first)

Wrong input answers 400 with a readable message; an unknown id 404.
"""
from __future__ import annotations

from fastapi import Body, FastAPI, HTTPException

from common.service import contract
from enginelog import VERSION
from enginelog.lookup import Lookup
from enginelog.store import KINDS, Store, fuel_stats

JSON_BODY = Body(...)      # the entry as a JSON object (validated by store.py)


def create_app(store: Store, lookup: Lookup | None = None, token: str | None = None) -> FastAPI:
    app, lookup = FastAPI(title="Engine log", version=VERSION, docs_url=None, redoc_url=None, openapi_url=None), lookup or Lookup()
    contract(app, "enginelog", VERSION, token)

    def kind_of(kind: str) -> str:
        if kind not in KINDS: raise HTTPException(404, "Unknown entry kind")
        return kind

    def guarded(fn):
        try: return fn()
        except ValueError as e: raise HTTPException(400, str(e)) from None
        except KeyError: raise HTTPException(404, "No such entry (deleted?)") from None

    @app.get("/api/log")
    def log():
        d = store.all()
        return {**d, "stats": fuel_stats(d["fuel"])}

    @app.get("/api/lookup")
    def place(lat: float, lon: float):
        if not (-90 <= lat <= 90 and -180 <= lon <= 180): raise HTTPException(400, "lat/lon out of range")
        return lookup.place(lat, lon)

    @app.post("/api/{kind}")
    def create(kind: str, body: dict = JSON_BODY):
        return guarded(lambda: store.create(kind_of(kind), body))

    @app.post("/api/{kind}/{entry_id}")
    def update(kind: str, entry_id: str, body: dict = JSON_BODY):
        return guarded(lambda: store.update(kind_of(kind), entry_id, body))

    @app.post("/api/{kind}/{entry_id}/delete")
    def delete(kind: str, entry_id: str):
        guarded(lambda: store.delete(kind_of(kind), entry_id))
        return {"ok": True}

    return app
