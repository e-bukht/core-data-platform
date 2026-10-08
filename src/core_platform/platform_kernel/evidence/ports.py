from __future__ import annotations

from typing import Protocol

from core_platform.platform_kernel.evidence.models import EvidenceRecord
from core_platform.platform_kernel.ids import EvidenceRecordId, TenantId


class EvidenceSigner(Protocol):
    @property
    def algorithm(self) -> str: ...

    @property
    def key_id(self) -> str: ...

    async def sign(self, payload: bytes) -> bytes: ...


class EvidenceVerifier(Protocol):
    async def verify(
        self,
        payload: bytes,
        *,
        signature: bytes,
        algorithm: str,
        key_id: str,
    ) -> bool: ...


class EvidenceRepository(Protocol):
    async def append(self, record: EvidenceRecord) -> None: ...

    async def get(
        self,
        tenant_id: TenantId,
        record_id: EvidenceRecordId,
    ) -> EvidenceRecord | None: ...
