from __future__ import annotations

from opentelemetry.sdk.trace import TracerProvider

from core_platform.host.logging import _add_trace_context


def test_trace_context_is_added_inside_active_span() -> None:
    provider = TracerProvider(shutdown_on_exit=False)

    try:
        tracer = provider.get_tracer("logging-test")

        with tracer.start_as_current_span("logging.trace-context") as span:
            event_dict = _add_trace_context(None, "info", {"event": "test"})

            span_context = span.get_span_context()

            assert event_dict["trace_id"] == f"{span_context.trace_id:032x}"
            assert event_dict["span_id"] == f"{span_context.span_id:016x}"
    finally:
        provider.shutdown()


def test_trace_context_is_absent_without_active_span() -> None:
    event_dict = _add_trace_context(None, "info", {"event": "test"})

    assert "trace_id" not in event_dict
    assert "span_id" not in event_dict
