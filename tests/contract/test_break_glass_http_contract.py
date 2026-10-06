from __future__ import annotations

from fastapi.testclient import TestClient

from core_platform.host.main import app

TENANT_ID = (
    "00000000-0000-7000-8000-000000000001"
)

CORRELATION_ID = (
    "00000000-0000-7000-8000-000000000099"
)

GRANT_ID = (
    "00000000-0000-7000-8000-000000000204"
)


def _headers() -> dict[str, str]:
    return {
        "X-Tenant-Id": TENANT_ID,
        "X-Correlation-Id": CORRELATION_ID,
    }


def test_break_glass_issue_requires_bearer_token() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/platform/break-glass/grants",
            headers=_headers(),
            json={
                "actor_id": (
                    "00000000-0000-7000-8000-000000000002"
                ),
                "capabilities": [
                    "platform.outbox.retry"
                ],
                "scope": {
                    "kind": "TENANT",
                },
                "reason": "Emergency recovery",
                "valid_from": (
                    "2026-10-06T16:00:00+00:00"
                ),
                "valid_until": (
                    "2026-10-06T17:00:00+00:00"
                ),
                "accepted_acr_values": [
                    "2"
                ],
                "required_amr": [
                    "otp"
                ],
            },
        )

    assert response.status_code == 401
    assert response.json()["code"] == (
        "AUTH.TOKEN.REQUIRED"
    )
    assert response.json()["correlation_id"] == (
        CORRELATION_ID
    )
    assert response.headers[
        "X-Correlation-Id"
    ] == CORRELATION_ID
    assert response.headers[
        "WWW-Authenticate"
    ] == "Bearer"


def test_break_glass_transition_routes_require_bearer_token() -> None:
    routes = (
        (
            "suspend",
            {
                "expected_version": 0,
                "transition_reason": (
                    "Emergency suspension"
                ),
            },
        ),
        (
            "resume",
            {
                "expected_version": 1,
                "transition_reason": (
                    "Emergency recovery"
                ),
            },
        ),
        (
            "revoke",
            {
                "expected_version": 2,
                "expected_current_status": "ACTIVE",
                "transition_reason": (
                    "Emergency access ended"
                ),
            },
        ),
    )

    with TestClient(app) as client:
        for operation, payload in routes:
            response = client.post(
                (
                    "/platform/break-glass/grants/"
                    f"{GRANT_ID}/{operation}"
                ),
                headers=_headers(),
                json=payload,
            )

            assert response.status_code == 401
            assert response.json()["code"] == (
                "AUTH.TOKEN.REQUIRED"
            )
            assert response.json()[
                "correlation_id"
            ] == CORRELATION_ID
            assert response.headers[
                "WWW-Authenticate"
            ] == "Bearer"


def test_openapi_advertises_oidc_for_break_glass_routes() -> None:
    expected_paths = (
        "/platform/break-glass/grants",
        (
            "/platform/break-glass/grants/"
            "{grant_id}/suspend"
        ),
        (
            "/platform/break-glass/grants/"
            "{grant_id}/resume"
        ),
        (
            "/platform/break-glass/grants/"
            "{grant_id}/revoke"
        ),
    )

    with TestClient(app) as client:
        schema = client.get(
            "/openapi.json"
        ).json()

    for path in expected_paths:
        assert path in schema["paths"]
        assert (
            schema["paths"][path]["post"]["security"]
            == [{"oidc": []}]
        )
