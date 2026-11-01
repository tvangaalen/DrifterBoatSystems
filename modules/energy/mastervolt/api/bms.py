"""The three DALY BMS units: status, refresh and the guarded MOS/SOC controls (over the Bluetooth priority queue)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..bluetooth.daly_protocol import BATTERY_NAMES
from ..runtime import Services
from .deps import blocking, services

router = APIRouter(prefix="/api/bms", tags=["bms"])


class BoolReq(BaseModel):
    enabled: bool


class SocValueReq(BaseModel):
    percent: float = Field(ge=0, le=100)


def _battery_name(battery_id: int) -> str:
    if battery_id not in (1, 2, 3):
        raise HTTPException(404, detail="Unknown battery")
    return BATTERY_NAMES[battery_id - 1]


def _error_text(exc: Exception) -> str:
    return str(exc).strip() or f"{type(exc).__name__} during Bluetooth control"


async def _control(fn, *args):
    return await blocking(fn, *args, value_error=400, error=503, message=_error_text)


@router.get("")
def bms_status(svc: Services = Depends(services)):
    return svc.bms.snapshot()


@router.post("/refresh")
def refresh_all(svc: Services = Depends(services)):
    return svc.bms.refresh_all()


# The "all batteries" routes come first so that their fixed words are never read as a battery number.
@router.post("/set-all-soc/{mode}")
async def set_all_soc(mode: str, req: SocValueReq | None = None, svc: Services = Depends(services)):
    if mode == "value":
        if req is None:
            raise HTTPException(400, detail="Missing percent")
        return await _control(svc.bms.control_all, "set_soc_value", req.percent)
    action = {"100": "set_soc_100", "charge": "set_soc_charge", "discharge": "set_soc_discharge"}.get(mode)
    if not action:
        raise HTTPException(404, detail="Unknown SOC mode")
    return await _control(svc.bms.control_all, action)


@router.post("/set-all/{action}")
async def set_all(action: str, svc: Services = Depends(services)):
    mapped = {"charge-on": "charge_on", "charge-off": "charge_off", "discharge-on": "discharge_on", "discharge-off": "discharge_off"}.get(
        action
    )
    if not mapped:
        raise HTTPException(404, detail="Unknown all-battery action")
    return await _control(svc.bms.control_all, mapped)


@router.post("/{battery_id}/refresh")
def refresh_one(battery_id: int, svc: Services = Depends(services)):
    name = _battery_name(battery_id)
    try:
        return svc.bms.refresh_one(name)
    except RuntimeError as exc:
        raise HTTPException(503, detail=_error_text(exc)) from exc


@router.post("/{battery_id}/set-soc-{mode}")
async def set_soc(battery_id: int, mode: str, req: SocValueReq | None = None, svc: Services = Depends(services)):
    name = _battery_name(battery_id)
    if mode == "value":
        if req is None:
            raise HTTPException(400, detail="Missing percent")
        return await _control(svc.bms.control, name, "set_soc_value", req.percent)
    action = {"100": "set_soc_100", "charge": "set_soc_charge", "discharge": "set_soc_discharge"}.get(mode)
    if not action:
        raise HTTPException(404, detail="Unknown SOC curve")
    return await _control(svc.bms.control, name, action)


@router.post("/{battery_id}/charge")
async def charge(battery_id: int, req: BoolReq, svc: Services = Depends(services)):
    return await _control(svc.bms.control, _battery_name(battery_id), "charge", req.enabled)


@router.post("/{battery_id}/discharge")
async def discharge(battery_id: int, req: BoolReq, svc: Services = Depends(services)):
    return await _control(svc.bms.control, _battery_name(battery_id), "discharge", req.enabled)
