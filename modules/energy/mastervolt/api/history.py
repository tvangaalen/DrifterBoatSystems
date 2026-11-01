"""The measurement history: chart data (from the server-side cache), totals, raw series and the export."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from ..runtime import Services
from .deps import services

router = APIRouter(prefix="/api/history", tags=["history"])


def _retention_days(svc: Services) -> int:
    return svc.masterbus.get_settings()["history_retention_days"]


@router.get("/status")
def status(svc: Services = Depends(services)):
    return svc.history.db_status(_retention_days(svc))


@router.get("")
def latest(limit: int = 100, svc: Services = Depends(services)):
    return {"count": svc.history.count(), "retention_days": _retention_days(svc), "records": svc.history.latest(limit)}


@router.get("/bms-series")
def bms_series(after_id: int = 0, svc: Services = Depends(services)):
    result = svc.history.bms_series(after_id)
    result["retention_days"] = _retention_days(svc)
    return result


@router.get("/dashboard-series")
def dashboard_series(after_id: int = 0, svc: Services = Depends(services)):
    result = svc.history.dashboard_series(after_id)
    result["retention_days"] = _retention_days(svc)
    return result


def _chart_data(svc: Services, hours: float | None, refresh: bool) -> dict:
    maximum = float(_retention_days(svc) * 24)
    zoom = maximum if hours is None else float(hours)
    if zoom < 0.25 or zoom > maximum:
        raise HTTPException(400, detail=f"Zoom must be between 0.25 and {maximum:g} hours")
    result = svc.history.chart_data(zoom, refresh)
    result.update({"zoom_hours": zoom, "max_hours": maximum, "server_cached": True})
    return result


@router.get("/chart-data")
def chart_data(hours: float | None = None, svc: Services = Depends(services)):
    return _chart_data(svc, hours, False)


@router.post("/chart-data/update")
def update_chart_data(hours: float | None = None, svc: Services = Depends(services)):
    return _chart_data(svc, hours, True)


@router.get("/export")
def export(svc: Services = Depends(services)):
    return StreamingResponse(
        svc.history.json_lines(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": "attachment; filename=mastervolt-history.jsonl"},
    )


@router.get("/contributions")
def contributions(start: str, end: str, svc: Services = Depends(services)):
    try:
        return svc.history.contributions(start, end)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
