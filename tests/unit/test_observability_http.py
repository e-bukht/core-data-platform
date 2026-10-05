from __future__ import annotations

from fastapi.testclient import TestClient
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import SpanKind

from core_platform.host.main import create_app
from core_platform.host.settings import Settings
from core_platform.infrastructure.observability import (
    ObservabilityConfig,
    ObservabilityRuntime,
)


def test_fastapi_preserves_incoming_w3c_trace_context() -> None:
    trace_id_hex = "0123456789abcdef0123456789abcdef"
    parent_span_id_hex = "0123456789abcdef"
    traceparent = f"00-{trace_id_hex}-{parent_span_id_hex}-01"

    span_exporter = InMemorySpanExporter()
    metric_reader = InMemoryMetricReader()

    runtime = ObservabilityRuntime(
        ObservabilityConfig(
            enabled=True,
            service_name="core-data-platform",
            service_version="test-version",
            environment="test",
            otlp_endpoint="http://must-not-be-used.invalid:4318",
            trace_sample_ratio=1.0,
            metric_export_interval_millis=5000,
        ),
        span_exporter=span_exporter,
        metric_reader=metric_reader,
    )

    settings = Settings(

        environment="test",
        otel_enabled=True,
    )

    app = create_app(
        settings=settings,
        observability=runtime,
    )

    with TestClient(app) as client:
        response = client.get(
            "/health/live",
            headers={"traceparent": traceparent},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}

    server_spans = [
        span
        for span in span_exporter.get_finished_spans()
        if span.kind is SpanKind.SERVER
    ]

    assert len(server_spans) == 1

    server_span = server_spans[0]

    assert server_span.context is not None
    assert server_span.context.trace_id == int(trace_id_hex, 16)

    assert server_span.parent is not None
    assert server_span.parent.span_id == int(parent_span_id_hex, 16)

    assert server_span.resource.attributes["service.name"] == "core-data-platform"
    assert server_span.resource.attributes["service.version"] == "test-version"
    assert server_span.resource.attributes["deployment.environment.name"] == "test"