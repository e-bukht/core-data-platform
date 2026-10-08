from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel

from core_platform.__about__ import __version__
from core_platform.infrastructure.persistence.database import Database

router = APIRouter(tags=["platform"])


class LivenessResponse(BaseModel):
    status: Literal["alive"]


class StartupResponse(BaseModel):
    status: Literal["starting", "started"]


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]


@router.get("/health/live", response_model=LivenessResponse)
async def live() -> LivenessResponse:
    return LivenessResponse(status="alive")


@router.get("/health/startup", response_model=StartupResponse)
async def startup(request: Request, response: Response) -> StartupResponse:
    startup_complete = bool(getattr(request.app.state, "startup_complete", False))

    if not startup_complete:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return StartupResponse(status="started" if startup_complete else "starting")


@router.get("/health/ready", response_model=ReadinessResponse)
async def ready(request: Request, response: Response) -> ReadinessResponse:
    database: Database = request.app.state.database
    db_state = await database.readiness()

    if not db_state.ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(status="ready" if db_state.ready else "not_ready")


@router.get("/version")
async def version() -> dict[str, str]:
    return {"version": __version__}
