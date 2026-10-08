from __future__ import annotations

from typing import Never

from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from pytest import MonkeyPatch

import core_platform.infrastructure.observability.runtime as runtime_module
from core_platform.infrastructure.observability import (
    ObservabilityConfig,
    ObservabilityRuntime,
)


def _unexpected_otlp_exporter(*args: object, **kwargs: object) -> Never:
    raise AssertionError("OTLP exporter must not be constructed by in-memory tests")


def test_enabled_runtime_supports_deterministic_in_memory_telemetry(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runtime_module,
        "OTLPSpanExporter",
        _unexpected_otlp_exporter,
    )
    monkeypatch.setattr(
        runtime_module,
        "OTLPMetricExporter",
        _unexpected_otlp_exporter,
    )

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

    tracer_provider = runtime.tracer_provider
    meter_provider = runtime.meter_provider

    assert runtime.enabled is True
    assert tracer_provider is not None
    assert meter_provider is not None

    try:
        tracer = tracer_provider.get_tracer("core-platform-test")

        with tracer.start_as_current_span("observability.runtime.test"):
            pass

        assert tracer_provider.force_flush()

        spans = span_exporter.get_finished_spans()

        assert len(spans) == 1
        assert spans[0].name == "observability.runtime.test"
        assert spans[0].resource.attributes["service.name"] == "core-data-platform"
        assert spans[0].resource.attributes["service.version"] == "test-version"
        assert spans[0].resource.attributes["deployment.environment.name"] == "test"

        meter = meter_provider.get_meter("core-platform-test")
        counter = meter.create_counter("core_platform.test.commands")
        counter.add(1, {"outcome": "ok"})

        metrics_data = metric_reader.get_metrics_data()

        assert metrics_data is not None

        metric_names = {
            metric.name
            for resource_metrics in metrics_data.resource_metrics
            for scope_metrics in resource_metrics.scope_metrics
            for metric in scope_metrics.metrics
        }

        assert "core_platform.test.commands" in metric_names
    finally:
        runtime.shutdown()

    runtime.shutdown()
