"""
Health check endpoint.

The health endpoint serves two purposes:
1. Liveness probe — is the process alive? (GET /api/v1/health)
2. Readiness probe — can it serve traffic? (GET /api/v1/health/ready)

The readiness probe checks database connectivity. If the DB is unreachable,
Kubernetes / Railway will stop sending traffic to this instance.

No authentication required. No rate limiting on health endpoints.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter
from fastapi.responses import ORJSONResponse
from sqlalchemy import text

from netacheck import __version__
from netacheck.core.config import settings
from netacheck.core.database import async_session_factory
from netacheck.core.logging import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    summary="Liveness check",
    description="Returns 200 if the process is alive.",
    response_description="Application status and version",
)
async def health() -> ORJSONResponse:
    """Liveness probe — confirms the process is running."""
    return ORJSONResponse(
        content={
            "status": "ok",
            "app": settings.app_name,
            "version": __version__,
            "environment": settings.environment,
            "timestamp": datetime.now(tz=UTC).isoformat(),
        }
    )


@router.get(
    "/health/ready",
    summary="Readiness check",
    description="Returns 200 if the application can serve traffic (DB reachable).",
)
async def health_ready() -> ORJSONResponse:
    """
    Readiness probe — confirms database connectivity.

    Returns HTTP 503 if the database is unreachable.
    """
    db_ok = False
    db_error: str | None = None

    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception as exc:
        db_error = str(exc)
        log.error("health_db_check_failed", error=db_error)

    status_code = 200 if db_ok else 503
    return ORJSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if db_ok else "degraded",
            "checks": {
                "database": {
                    "ok": db_ok,
                    "error": db_error,
                }
            },
            "version": __version__,
            "timestamp": datetime.now(tz=UTC).isoformat(),
        },
    )
