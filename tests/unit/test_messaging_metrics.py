from __future__ import annotations

from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from core_platform.infrastructure.observability import (
    ObservabilityConfig,
    ObservabilityRuntime,
)


def test_outbox_and_inbox_metrics_are_low_cardinality() -> None:
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

        metrics.record_outbox_added()
        metrics.record_outbox_claimed(count=3)
        metrics.record_outbox_published()
        metrics.record_outbox_released()

        metrics.record_inbox_lookup(found=False)
        metrics.record_inbox_lookup(found=True)
        metrics.record_inbox_added()
        metrics.record_inbox_processed()

        metrics_data = metric_reader.get_metrics_data()
        assert metrics_data is not None

        points = {
            metric.name: tuple(getattr(metric.data, "data_points", ()))
            for resource_metrics in metrics_data.resource_metrics
            for scope_metrics in resource_metrics.scope_metrics
            for metric in scope_metrics.metrics
        }

        assert points["core_platform.outbox.added"][0].value == 1
        assert points["core_platform.outbox.claimed"][0].value == 3
        assert points["core_platform.outbox.published"][0].value == 1
        assert points["core_platform.outbox.released"][0].value == 1
        assert points["core_platform.inbox.added"][0].value == 1
        assert points["core_platform.inbox.processed"][0].value == 1

        lookup_points = points["core_platform.inbox.lookup"]
        lookup_results = {
            point.attributes["result"]: point.value
            for point in lookup_points
        }

        assert lookup_results == {
            "found": 1,
            "missing": 1,
        }

        for metric_points in points.values():
            for point in metric_points:
                attributes = dict(point.attributes)
                assert "tenant_id" not in attributes
                assert "actor_id" not in attributes
                assert "message_id" not in attributes
                assert "correlation_id" not in attributes
                assert "worker_id" not in attributes
                assert "consumer_name" not in attributes
    finally:
        runtime.shutdown()