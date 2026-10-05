from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from opentelemetry.trace import Span
from starlette.requests import Request
from starlette.types import Scope

from core_platform.host.sensitive_data import (
    REDACTED,
    is_sensitive_query_key,
)


def sanitize_url(url: str) -> str:
    parts = urlsplit(url)

    if not parts.query:
        return url

    query = [
        (
            key,
            REDACTED if is_sensitive_query_key(key) else value,
        )
        for key, value in parse_qsl(
            parts.query,
            keep_blank_values=True,
        )
    ]

    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query),
            parts.fragment,
        )
    )


def sanitize_http_server_span(
    span: Span,
    scope: Scope,
) -> None:
    if not span.is_recording():
        return

    sanitized_url = sanitize_url(str(Request(scope).url))

    # Support both legacy and stable HTTP semantic-convention attribute names.
    span.set_attribute("http.url", sanitized_url)
    span.set_attribute("url.full", sanitized_url)