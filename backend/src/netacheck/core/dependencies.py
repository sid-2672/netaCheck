"""
FastAPI dependency providers.

All shared resources (database session, settings, admin auth) are injected
via FastAPI's Depends() mechanism. This keeps route handlers thin and testable —
in tests, override dependencies via `app.dependency_overrides`.

Usage in a route:
    @router.get("/example")
    async def example(
        session: DbSession,
        _: AdminUser,
    ) -> dict:
        ...
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from netacheck.core.config import Settings, get_settings
from netacheck.core.database import get_db_session

# ---------------------------------------------------------------------------
# Typed aliases — import these in route files for clean signatures
# ---------------------------------------------------------------------------

#: Annotated AsyncSession — used in route function signatures
DbSession = Annotated[AsyncSession, Depends(get_db_session)]

#: Annotated Settings — injected where route handlers need config
AppSettings = Annotated[Settings, Depends(get_settings)]


# ---------------------------------------------------------------------------
# Admin authentication
# ---------------------------------------------------------------------------


async def require_admin(
    x_api_key: Annotated[str | None, Header(alias="X-Api-Key")] = None,
    settings: Settings = Depends(get_settings),
) -> bool:
    """
    Validate the `X-Api-Key` header against the configured admin API key.

    Returns True if valid; raises HTTP 401 otherwise.

    Design: MVP uses a static API key. Future phases can swap this dependency
    for JWT/OAuth without changing any route handler signatures.
    """
    if x_api_key is None or x_api_key != settings.admin_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing admin API key.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return True


#: Annotated dependency — use in admin route signatures
AdminUser = Annotated[bool, Depends(require_admin)]


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


class PaginationParams:
    """
    Standard pagination query parameters.

    Usage:
        @router.get("/items")
        async def list_items(pagination: PaginationDep) -> ...:
            skip = pagination.skip
            limit = pagination.limit
    """

    def __init__(
        self,
        page: int = 1,
        page_size: int = 20,
    ) -> None:
        if page < 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="'page' must be >= 1",
            )
        if page_size < 1 or page_size > 100:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="'page_size' must be between 1 and 100",
            )
        self.page = page
        self.page_size = page_size

    @property
    def skip(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


#: Annotated pagination dependency
PaginationDep = Annotated[PaginationParams, Depends(PaginationParams)]
