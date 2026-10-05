from __future__ import annotations

import os
from collections.abc import Mapping

from core_platform.foundation.secrets import (
    SecretReference,
    SecretValue,
)


class EnvironmentSecretProvider:
    def __init__(
        self,
        *,
        bindings: Mapping[str, str],
        environ: Mapping[str, str] | None = None,
    ) -> None:
        normalized: dict[str, str] = {}

        for reference_name, environment_name in bindings.items():
            logical_name = reference_name.strip()
            variable_name = environment_name.strip()

            if not logical_name:
                raise ValueError(
                    "Secret binding reference name must not be empty"
                )

            if not variable_name:
                raise ValueError(
                    "Secret binding environment name must not be empty"
                )

            normalized[logical_name] = variable_name

        self._bindings = normalized
        self._environ = (
            os.environ
            if environ is None
            else environ
        )

    def get_secret(
        self,
        reference: SecretReference,
    ) -> SecretValue:
        environment_name = self._bindings.get(
            reference.name
        )

        if environment_name is None:
            raise RuntimeError(
                f"Secret reference is not configured: "
                f"{reference.name}"
            )

        value = self._environ.get(environment_name)

        if value is None or not value:
            raise RuntimeError(
                f"Secret is unavailable: {reference.name}"
            )

        return SecretValue(value)