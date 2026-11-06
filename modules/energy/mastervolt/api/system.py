"""The version. Since 3.0 the page is the Energy module of the Drifter app; this server has no page of its own (the manual was
removed in 2026-11: new ones per tab will follow)."""

from __future__ import annotations

from fastapi import APIRouter

from .. import __version__

router = APIRouter(tags=["system"])


@router.get("/api/version")
def version():
    return {"version": __version__}
