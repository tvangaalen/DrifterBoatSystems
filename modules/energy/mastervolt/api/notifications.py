"""Phone notifications: the Float protection notification switch (data/notifications.json, see mastervolt/notify.py)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..runtime import Services
from .deps import services

router = APIRouter(tags=["notifications"])


class NotificationsReq(BaseModel):
    float_notification: bool


@router.get("/api/notifications")
def get_notifications(svc: Services = Depends(services)):
    return svc.notifier.status()


@router.post("/api/notifications")
def set_notifications(req: NotificationsReq, svc: Services = Depends(services)):
    svc.notifier.set_float_enabled(req.float_notification)
    return svc.notifier.status()
