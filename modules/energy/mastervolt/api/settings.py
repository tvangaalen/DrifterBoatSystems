"""User settings. The request model is generated from the settings table, so the limits live in one place."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, create_model

from ..runtime import Services
from ..settings import SETTINGS
from .deps import services

router = APIRouter(tags=["settings"])


def _request_model():
    fields = {}
    for setting in SETTINGS:
        if setting.kind is bool:
            fields[setting.name] = (bool, ...)
        else:
            fields[setting.name] = (setting.kind, Field(..., ge=setting.low, le=setting.high))
    return create_model("SettingsReq", **fields)


SettingsReq = _request_model()


@router.get("/api/settings")
def get_settings(svc: Services = Depends(services)):
    return svc.masterbus.get_settings()


@router.post("/api/settings")
def save_settings(req: SettingsReq, svc: Services = Depends(services)):
    try:
        return svc.masterbus.update_settings(req.model_dump())
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, detail=str(exc)) from exc
