from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from collections.abc import Mapping

type JsonScalar = bool | int | float | str | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


def _normalize_text(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _normalize_json(value: JsonValue) -> JsonValue:
    if value is None or isinstance(value, bool | int):
        return value

    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Non-finite JSON numbers are not canonicalizable")
        return value

    if isinstance(value, str):
        return _normalize_text(value)

    if isinstance(value, list):
        return [_normalize_json(item) for item in value]

    normalized: dict[str, JsonValue] = {}
    for key, item in value.items():
        normalized_key = _normalize_text(key)
        if normalized_key in normalized:
            raise ValueError(
                "JSON object contains keys that collide after Unicode normalization"
            )
        normalized[normalized_key] = _normalize_json(item)

    return normalized


def canonical_json_bytes(payload: Mapping[str, JsonValue]) -> bytes:
    normalized = _normalize_json(dict(payload))
    serialized = json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return serialized.encode("utf-8")


def canonical_json_sha256(payload: Mapping[str, JsonValue]) -> str:
    digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    return f"sha256:{digest}"