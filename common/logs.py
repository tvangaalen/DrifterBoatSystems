"""One log format for the boat's servers: date and 24-hour time, level, message. Optional rotating log file."""
from __future__ import annotations

import logging, sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from common.timefmt import STAMP

FORMAT = "%(asctime)s %(levelname)s %(message)s"


def setup(logger: logging.Logger | None = None, file=None, keep: int = 5, max_bytes: int = 1_000_000,
          level: int = logging.INFO) -> logging.Logger:
    """Logs `logger` (default: the root logger) to `file` (rotating) and to the console when there is one
    (pythonw, as used by the scheduled tasks, has none)."""
    logger = logger or logging.getLogger()
    fmt = logging.Formatter(FORMAT, STAMP)
    hs: list[logging.Handler] = []
    if file:
        Path(file).parent.mkdir(parents=True, exist_ok=True)
        hs.append(RotatingFileHandler(file, maxBytes=max_bytes, backupCount=keep, encoding="utf-8"))
    if sys.stderr: hs.append(logging.StreamHandler())
    for h in hs: h.setFormatter(fmt); logger.addHandler(h)
    logger.setLevel(level)
    return logger
