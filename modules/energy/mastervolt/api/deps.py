"""Shared helpers for the routes: the services dependency and the exception-to-HTTP mapping."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from fastapi import HTTPException, Request

from ..runtime import Services


def services(request: Request) -> Services:
    """FastAPI dependency: the application's `Services` (set on `app.state` by the factory)."""
    return request.app.state.services


async def blocking(fn: Callable, *args, value_error: int | None = None, error: int = 500, message: Callable[[Exception], str] = str):
    """Run a blocking hardware call in a worker thread and translate its failures into HTTP errors.

    `ValueError` (a rejected request: bad value, unknown name) becomes `value_error` when given; every other exception
    becomes `error`. The detail text is what the browser shows to the user.
    """
    try:
        return await asyncio.to_thread(fn, *args)
    except ValueError as exc:
        if value_error is None:
            raise HTTPException(error, detail=message(exc)) from exc
        raise HTTPException(value_error, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(error, detail=message(exc)) from exc
