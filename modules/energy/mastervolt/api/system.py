"""The manual and the version. Since 3.0 the page is the Energy module of the Drifter app; this server has no page of its own."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from .. import __version__
from ..runtime import Services
from .deps import services

router = APIRouter(tags=["system"])


@router.get("/manual")
def manual(svc: Services = Depends(services)):
    """The user manual (docs/MANUAL.md rendered by `py -m tools.build_manual`)."""
    page = svc.paths.docs / "manual.html"
    if not page.exists():
        raise HTTPException(404, detail="The manual has not been built: run py -m tools.build_manual")
    return FileResponse(page, media_type="text/html")


@router.get("/api/version")
def version():
    return {"version": __version__}
