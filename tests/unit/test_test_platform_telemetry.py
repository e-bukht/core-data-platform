from __future__ import annotations

from tests.test_platform.telemetry import CertificationTelemetryCollector


def test_certification_telemetry_collector_captures_spans_and_metrics(
    cert_telemetry_collector: CertificationTelemetryCollector,
) -> None:
    runtime = cert_telemetry_collector.runtime

    tracer_provider = runtime.tracer_provider
    meter_provider = runtime.meter_provider

    assert runtime.enabled
    assert tracer_provider is not None
    assert meter_provider is not None

    tracer = tracer_provider.get_tracer("core-platform-certification")

    with tracer.start_as_current_span("certification.telemetry"):
        pass

    assert tracer_provider.force_flush()

    spans = cert_telemetry_collector.span_exporter.get_finished_spans()

    assert len(spans) == 1
    assert spans[0].name == "certification.telemetry"
    assert spans[0].resource.attributes["service.name"] == "core-data-platform-certification"
    assert spans[0].resource.attributes["service.version"] == "test-platform"
    assert spans[0].resource.attributes["deployment.environment.name"] == "test"

    meter = meter_provider.get_meter("core-platform-certification")
    counter = meter.create_counter("core_platform.certification.events")
    counter.add(1, {"outcome": "ok"})

    metrics_data = cert_telemetry_collector.metric_reader.get_metrics_data()

    assert metrics_data is not None

    metric_names = {
        metric.name
        for resource_metrics in metrics_data.resource_metrics
        for scope_metrics in resource_metrics.scope_metrics
        for metric in scope_metrics.metrics
    }

    assert "core_platform.certification.events" in metric_names
