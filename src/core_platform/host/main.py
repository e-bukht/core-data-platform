from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from core_platform.__about__ import __version__
from core_platform.application.context_trust import ContextTrustService
from core_platform.foundation.errors import PlatformError
from core_platform.foundation.secrets import SecretProvider
from core_platform.host.api.break_glass import router as break_glass_router
from core_platform.host.api.context_trust import router as context_trust_router
from core_platform.host.break_glass_composition import (
    build_break_glass_runtime,
)
from core_platform.host.errors import platform_error_handler
from core_platform.host.health import router as health_router
from core_platform.host.logging import configure_logging
from core_platform.host.openapi import configure_openapi
from core_platform.host.settings import Settings, get_settings
from core_platform.host.telemetry import sanitize_http_server_span
from core_platform.infrastructure.observability import (
    ObservabilityConfig,
    ObservabilityRuntime,
)
from core_platform.infrastructure.persistence.break_glass_repository import (
    SqlBreakGlassRepository,
)
from core_platform.infrastructure.persistence.context_trust_repository import (
    SqlContextTrustRepository,
)
from core_platform.infrastructure.persistence.database import Database
from core_platform.infrastructure.security.oidc import OidcConfiguration, OidcTokenAuthenticator
from core_platform.infrastructure.security.secret_catalog import (
    RUNTIME_DATABASE_URL_SECRET,
    build_environment_secret_provider,
)
from core_platform.platform_kernel.policy import CapabilityGrantPdp


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    observability: ObservabilityRuntime = app.state.observability
    secret_provider: SecretProvider = app.state.secret_provider

    database_url = secret_provider.get_secret(
        RUNTIME_DATABASE_URL_SECRET
    ).reveal_text()

    database = Database(database_url)
    authenticator: OidcTokenAuthenticator | None = None
    try:
        observability.instrument_database(database)
        # Startup fails closed when the key ID or signing secret is unavailable.
        break_glass_runtime = build_break_glass_runtime(
            settings=settings,
            secret_provider=secret_provider,
            database=database,
            metrics=observability.metrics,
        )
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
        break_glass_repository = SqlBreakGlassRepository(database)
        app.state.database = database
        app.state.break_glass_lifecycle = (
            break_glass_runtime.lifecycle_service
        )
        app.state.context_trust = ContextTrustService(
            authenticator=authenticator,
            repository=repository,
            break_glass_repository=break_glass_repository,
            pdp=CapabilityGrantPdp(),
            environment=settings.environment,
            break_glass_activation_recorder=(
                break_glass_runtime.activation_recorder
            ),
        )
        app.state.startup_complete = True
        yield
    finally:
        app.state.startup_complete = False
        if observability.enabled:
            FastAPIInstrumentor.uninstrument_app(app)
        observability.shutdown()
        if authenticator is not None:
            await authenticator.close()
        await database.close()


def _observability_config(settings: Settings) -> ObservabilityConfig:
    return ObservabilityConfig(
        enabled=settings.otel_enabled,
        service_name=settings.otel_service_name,
        service_version=__version__,
        environment=settings.environment,
        otlp_endpoint=settings.otel_exporter_otlp_endpoint,
        trace_sample_ratio=settings.otel_trace_sample_ratio,
        metric_export_interval_millis=settings.otel_metric_export_interval_millis,
    )


def create_app(
    *,
    settings: Settings | None = None,
    observability: ObservabilityRuntime | None = None,
    secret_provider: SecretProvider | None = None,
) -> FastAPI:
    active_settings = settings if settings is not None else get_settings()
    configure_logging(
        level=active_settings.log_level,
        json_logs=active_settings.environment != "local",
    )

    runtime = (
        observability
        if observability is not None
        else ObservabilityRuntime(_observability_config(active_settings))
    )

    app = FastAPI(
        title="Core Data Model Platform",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if active_settings.openapi_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if active_settings.openapi_enabled else None,
    )
    app.state.settings = active_settings
    app.state.observability = runtime
    app.state.secret_provider = (
        secret_provider
        if secret_provider is not None
        else build_environment_secret_provider()
    )
    app.state.startup_complete = False

    if runtime.enabled:
        if runtime.tracer_provider is None or runtime.meter_provider is None:
            raise RuntimeError("Enabled observability runtime has no providers")
        FastAPIInstrumentor.instrument_app(
            app,
            tracer_provider=runtime.tracer_provider,
            meter_provider=runtime.meter_provider,
            server_request_hook=sanitize_http_server_span,
        )

    app.add_exception_handler(PlatformError, platform_error_handler)  # type: ignore[arg-type]
    app.include_router(health_router)
    app.include_router(context_trust_router)
    app.include_router(break_glass_router)
    configure_openapi(app, issuer=active_settings.oidc_issuer)
    return app


app = create_app()
