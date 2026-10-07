from __future__ import annotations

import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.trace import SpanKind
from opentelemetry.trace.propagation.tracecontext import (
    TraceContextTextMapPropagator,
)
from tests.test_platform.telemetry import CertificationTelemetryCollector
from tests.test_platform.telemetry_assertions import (
    assert_trace_correlation,
)

TRACE_ID_HEX = "0123456789abcdef0123456789abcdef"
PARENT_SPAN_ID_HEX = "0123456789abcdef"
TRACEPARENT = (
    f"00-{TRACE_ID_HEX}-{PARENT_SPAN_ID_HEX}-01"
)


def _capture_correlated_spans(
    collector: CertificationTelemetryCollector,
) -> tuple[ReadableSpan, ...]:
    tracer_provider = collector.runtime.tracer_provider

    assert tracer_provider is not None

    tracer = tracer_provider.get_tracer(
        "core-platform-certification-correlation"
    )

    parent_context = TraceContextTextMapPropagator().extract(
        {
            "traceparent": TRACEPARENT,
        }
    )

    with tracer.start_as_current_span(
        "certification.http",
        context=parent_context,
        kind=SpanKind.SERVER,
    ), tracer.start_as_current_span(
        "certification.postgresql",
        kind=SpanKind.CLIENT,
    ):
        pass

    assert tracer_provider.force_flush()

    return tuple(
        collector.span_exporter.get_finished_spans()
    )


def test_reusable_trace_correlation_assertion(
    cert_telemetry_collector: CertificationTelemetryCollector,
) -> None:
    spans = _capture_correlated_spans(
        cert_telemetry_collector
    )

    assert_trace_correlation(
        spans,
        TRACE_ID_HEX,
        required_kinds=(
            SpanKind.SERVER,
            SpanKind.CLIENT,
        ),
    )


def test_trace_correlation_assertion_rejects_wrong_trace(
    cert_telemetry_collector: CertificationTelemetryCollector,
) -> None:
    spans = _capture_correlated_spans(
        cert_telemetry_collector
    )

    with pytest.raises(
        AssertionError,
        match="is not correlated",
    ):
        assert_trace_correlation(
            spans,
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )