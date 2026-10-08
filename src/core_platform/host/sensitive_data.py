from __future__ import annotations

REDACTED = "[REDACTED]"

_SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "proxy_authorization",
        "password",
        "passwd",
        "secret",
        "client_secret",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "api_key",
        "apikey",
        "private_key",
        "credential",
        "credentials",
        "database_url",
        "migration_database_url",
        "cookie",
        "set_cookie",
        "dsn",
        "connection_string",
    }
)

_QUERY_SENSITIVE_KEYS = frozenset(
    {
        "code",
        "state",
        "signature",
        "sig",
        "client_assertion",
        "assertion",
        "samlresponse",
    }
)


def is_sensitive_key(key: str) -> bool:
    normalized = key.strip().lower().replace("-", "_")

    if normalized in _SENSITIVE_KEYS:
        return True

    return (
        normalized.startswith("authorization_")
        or normalized.endswith("_authorization")
        or normalized.endswith("_password")
        or normalized.endswith("_secret")
        or normalized.endswith("_token")
        or normalized.endswith("_api_key")
        or normalized.endswith("_private_key")
        or normalized.endswith("_credential")
        or normalized.endswith("_credentials")
        or normalized.endswith("_database_url")
        or normalized.endswith("_cookie")
        or normalized.endswith("_dsn")
        or normalized.endswith("_connection_string")
    )


def is_sensitive_query_key(key: str) -> bool:
    normalized = key.strip().lower().replace("-", "_")
    return normalized in _QUERY_SENSITIVE_KEYS or is_sensitive_key(normalized)
