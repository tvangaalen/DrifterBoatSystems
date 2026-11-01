"""The three DALY balancers (read-only over Bluetooth)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..runtime import Services
from .deps import services

router = APIRouter(prefix="/api/balancers", tags=["balancers"])


@router.get("")
def balancer_status(svc: Services = Depends(services)):
    return svc.balancers.snapshot()


@router.post("/refresh")
def refresh_all(svc: Services = Depends(services)):
    return svc.balancers.refresh_all()


@router.post("/{balancer_id}/refresh")
def refresh_one(balancer_id: int, svc: Services = Depends(services)):
    if balancer_id not in (1, 2, 3):
        raise HTTPException(404, detail="Unknown balancer")
    try:
        return svc.balancers.refresh_one(f"DL-BAL{balancer_id}")
    except Exception as exc:
        raise HTTPException(503, detail=str(exc).strip() or "Balancer refresh unavailable") from exc
