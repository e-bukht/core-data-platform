from __future__ import annotations

from dataclasses import dataclass
from typing import final


@dataclass(frozen=True, slots=True)
class SecretReference:
    name: str

    def __post_init__(self) -> None:
        normalized = self.name.strip()

        if not normalized:
            raise ValueError("Secret reference name must not be empty")

        object.__setattr__(
            self,
            "name",
            normalized,
        )


@final
class SecretValue:
    __slots__ = ("_value",)

    def __init__(
        self,
        value: str | bytes,
    ) -> None:
        raw = value.encode("utf-8") if isinstance(value, str) else bytes(value)

        if not raw:
            raise ValueError("Secret value must not be empty")

        self._value = raw

    def reveal_bytes(self) -> bytes:
        return self._value

    def reveal_text(
        self,
        *,
        encoding: str = "utf-8",
    ) -> str:
        return self._value.decode(encoding)

    def __repr__(self) -> str:
        return "SecretValue(<redacted>)"

    def __str__(self) -> str:
        return "<redacted>"
