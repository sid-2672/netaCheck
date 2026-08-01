"""
Async database engine and session factory.

Design decisions:
- asyncpg driver for maximum Postgres async throughput.
- Session is provided via FastAPI dependency injection (see core/dependencies.py).
- `Base` is imported by every model module to share metadata.
- `run_sync` helper is used by Alembic (which is synchronous) via env.py.

Never import `engine` or `async_session_factory` directly in business logic.
Always use the `get_db_session` dependency from `core/dependencies.py`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from netacheck.core.config import settings

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


class Base(DeclarativeBase):
    """
    Shared declarative base for all SQLAlchemy ORM models.

    All models must inherit from this class so that Alembic's autogenerate
    can discover them via `Base.metadata`.
    """


def _build_engine() -> AsyncEngine:
    """
    Construct the async SQLAlchemy engine from application settings.

    Connection pool parameters are tuned for a typical single-instance
    Railway/Render deployment. Adjust for higher concurrency as needed.
    """
    return create_async_engine(
        str(settings.database_url),
        echo=settings.database_echo,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout,
        pool_pre_ping=True,  # detect stale connections
        future=True,
    )


# Module-level engine — shared across the process lifetime
engine: AsyncEngine = _build_engine()

# Session factory — use `async_session_factory()` to open a session
async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,  # prevents lazy-load errors after commit
    autoflush=False,
    autocommit=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Async generator that yields one database session per request.

    Intended for use as a FastAPI dependency:
        session: AsyncSession = Depends(get_db_session)

    The session is automatically closed on exit. Rollback on exception
    is handled by the repository layer, not here.
    """
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


async def dispose_engine() -> None:
    """
    Dispose the connection pool gracefully.

    Called during application shutdown to release all connections
    before the process exits.
    """
    await engine.dispose()
