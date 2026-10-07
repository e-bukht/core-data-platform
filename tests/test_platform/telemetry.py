from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from core_platform.infrastructure.observability import (
    ObservabilityConfig,
    ObservabilityRuntime,
)


@dataclass(frozen=True, slots=True)
class CertificationTelemetryCollector:
    """Deterministic in-memory telemetry runtime for certification tests."""

    runtime: ObservabilityRuntime
    span_exporter: InMemorySpanExporter
    metric_reader: InMemoryMetricReader


@pytest.fixture
def cert_telemetry_collector() -> Iterator[CertificationTelemetryCollector]:
    span_exporter = InMemorySpanExporter()
    metric_reader = InMemoryMetricReader()

    runtime = ObservabilityRuntime(
        ObservabilityConfig(
            enabled=True,
            service_name="core-data-platform-certification",
            service_version="test-platform",
            environment="test",
            otlp_endpoint="http://must-not-be-used.invalid:4318",
            trace_sample_ratio=1.0,
            metric_export_interval_millis=5000,
        ),
        span_exporter=span_exporter,
        metric_reader=metric_reader,
    )

    try:
        yield CertificationTelemetryCollector(
            runtime=runtime,
            span_exporter=span_exporter,
            metric_reader=metric_reader,
        )
    finally:
        runtime.shutdown()