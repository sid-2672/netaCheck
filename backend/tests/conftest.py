"""
Test configuration and shared fixtures.

Fixtures use pytest-asyncio with `asyncio_mode = "auto"` (set in pyproject.toml).
Each test gets an isolated database transaction that is rolled back after the
test, so tests never pollute each other.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Test database — uses NullPool to prevent connection sharing across tests
# Postgres is mapped to host port 5433 (see docker-compose.yml POSTGRES_PORT=5433)
# Credentials match .env (POSTGRES_USER / POSTGRES_PASSWORD)
# ---------------------------------------------------------------------------
import os
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from netacheck.core.database import Base, get_db_session
from netacheck.main import create_app

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from fastapi import FastAPI

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://netacheck:netacheck_dev_password@localhost:5433/netacheck_test"
)
TEST_DATABASE_URL = (
    os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL") or DEFAULT_TEST_DATABASE_URL
)


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line("markers", "integration: marks tests as integration tests (require DB)")
    config.addinivalue_line("markers", "unit: marks tests as pure unit tests (no DB)")


@pytest.fixture(scope="session")
def test_engine() -> AsyncEngine:
    """Session-scoped engine for the test database."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        poolclass=NullPool,
        future=True,
    )
    return engine


@pytest_asyncio.fixture(scope="session")
async def create_tables(test_engine: AsyncEngine) -> AsyncGenerator[None, None]:
    """Create all tables once per test session, drop on teardown."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()


@pytest_asyncio.fixture
async def db_session(
    test_engine: AsyncEngine, create_tables: None
) -> AsyncGenerator[AsyncSession, None]:
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
