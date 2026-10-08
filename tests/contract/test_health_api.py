from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core_platform.host.health import router as health_router
from core_platform.infrastructure.persistence.database import DatabaseReadiness


class _FakeDatabase:
    def __init__(self, readiness: DatabaseReadiness) -> None:
        self._readiness = readiness

    async def readiness(self) -> DatabaseReadiness:
        return self._readiness


def _health_app(
    *,
    startup_complete: bool,
    database_readiness: DatabaseReadiness,
) -> FastAPI:
    app = FastAPI()
    app.state.startup_complete = startup_complete
    app.state.database = _FakeDatabase(database_readiness)
    app.include_router(health_router)
    return app


def test_liveness_is_independent_of_database() -> None:
    app = _health_app(
        startup_complete=False,
        database_readiness=DatabaseReadiness(
            reachable=False,
            migrated=False,
            revision="must-not-leak",
            error="SensitiveInfrastructureError",
        ),
    )

    with TestClient(app) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_startup_reports_initialization_state_only() -> None:
    starting_app = _health_app(
        startup_complete=False,
        database_readiness=DatabaseReadiness(
            reachable=False,
            migrated=False,
        ),
    )

    with TestClient(starting_app) as client:
        starting = client.get("/health/startup")

    assert starting.status_code == 503
    assert starting.json() == {"status": "starting"}

    started_app = _health_app(
        startup_complete=True,
        database_readiness=DatabaseReadiness(
            reachable=False,
            migrated=False,
        ),
    )

    with TestClient(started_app) as client:
        started = client.get("/health/startup")

    assert started.status_code == 200
    assert started.json() == {"status": "started"}


def test_readiness_is_publicly_minimal_when_ready() -> None:
    app = _health_app(
        startup_complete=True,
        database_readiness=DatabaseReadiness(
            reachable=True,
            migrated=True,
            revision="0004-sensitive-revision",
        ),
    )

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readiness_is_publicly_minimal_when_not_ready() -> None:
    app = _health_app(
        startup_complete=True,
        database_readiness=DatabaseReadiness(
            reachable=False,
            migrated=False,
            revision="must-not-leak",
            error="SensitiveInfrastructureError",
        ),
    )

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}
