from __future__ import annotations

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel

from core_platform.__about__ import __version__
from core_platform.infrastructure.persistence.database import Database

router = APIRouter(tags=["platform"])


class LivenessResponse(BaseModel):
    status: str


class ReadinessResponse(BaseModel):
    status: str
    database_reachable: bool
    database_migrated: bool
    database_revision: str | None = None


@router.get("/health/live", response_model=LivenessResponse)
async def live() -> LivenessResponse:
    return LivenessResponse(status="alive")


@router.get("/health/ready", response_model=ReadinessResponse)
async def ready(request: Request, response: Response) -> ReadinessResponse:
    database: Database = request.app.state.database
    db_state = await database.readiness()
    if not db_state.ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ready" if db_state.ready else "not_ready",
        database_reachable=db_state.reachable,
        database_migrated=db_state.migrated,
        database_revision=db_state.revision,
    )


@router.get("/version")
async def version() -> dict[str, str]:
    return {"version": __version__}
