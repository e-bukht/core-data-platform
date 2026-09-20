from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from core_platform.__about__ import __version__
from core_platform.application.context_trust import ContextTrustService
from core_platform.foundation.errors import PlatformError
from core_platform.host.api.context_trust import router as context_trust_router
from core_platform.host.errors import platform_error_handler
from core_platform.host.health import router as health_router
from core_platform.host.logging import configure_logging
from core_platform.host.openapi import configure_openapi
from core_platform.host.settings import get_settings
from core_platform.infrastructure.persistence.context_trust_repository import (
    SqlContextTrustRepository,
)
from core_platform.infrastructure.persistence.database import Database
from core_platform.infrastructure.security.oidc import OidcConfiguration, OidcTokenAuthenticator
from core_platform.platform_kernel.policy import CapabilityGrantPdp


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    database = Database(settings.database_url.get_secret_value())
    authenticator = OidcTokenAuthenticator(
        OidcConfiguration(
            issuer=settings.oidc_issuer.rstrip("/"),
            audience=settings.oidc_audience,
            allowed_algorithms=settings.allowed_algorithms,
            jwks_ttl_seconds=settings.oidc_jwks_ttl_seconds,
            clock_skew_seconds=settings.oidc_clock_skew_seconds,
        )
    )
    repository = SqlContextTrustRepository(database)
    app.state.settings = settings
    app.state.database = database
    app.state.context_trust = ContextTrustService(
        authenticator=authenticator,
        repository=repository,
        pdp=CapabilityGrantPdp(),
        environment=settings.environment,
    )
    try:
        yield
    finally:
        await authenticator.close()
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
    app.include_router(context_trust_router)
    configure_openapi(app, issuer=settings.oidc_issuer)
    return app


app = create_app()
