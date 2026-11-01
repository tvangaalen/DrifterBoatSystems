"""Shared helpers for the diagnostic tools."""

from __future__ import annotations

from contextlib import contextmanager

from mastervolt.masterbus.service import MasterBusService

DASH = "-"


@contextmanager
def masterbus():
    """A `MasterBusService` with the USB Link open. The web server must not be running: it needs the Link exclusively."""
    service = MasterBusService()
    service.open()
    try:
        yield service
    finally:
        service.close()


def number(value, fmt: str = ".6g") -> str:
    """A measured value for display; DASH when there is none."""
    return DASH if value is None else format(value, fmt)
