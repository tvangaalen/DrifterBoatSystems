"""Bluetooth diagnostics: who holds the radio, and the event log with per-device counters and timings."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..bluetooth.events import ble_log
from ..runtime import Services
from .deps import services

router = APIRouter(prefix="/api", tags=["bluetooth"])


@router.get("/bluetooth-coordinator")
def coordinator_status(svc: Services = Depends(services)):
    return svc.coordinator.snapshot()


@router.get("/bluetooth-events")
def events(limit: int = 100):
    return ble_log.snapshot(limit)
