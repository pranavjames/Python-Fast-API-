from typing import Literal

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

from app.api.deps import SessionDep
from app.core.config import settings
from app.core.logging import get_logger

router = APIRouter(prefix="/health", tags=["Health"])
logger = get_logger(__name__)


class HealthStatus(BaseModel):
    status: Literal["ok", "unavailable"]
    version: str
    environment: str
    database: Literal["ok", "unavailable"] | None = None


@router.get("/live", response_model=HealthStatus, summary="Liveness probe")
async def liveness() -> HealthStatus:
    return HealthStatus(status="ok", version=settings.APP_VERSION, environment=settings.ENVIRONMENT)


@router.get(
    "/ready",
    response_model=HealthStatus,
    summary="Readiness probe (checks database connectivity)",
    responses={503: {"model": HealthStatus}},
)
async def readiness(session: SessionDep) -> HealthStatus | JSONResponse:
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Readiness check failed: database unavailable")
        body = HealthStatus(
            status="unavailable",
            version=settings.APP_VERSION,
            environment=settings.ENVIRONMENT,
            database="unavailable",
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=body.model_dump()
        )
    return HealthStatus(
        status="ok", version=settings.APP_VERSION, environment=settings.ENVIRONMENT, database="ok"
    )
