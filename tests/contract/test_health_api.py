from __future__ import annotations

from fastapi.testclient import TestClient

from core_platform.host.main import app


def test_liveness_is_independent_of_database() -> None:
    with TestClient(app) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}
