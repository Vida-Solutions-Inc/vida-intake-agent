"""Logging: a daily rotating file in the OS log dir, plus optional console.

A small in-memory ring buffer of recent events is also exposed so the tray app
and ``intake status`` can show "what happened lately" without parsing the log.
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import date
from typing import Deque

from .platform_utils import log_dir

_RING: Deque[str] = deque(maxlen=200)
_CONFIGURED = False


class _RingHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            _RING.append(self.format(record))
        except Exception:
            pass


def get_logger(console: bool = True) -> logging.Logger:
    global _CONFIGURED
    logger = logging.getLogger("intake")
    if _CONFIGURED:
        return logger

    logger.setLevel(logging.INFO)
    log_file = log_dir() / f"intake_{date.today().isoformat()}.log"

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s"))
    logger.addHandler(fh)

    ring = _RingHandler()
    ring.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))
    logger.addHandler(ring)

    if console:
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))
        logger.addHandler(sh)

    _CONFIGURED = True
    return logger


def recent_events(n: int = 20) -> list[str]:
    return list(_RING)[-n:]
