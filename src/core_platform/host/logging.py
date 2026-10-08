from __future__ import annotations

import logging
import sys
from collections.abc import Mapping

import structlog
from opentelemetry import trace
from structlog.typing import EventDict, WrappedLogger

from core_platform.host.sensitive_data import (
    REDACTED as _REDACTED,
)
from core_platform.host.sensitive_data import (
    is_sensitive_key as _is_sensitive_key,
)


def _redact_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            key: (
                _REDACTED
                if isinstance(key, str) and _is_sensitive_key(key)
                else _redact_value(nested_value)
            )
            for key, nested_value in value.items()
        }

    if isinstance(value, list):
        return [_redact_value(item) for item in value]

    if isinstance(value, tuple):
        return tuple(_redact_value(item) for item in value)

    return value


def _redact_sensitive_data(
    logger: WrappedLogger,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    del logger, method_name

    for key, value in tuple(event_dict.items()):
        if _is_sensitive_key(key):
            event_dict[key] = _REDACTED
        else:
            event_dict[key] = _redact_value(value)

    return event_dict


def _add_trace_context(
    logger: WrappedLogger,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    del logger, method_name

    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return event_dict

    event_dict["trace_id"] = f"{span_context.trace_id:032x}"
    event_dict["span_id"] = f"{span_context.span_id:016x}"
    return event_dict


def configure_logging(*, level: str, json_logs: bool) -> None:
    """Configure structured application logging at the host boundary."""
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level.upper(),
        force=True,
    )

    # HTTP request telemetry is provided by OpenTelemetry spans.
    # Suppress third-party INFO request logs because they may contain raw URLs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    renderer = structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _redact_sensitive_data,
            _add_trace_context,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
