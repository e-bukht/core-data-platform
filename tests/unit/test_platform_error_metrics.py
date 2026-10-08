from __future__ import annotations

from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from core_platform.infrastructure.observability import (
    ObservabilityConfig,
    ObservabilityRuntime,
)


def test_platform_error_metrics_are_low_cardinality() -> None:
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
        span_exporter=InMemorySpanExporter(),
        metric_reader=metric_reader,
    )

    try:
        metrics = runtime.metrics

        metrics.record_platform_error(
            category="authorization",
            status_code=403,
        )
        metrics.record_platform_error(
            category="concurrency",
            status_code=409,
        )

        metrics_data = metric_reader.get_metrics_data()
        assert metrics_data is not None

        platform_error_points = [
            point
            for resource_metrics in metrics_data.resource_metrics
            for scope_metrics in resource_metrics.scope_metrics
            for metric in scope_metrics.metrics
            if metric.name == "core_platform.platform.errors"
            for point in getattr(metric.data, "data_points", ())
        ]

        assert {
            (
                point.attributes["category"],
                point.attributes["status_code"],
                point.value,
            )
            for point in platform_error_points
        } == {
            ("authorization", 403, 1),
            ("concurrency", 409, 1),
        }

        for point in platform_error_points:
            attributes = dict(point.attributes)

            assert set(attributes) == {
                "category",
                "status_code",
            }
    finally:
        runtime.shutdown()
