"""The HTTP API (behind the gateway's allowlist, `enginelog` in drifter.py ROUTES):

    GET  /api/log                          {"fuel", "maintenance", "alarms", "stats", "settings", "engine", "schedule"}
    POST /api/fuel | /api/maintenance      create an entry; answers the entry
    POST /api/<kind>/<id>                  change it
    POST /api/<kind>/<id>/delete           delete it (the page asks first)
    POST /api/alarms/<id>/delete           delete a logged engine alarm (the page asks first)
    POST /api/settings                     {"tank_capacity_l": litres or null, "temp_high_c", "oil_low_bar"}

Wrong input answers 400 with a readable message; an unknown id 404.
"""
from __future__ import annotations

from datetime import date

from fastapi import Body, FastAPI, HTTPException

from common.service import contract
from enginelog import VERSION
from enginelog.schedule import status as schedule_status
from enginelog.store import KINDS, Store, fuel_stats

JSON_BODY = Body(...)      # the entry as a JSON object (validated by store.py)


def create_app(store: Store, engine=None, token: str | None = None) -> FastAPI:
    """`engine`: the live engine reader (engine.py), None in tests that do not need it."""
    app = FastAPI(title="Engine log", version=VERSION, docs_url=None, redoc_url=None, openapi_url=None)
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
        e = engine.snapshot() if engine else {"connected": False, "error": "not started", "fresh": False, "running": False,
                                              "last_hours": store.engine().get("hours"), "last_hours_at": store.engine().get("t")}
        hours = e.get("hours") if e.get("fresh") and e.get("hours") is not None else e.get("last_hours")     # the meter now, else its last reading
        return {**d, "stats": fuel_stats(d["fuel"]), "settings": store.settings(), "engine": e,
                "schedule": schedule_status(d["maintenance"], hours, date.today())}

    @app.post("/api/settings")
    def settings(body: dict = JSON_BODY):
        return guarded(lambda: store.set_settings(body))

    @app.post("/api/alarms/{alarm_id}/delete")
    def delete_alarm(alarm_id: str):
        guarded(lambda: store.delete_alarm(alarm_id))
        return {"ok": True}

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
