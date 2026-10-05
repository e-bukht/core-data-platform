from __future__ import annotations

from typing import Protocol

from core_platform.foundation.secrets.models import (
    SecretReference,
    SecretValue,
)


class SecretProvider(Protocol):
    def get_secret(
        self,
        reference: SecretReference,
    ) -> SecretValue: ...