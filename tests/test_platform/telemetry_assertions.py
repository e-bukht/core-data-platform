from __future__ import annotations

from collections.abc import Iterable

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.trace import SpanKind


def assert_trace_correlation(
    spans: Iterable[ReadableSpan],
    expected_trace_id_hex: str,
    *,
    required_kinds: tuple[SpanKind, ...] = (),
) -> None:
    """Assert that all supplied spans belong to one expected distributed trace."""

    captured = tuple(spans)

    assert captured, "Expected at least one telemetry span"
    assert len(expected_trace_id_hex) == 32, (
        "Expected trace id MUST contain exactly 32 hexadecimal characters"
    )

    try:
        expected_trace_id = int(expected_trace_id_hex, 16)
    except ValueError as exc:
        raise AssertionError("Expected trace id MUST be hexadecimal") from exc

    assert expected_trace_id != 0, "Expected trace id MUST be non-zero"

    for span in captured:
        assert span.context is not None, f"Span {span.name!r} has no span context"
        assert span.context.trace_id == expected_trace_id, (
            f"Span {span.name!r} is not correlated to trace {expected_trace_id_hex}"
        )

    missing_kinds = tuple(
        kind for kind in required_kinds if not any(span.kind is kind for span in captured)
    )

    assert not missing_kinds, "Missing required span kinds: " + ", ".join(
        kind.name for kind in missing_kinds
    )
