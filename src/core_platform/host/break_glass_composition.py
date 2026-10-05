from __future__ import annotations

from core_platform.application.break_glass import (
    BreakGlassActivationRecorder,
    DurableBreakGlassActivationRecorder,
)
from core_platform.foundation.secrets import SecretProvider
from core_platform.foundation.temporal import UtcClock
from core_platform.host.settings import Settings
from core_platform.infrastructure.observability.metrics import InfrastructureMetrics
from core_platform.infrastructure.persistence.break_glass_activation_persistence import (
    PostgresBreakGlassActivationPersistence,
)
from core_platform.infrastructure.persistence.database import Database
from core_platform.infrastructure.persistence.transaction_uow import PostgresUnitOfWorkFactory
from core_platform.infrastructure.security.evidence_crypto import Ed25519EvidenceSigner
from core_platform.infrastructure.security.evidence_keys import load_ed25519_private_key
from core_platform.infrastructure.security.secret_catalog import (
    EVIDENCE_SIGNING_PRIVATE_KEY_SECRET,
)


def build_break_glass_activation_recorder(
    *,
    settings: Settings,
    secret_provider: SecretProvider,
    database: Database,
    metrics: InfrastructureMetrics | None = None,
) -> BreakGlassActivationRecorder:
    """Compose durable activation using an explicitly configured signing identity."""
    key_id = settings.evidence_signing_key_id
    if key_id is None:
        raise RuntimeError("Evidence signing key ID is not configured")

    private_key = load_ed25519_private_key(
        secret_provider,
        EVIDENCE_SIGNING_PRIVATE_KEY_SECRET,
    )
    signer = Ed25519EvidenceSigner(private_key=private_key, key_id=key_id)
    factory = PostgresUnitOfWorkFactory(database, metrics=metrics)
    persistence = PostgresBreakGlassActivationPersistence(factory)
    return DurableBreakGlassActivationRecorder(
        persistence=persistence,
        signer=signer,
        clock=UtcClock(),
    )
