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

    payload = {
        "type": f"urn:core-data-platform:error:{exc.code}",
        "title": exc.category.value,
        "status": status_code,
        "detail": exc.message,
        "instance": str(request.url.path),
        "code": exc.code,
        "retryable": exc.retryable,
        "correlation_id": exc.correlation_id,
    }
    return JSONResponse(
        status_code=status_code,
        content=payload,
        media_type="application/problem+json",
    )
