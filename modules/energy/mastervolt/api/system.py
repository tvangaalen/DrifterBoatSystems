"""The web app shell: the page, its PWA files, the local CA certificate and the version."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from .. import __version__
from ..runtime import Services
from .deps import services

router = APIRouter(tags=["system"])


@router.get("/")
def root(svc: Services = Depends(services)):
    return FileResponse(svc.paths.static / "index.html")


@router.get("/manifest.webmanifest")
def manifest(svc: Services = Depends(services)):
    return FileResponse(svc.paths.static / "manifest.webmanifest", media_type="application/manifest+json")


@router.get("/service-worker.js")
def service_worker(svc: Services = Depends(services)):
    return FileResponse(svc.paths.static / "service-worker.js", media_type="application/javascript")


@router.get("/manual")
def manual(svc: Services = Depends(services)):
    """The user manual (docs/MANUAL.md rendered by `py -m tools.build_manual`)."""
    page = svc.paths.docs / "manual.html"
    if not page.exists():
        raise HTTPException(404, detail="The manual has not been built: run py -m tools.build_manual")
    return FileResponse(page, media_type="text/html")


@router.get("/local-ca.cer")
def local_ca(svc: Services = Depends(services)):
    """The private CA certificate, so a phone can be set up to trust the server's HTTPS certificate (docs/local-https.md)."""
    certificate = svc.paths.certs / "Mastervolt-Local-CA.cer"
    if not certificate.exists():
        raise HTTPException(404, detail="Local CA certificate has not been generated")
    return FileResponse(certificate, media_type="application/pkix-cert", filename="Mastervolt-Local-CA.cer")


@router.get("/api/version")
def version():
    return {"version": __version__}
