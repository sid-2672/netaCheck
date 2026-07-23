"""
FastAPI application factory and lifespan.

Design decisions:
- Application is created via a factory function (`create_app`) rather than
  a module-level global. This enables test isolation (each test can create
  a fresh app with overridden dependencies).
- The lifespan context manager handles startup/shutdown side effects cleanly
  (logging setup, DB pool initialization, graceful teardown).
- Exception handlers translate domain exceptions into RFC 7807 Problem Details
  responses so the frontend always receives a consistent error shape.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

from netacheck import __version__
from netacheck.api.middleware.logging import LoggingMiddleware
from netacheck.api.v1.router import v1_router
from netacheck.core.config import settings
from netacheck.core.database import dispose_engine
from netacheck.core.exceptions import (
    AuthorizationError,
    NetaCheckError,
    NotFoundError,
    SourceMissingError,
)
from netacheck.core.logging import configure_logging

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup and shutdown lifecycle."""
    # ---- Startup ----
    configure_logging()
    log.info(
        "netacheck_startup",
        version=__version__,
        environment=settings.environment,
        debug=settings.debug,
    )
    yield
    # ---- Shutdown ----
    log.info("netacheck_shutdown")
    await dispose_engine()


def create_app() -> FastAPI:
    """
    Construct and configure the FastAPI application.

    Returns a fully wired application instance ready to be served by Uvicorn.
    """
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "NetaCheck API — public record aggregation for Indian politicians. "
            "Every data point is cited. Every source is documented."
        ),
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url="/openapi.json" if not settings.is_production else None,
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
    )

    # -------------------------------------------------------------------------
    # Middleware
    # -------------------------------------------------------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["X-Api-Key", "Content-Type"],
    )
    app.add_middleware(LoggingMiddleware)

    # -------------------------------------------------------------------------
    # Exception handlers — translate domain errors to RFC 7807 Problem Details
    # -------------------------------------------------------------------------

    @app.exception_handler(NotFoundError)
    async def not_found_handler(request: Request, exc: NotFoundError) -> ORJSONResponse:
        return ORJSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"type": "not_found", "detail": exc.detail, "context": exc.context},
        )

    @app.exception_handler(SourceMissingError)
    async def source_missing_handler(
        request: Request, exc: SourceMissingError
    ) -> ORJSONResponse:
        log.error("source_missing_attempted_render", **exc.context)
        return ORJSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "type": "source_missing",
                "detail": exc.detail,
                "context": exc.context,
            },
        )

    @app.exception_handler(AuthorizationError)
    async def authorization_handler(
        request: Request, exc: AuthorizationError
    ) -> ORJSONResponse:
        return ORJSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"type": "unauthorized", "detail": exc.detail},
        )

    @app.exception_handler(NetaCheckError)
    async def domain_error_handler(
        request: Request, exc: NetaCheckError
    ) -> ORJSONResponse:
        log.warning("domain_error", detail=exc.detail, **exc.context)
        return ORJSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"type": "domain_error", "detail": exc.detail, "context": exc.context},
        )

    # -------------------------------------------------------------------------
    # Routers
    # -------------------------------------------------------------------------
    app.include_router(v1_router, prefix="/api/v1")

    return app


def main() -> None:
    """Entrypoint for running with `python -m netacheck` or `netacheck` CLI."""
    import uvicorn

    uvicorn.run(
        "netacheck.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        workers=settings.workers,
        reload=settings.reload,
        log_config=None,  # structlog handles logging
    )


# Module-level app instance — used by Uvicorn when invoked as:
#   uvicorn netacheck.main:app
app = create_app()
