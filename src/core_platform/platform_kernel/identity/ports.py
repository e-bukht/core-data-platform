from __future__ import annotations

from typing import Protocol

from core_platform.platform_kernel.identity.models import AuthenticationContext


class TokenAuthenticator(Protocol):
    async def authenticate(self, token: str) -> AuthenticationContext: ...
