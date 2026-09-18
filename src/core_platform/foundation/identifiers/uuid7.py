"""UUIDv7 generation for Python 3.12.

Python's stdlib only gained uuid.uuid7 in later Python versions. This implementation follows the
RFC 9562 bit layout: 48-bit Unix epoch milliseconds, version 7, 12 random bits, RFC variant, and
62 random bits. It does not promise strict monotonic ordering within one millisecond.
"""

from __future__ import annotations

import secrets
import time
from uuid import UUID


def new_uuid7(*, timestamp_ms: int | None = None) -> UUID:
    """Create a standards-shaped UUIDv7.

    Args:
        timestamp_ms: Optional timestamp override used only for deterministic tests.
    """
    unix_ms = int(time.time_ns() // 1_000_000) if timestamp_ms is None else timestamp_ms
    if unix_ms < 0 or unix_ms >= 1 << 48:
        raise ValueError("timestamp_ms must fit in 48 bits")

    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)

    value = unix_ms << 80
    value |= 0x7 << 76
    value |= rand_a << 64
    value |= 0b10 << 62
    value |= rand_b
    return UUID(int=value)
