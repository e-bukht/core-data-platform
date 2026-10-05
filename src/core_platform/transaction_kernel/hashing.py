from __future__ import annotations

from collections.abc import Mapping

from core_platform.foundation.canonical_json import (
    JsonScalar,
    JsonValue,
    canonical_json_bytes,
    canonical_json_sha256,
)


def canonical_request_hash(payload: Mapping[str, JsonValue]) -> str:
    return canonical_json_sha256(payload)


__all__ = [
    "JsonScalar",
    "JsonValue",
    "canonical_json_bytes",
    "canonical_request_hash",
]