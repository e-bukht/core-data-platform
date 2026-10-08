from __future__ import annotations

from core_platform.host.logging import _redact_sensitive_data
from core_platform.host.sensitive_data import REDACTED


def test_sensitive_fields_are_redacted_recursively() -> None:
    event = {
        "event": "request_processed",
        "Authorization": "Bearer top-secret-token",
        "database_url": "postgresql://user:password@db/coredata",
        "payload": {
            "access-token": "access-secret",
            "nested": [
                {
                    "client_secret": "client-secret-value",
                    "session_cookie": "session-value",
                    "safe": "visible",
                }
            ],
        },
    }

    result = _redact_sensitive_data(None, "info", event)

    assert result["Authorization"] == REDACTED
    assert result["database_url"] == REDACTED

    payload = result["payload"]
    assert isinstance(payload, dict)
    assert payload["access-token"] == REDACTED

    nested = payload["nested"]
    assert isinstance(nested, list)

    first = nested[0]
    assert isinstance(first, dict)
    assert first["client_secret"] == REDACTED
    assert first["session_cookie"] == REDACTED
    assert first["safe"] == "visible"


def test_operational_correlation_fields_remain_visible() -> None:
    event = {
        "event": "authorization_decision",
        "effect": "ALLOW",
        "tenant_id": "tenant-123",
        "actor_id": "actor-123",
        "correlation_id": "correlation-123",
        "capability": "test-resource.create",
        "code": "AUTHZ.ALLOW",
        "jwks_uri": "https://idp.example.test/.well-known/jwks.json",
        "token_id": "jti-reference-only",
    }

    result = _redact_sensitive_data(None, "info", event)

    assert result == event
