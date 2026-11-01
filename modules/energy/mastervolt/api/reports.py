"""The battery health report (runs in a separate low-priority process, one at a time)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..runtime import Services
from .deps import services

router = APIRouter(prefix="/api/reports", tags=["reports"])


class ReportReq(BaseModel):
    days: int = Field(ge=1, le=365)


@router.post("/battery-health")
def start_battery_report(req: ReportReq, svc: Services = Depends(services)):
    try:
        return svc.reports.start(req.days)
    except RuntimeError as exc:
        raise HTTPException(409, detail=str(exc)) from exc


@router.get("/battery-health")
def battery_report_status(svc: Services = Depends(services)):
    return svc.reports.status()
