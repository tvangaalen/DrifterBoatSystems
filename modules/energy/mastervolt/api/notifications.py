"""Phone notifications: the Float protection and shore power notification switches (data/notifications.json, see
mastervolt/notify.py)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..runtime import Services
from .deps import services

router = APIRouter(tags=["notifications"])


class NotificationsReq(BaseModel):
    float_notification: bool | None = None
    shore_notification: bool | None = None


@router.get("/api/notifications")
def get_notifications(svc: Services = Depends(services)):
    return svc.notifier.status()


@router.post("/api/notifications")
def set_notifications(req: NotificationsReq, svc: Services = Depends(services)):
    for key, value in req.model_dump().items():
        if value is not None:
            svc.notifier.set_enabled(key, value)
    return svc.notifier.status()
