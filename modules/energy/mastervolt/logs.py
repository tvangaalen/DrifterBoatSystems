"""Application logging: console + a rotating file (`logs/server.log`), and a helper that keeps repeating errors quiet.

Background loops (history recording, MasterBus polling) must never crash because one pass failed, but they must not
fail *silently* either: `warn_once` logs the first occurrence of each problem with its traceback and then at most
once every few minutes, so a persistent fault is visible without flooding the console.
"""

from __future__ import annotations

import logging
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_last: dict[str, float] = {}


def configure(log_file: Path | None = None) -> None:
    """Idempotent: add the console handler and (optionally) the rotating file to the `mastervolt` logger."""
    logger = logging.getLogger("mastervolt")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(FORMAT))
    logger.addHandler(console)
    if log_file:
        try:
            Path(log_file).parent.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
            handler.setFormatter(logging.Formatter(FORMAT))
            logger.addHandler(handler)
        except OSError:
            pass  # logging to a file is a convenience; the console log remains


def warn_once(logger: logging.Logger, key: str, message: str, *, every: float = 300.0, exc_info: bool = True) -> None:
    """Log `message` (with the active exception) unless the same `key` was logged within the last `every` seconds."""
    now = time.monotonic()
    if now - _last.get(key, -every) >= every:
        _last[key] = now
        logger.warning(message, exc_info=exc_info)
