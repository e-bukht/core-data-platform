from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from core_platform.foundation.errors import PlatformError


async def platform_error_handler(request: Request, exc: PlatformError) -> JSONResponse:
    status_code = 400
    if exc.category.value == "not_found":
        status_code = 404
    elif exc.category.value in {"authentication", "authorization"}:
        status_code = 401 if exc.category.value == "authentication" else 403
    elif exc.category.value == "concurrency":
        status_code = 409

    headers: dict[str, str] = {}
    settings = getattr(request.app.state, "settings", None)
    correlation_id = exc.correlation_id
    if correlation_id is None:
        state_correlation = getattr(request.state, "correlation_id", None)
        correlation_id = str(state_correlation) if state_correlation is not None else None
    if settings is not None and correlation_id is not None:
        headers[settings.correlation_header] = correlation_id
    if exc.category.value == "authentication":
        headers["WWW-Authenticate"] = "Bearer"

    payload = {
        "type": f"urn:core-data-platform:error:{exc.code}",
        "title": exc.category.value,
        "status": status_code,
        "detail": exc.message,
        "instance": str(request.url.path),
        "code": exc.code,
        "retryable": exc.retryable,
        "correlation_id": correlation_id,
    }

    return JSONResponse(
        status_code=status_code,
        content=payload,
        headers=headers,
        media_type="application/problem+json",
    )
