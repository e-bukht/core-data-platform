from __future__ import annotations

import logging
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import SpanKind
from pytest import CaptureFixture

from core_platform.host.main import create_app
from core_platform.host.sensitive_data import REDACTED
from core_platform.host.settings import Settings
from core_platform.infrastructure.observability import (
    ObservabilityConfig,
    ObservabilityRuntime,
)


def test_http_telemetry_does_not_expose_sensitive_request_data(
    capsys: CaptureFixture[str],
) -> None:
    span_exporter = InMemorySpanExporter()
    metric_reader = InMemoryMetricReader()

    runtime = ObservabilityRuntime(
        ObservabilityConfig(
            enabled=True,
            service_name="core-data-platform",
            service_version="test",
            environment="test",
            otlp_endpoint="http://unused.invalid:4318",
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
            "/health/live?access_token=super-secret&safe=value",
            headers={
                "Authorization": "Bearer top-secret-token",
                "Cookie": "session=super-secret-cookie",
                "X-Api-Key": "super-secret-api-key",
            },
        )

    assert response.status_code == 200

    server_spans = [
        span for span in span_exporter.get_finished_spans() if span.kind is SpanKind.SERVER
    ]
    assert len(server_spans) == 1

    span = server_spans[0]
    attributes = span.attributes
    assert attributes is not None

    for attribute_name in ("http.url", "url.full"):
        raw_url = attributes.get(attribute_name)
        assert isinstance(raw_url, str)

        query = parse_qs(urlsplit(raw_url).query)

        assert query["access_token"] == [REDACTED]
        assert query["safe"] == ["value"]

    span_serialized = repr(attributes)

    metrics_data = metric_reader.get_metrics_data()
    assert metrics_data is not None

    metric_attributes = [
        repr(dict(point.attributes))
        for resource_metrics in metrics_data.resource_metrics
        for scope_metrics in resource_metrics.scope_metrics
        for metric in scope_metrics.metrics
        for point in getattr(metric.data, "data_points", ())
    ]

    telemetry_serialized = span_serialized + "\n" + "\n".join(metric_attributes)

    captured = capsys.readouterr()
    log_output = captured.out + captured.err

    for secret in (
        "super-secret",
        "top-secret-token",
        "super-secret-cookie",
        "super-secret-api-key",
    ):
        assert secret not in telemetry_serialized
        assert secret not in log_output

    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING
