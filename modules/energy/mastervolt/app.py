"""The FastAPI application factory. The root `app.py` calls `create_app()` once for `uvicorn app:app`."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import routers
from .runtime import Services


def _is_benign_client_disconnect(exc) -> bool:
    """iOS/Safari/PWA may reset an HTTP socket when the app is closed. On Windows' Proactor event loop this surfaces as
    WinError 10054 during transport cleanup: harmless, and not worth a traceback in the log."""
    if isinstance(exc, ConnectionResetError):
        return getattr(exc, "winerror", None) == 10054 or getattr(exc, "errno", None) == 10054 or "10054" in str(exc)
    return False


def _install_asyncio_exception_filter() -> None:
    loop = asyncio.get_running_loop()
    previous = loop.get_exception_handler()

    def handler(loop, context):
        if _is_benign_client_disconnect(context.get("exception")):
            return
        if previous is not None:
            previous(loop, context)
        else:
            loop.default_exception_handler(context)

    loop.set_exception_handler(handler)


def create_app(services: Services | None = None) -> FastAPI:
    """Build the application. Tests pass their own `services`; production creates the real ones."""
    services = services or Services()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        _install_asyncio_exception_filter()
        await asyncio.to_thread(services.start)
        yield
        await asyncio.to_thread(services.stop)

    app = FastAPI(title="Mastervolt Energy", version=__version__, lifespan=lifespan)
    app.state.services = services
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.mount("/static", StaticFiles(directory=services.paths.static), name="static")
    for router in routers:
        app.include_router(router)
    return app
