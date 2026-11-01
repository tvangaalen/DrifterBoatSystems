"""Switching the MasterBus devices. Each route writes, reads back and reports; failures carry the verify details."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..runtime import Services
from .deps import blocking, services

router = APIRouter(prefix="/api/control", tags=["control"])


class BoolReq(BaseModel):
    enabled: bool


class LimitReq(BaseModel):
    amps: int = Field(ge=3, le=15)


class ModeReq(BaseModel):
    mode: str


@router.post("/inverter")
async def inverter(req: BoolReq, svc: Services = Depends(services)):
    svc.masterbus.controls.clear_active_mode()
    return await blocking(svc.masterbus.controls.set_inverter, req.enabled)


@router.post("/charger")
async def charger(req: BoolReq, svc: Services = Depends(services)):
    svc.masterbus.controls.clear_active_mode()
    return await blocking(svc.masterbus.controls.set_charger, req.enabled)


@router.post("/ac-limit")
async def ac_limit(req: LimitReq, svc: Services = Depends(services)):
    svc.masterbus.controls.clear_active_mode()
    return await blocking(svc.masterbus.controls.set_ac_limit, req.amps, value_error=400)


@router.post("/ac-support")
async def ac_support(req: BoolReq, svc: Services = Depends(services)):
    svc.masterbus.controls.clear_active_mode()
    return await blocking(svc.masterbus.controls.set_ac_support, req.enabled, error=409)


@router.post("/mode")
async def operating_mode(req: ModeReq, svc: Services = Depends(services)):
    return await blocking(svc.masterbus.controls.set_operating_mode, req.mode, value_error=400, error=409)


@router.post("/device/{name}")
async def device_control(name: str, req: BoolReq, svc: Services = Depends(services)):
    svc.masterbus.controls.clear_active_mode()
    return await blocking(svc.masterbus.controls.set_device_control, name, req.enabled, value_error=400, error=409)


@router.post("/alternator")
async def alternator_control(req: BoolReq, svc: Services = Depends(services)):
    svc.masterbus.controls.clear_active_mode()
    return await blocking(svc.masterbus.controls.set_alternator_enabled, req.enabled, error=409)
