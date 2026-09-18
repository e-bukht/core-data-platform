from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from core_platform.__about__ import __version__
from core_platform.foundation.errors import PlatformError
from core_platform.host.errors import platform_error_handler
from core_platform.host.health import router as health_router
from core_platform.host.logging import configure_logging
from core_platform.host.settings import get_settings
from core_platform.infrastructure.persistence.database import Database


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    database = Database(settings.database_url.get_secret_value())
    app.state.database = database
    try:
        yield
    finally:
        await database.close()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.environment != "local")
    app = FastAPI(
        title="Core Data Model Platform",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if settings.openapi_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.openapi_enabled else None,
    )
    app.add_exception_handler(PlatformError, platform_error_handler)  # type: ignore[arg-type]
    app.include_router(health_router)
    return app


app = create_app()
