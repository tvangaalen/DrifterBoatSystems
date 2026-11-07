"""Phone notifications: the Float protection and shore power notification switches, priority and sound (data/notifications.json, see
mastervolt/notify.py)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..runtime import Services
from .deps import services

router = APIRouter(tags=["notifications"])


class NotificationsReq(BaseModel):
    float_notification: bool | None = None
    shore_notification: bool | None = None
    prefs: dict | None = None        # {"float"|"shore": {"priority": -2..1, "sound": a Pushover sound}}


@router.get("/api/notifications")
def get_notifications(svc: Services = Depends(services)):
    return svc.notifier.status()


@router.post("/api/notifications")
def set_notifications(req: NotificationsReq, svc: Services = Depends(services)):
    if req.prefs is not None:
        try:
            svc.notifier.set_prefs(req.prefs)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
    for key, value in req.model_dump(exclude={"prefs"}).items():
        if value is not None:
            svc.notifier.set_enabled(key, value)
    return svc.notifier.status()
