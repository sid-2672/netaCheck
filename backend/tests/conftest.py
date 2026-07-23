"""
Test configuration and shared fixtures.

Fixtures use pytest-asyncio with `asyncio_mode = "auto"` (set in pyproject.toml).
Each test gets an isolated database transaction that is rolled back after the
test, so tests never pollute each other.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from netacheck.core.database import Base, get_db_session
from netacheck.main import create_app

# ---------------------------------------------------------------------------
# Test database — uses NullPool to prevent connection sharing across tests
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = (
    "postgresql+asyncpg://netacheck_test:netacheck_test@localhost:5432/netacheck_test"
)


@pytest.fixture(scope="session")
def test_engine():
    """Session-scoped engine for the test database."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        poolclass=NullPool,
        future=True,
    )
    return engine


@pytest_asyncio.fixture(scope="session")
async def create_tables(test_engine):
    """Create all tables once per test session, drop on teardown."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine, create_tables) -> AsyncGenerator[AsyncSession, None]:
    """
    Per-test database session wrapped in a transaction that is always rolled back.

    This keeps tests fast (no truncation needed) and fully isolated.
    """
    async with test_engine.connect() as conn:
        await conn.begin()
        session_factory = async_sessionmaker(
            bind=conn,
            expire_on_commit=False,
            autoflush=False,
        )
        async with session_factory() as session:
            yield session
        await conn.rollback()


@pytest.fixture
def app(db_session: AsyncSession) -> FastAPI:
    """
    Return a FastAPI app with the database dependency overridden to use
    the test session (which is always rolled back after the test).
    """
    application = create_app()

    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    application.dependency_overrides[get_db_session] = override_db
    return application


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP test client bound to the test app."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac
