from __future__ import annotations

import asyncio

from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from core_platform.infrastructure.observability import (
    ObservabilityConfig,
    ObservabilityRuntime,
)
from core_platform.infrastructure.persistence.database import Database


def test_database_pool_metrics_are_observable_in_memory() -> None:
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

    database = Database(
        "postgresql+psycopg://runtime:secret@localhost/coredata",
        pool_size=7,
        max_overflow=3,
    )

    try:
        snapshot = database.pool_snapshot()

        assert snapshot.size == 7
        assert snapshot.checked_in == 0
        assert snapshot.checked_out == 0

        runtime.instrument_database(database)

        metrics_data = metric_reader.get_metrics_data()
        assert metrics_data is not None

        metric_names = {
            metric.name
            for resource_metrics in metrics_data.resource_metrics
            for scope_metrics in resource_metrics.scope_metrics
            for metric in scope_metrics.metrics
        }

        assert {
            "core_platform.db.pool.size",
            "core_platform.db.pool.checked_in",
            "core_platform.db.pool.checked_out",
            "core_platform.db.pool.overflow",
        } <= metric_names
    finally:
        runtime.shutdown()
        asyncio.run(database.close())
