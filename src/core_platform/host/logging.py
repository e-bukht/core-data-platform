from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(*, level: str, json_logs: bool) -> None:
    """Configure structured application logging at the host boundary."""
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper(), force=True)
    renderer = structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
