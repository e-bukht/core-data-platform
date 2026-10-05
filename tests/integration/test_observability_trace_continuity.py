from __future__ import annotations

import asyncio
import selectors

import httpx
import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import SpanKind

from core_platform.host.main import create_app
from core_platform.host.settings import get_settings
from core_platform.infrastructure.observability import (
    ObservabilityConfig,
    ObservabilityRuntime,
)

_TRACE_ID_HEX = "0123456789abcdef0123456789abcdef"
_PARENT_SPAN_ID_HEX = "0123456789abcdef"
_TRACEPARENT = (
    f"00-{_TRACE_ID_HEX}-{_PARENT_SPAN_ID_HEX}-01"
)


def _selector_loop_factory() -> asyncio.AbstractEventLoop:
    return asyncio.SelectorEventLoop(
        selectors.SelectSelector()
    )


async def _assert_http_to_postgres_trace_continuity() -> None:
    settings = get_settings()

    span_exporter = InMemorySpanExporter()
    metric_reader = InMemoryMetricReader()

    runtime = ObservabilityRuntime(
        ObservabilityConfig(
            enabled=True,
            service_name="core-data-platform-integration",
            service_version="test",
            environment="test",
            otlp_endpoint="http://unused.invalid:4318",
            trace_sample_ratio=1.0,
            metric_export_interval_millis=5000,
        ),
        span_exporter=span_exporter,
        metric_reader=metric_reader,
    )

    app = create_app(
        settings=settings,
        observability=runtime,
    )

    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            response = await client.get(
                "/health/ready",
                headers={"traceparent": _TRACEPARENT},
            )

        assert response.status_code == 200
        assert response.json() == {"status": "ready"}

        tracer_provider = runtime.tracer_provider
        assert tracer_provider is not None
        assert tracer_provider.force_flush()

        spans = span_exporter.get_finished_spans()

        server_spans = [
            span
            for span in spans
            if span.kind is SpanKind.SERVER
        ]

        assert len(server_spans) == 1

        server_span = server_spans[0]

        assert server_span.context is not None
        assert server_span.context.trace_id == int(
            _TRACE_ID_HEX,
            16,
        )

        assert server_span.parent is not None
        assert server_span.parent.span_id == int(
            _PARENT_SPAN_ID_HEX,
            16,
        )

        sqlalchemy_spans = [
            span
            for span in spans
            if (
                span.kind is SpanKind.CLIENT
                and span.instrumentation_scope is not None
                and span.instrumentation_scope.name
                == "opentelemetry.instrumentation.sqlalchemy"
            )
        ]

        assert sqlalchemy_spans

        assert all(
            span.context is not None
            and span.context.trace_id == int(_TRACE_ID_HEX, 16)
            for span in sqlalchemy_spans
        )


@pytest.mark.integration
def test_http_ingress_trace_continues_into_postgresql() -> None:
    with asyncio.Runner(
        loop_factory=_selector_loop_factory
    ) as runner:
        runner.run(
            _assert_http_to_postgres_trace_continuity()
        )