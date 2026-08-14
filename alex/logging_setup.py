"""
Structured, rotating logging for ALEX.

Every module should do `log = logging.getLogger(__name__)` and let this
module own handler/formatter setup, called once from alex.main at startup.
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from alex.config import Settings

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-28s | %(message)s"


def setup_logging(settings: Settings) -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    formatter = logging.Formatter(_LOG_FORMAT)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    log_file = settings.log_dir / "alex.log"
    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # Quiet down noisy third-party libraries unless we're debugging.
    if level > logging.DEBUG:
        for noisy in ("httpx", "httpcore", "uvicorn.access", "asyncio"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.getLogger(__name__).info(
        "Logging initialized (level=%s, file=%s)", settings.log_level, log_file
    )
