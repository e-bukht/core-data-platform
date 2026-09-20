from uuid import UUID

from fastapi.testclient import TestClient

from core_platform.host.main import app

TENANT_ID = "00000000-0000-7000-8000-000000000001"
CORRELATION_ID = "00000000-0000-7000-8000-000000000099"


def test_protected_route_requires_bearer_token_and_preserves_correlation_id() -> None:
    with TestClient(app) as client:
        response = client.get(
            "/platform/context",
            headers={
                "X-Tenant-Id": TENANT_ID,
                "X-Correlation-Id": CORRELATION_ID,
            },
        )

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH.TOKEN.REQUIRED"
    assert response.json()["correlation_id"] == CORRELATION_ID
    assert response.headers["X-Correlation-Id"] == CORRELATION_ID
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_protected_route_generates_correlation_id_when_missing() -> None:
    with TestClient(app) as client:
        response = client.get(
            "/platform/context",
            headers={"X-Tenant-Id": TENANT_ID},
        )

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH.TOKEN.REQUIRED"

    correlation_id = response.headers["X-Correlation-Id"]
    assert response.json()["correlation_id"] == correlation_id
    UUID(correlation_id)

    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_openapi_advertises_oidc_for_platform_routes() -> None:
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()

    oidc = schema["components"]["securitySchemes"]["oidc"]
    assert oidc["type"] == "openIdConnect"
    assert "/.well-known/openid-configuration" in oidc["openIdConnectUrl"]
    assert schema["paths"]["/platform/context"]["get"]["security"] == [{"oidc": []}]
