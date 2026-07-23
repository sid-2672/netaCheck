"""
Unit tests for the health check endpoints.

These tests do not hit a real database — they use the dependency override
pattern to inject a mock session.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from netacheck import __version__


@pytest.mark.asyncio
async def test_health_returns_200(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert body["app"] == "NetaCheck"
    assert "timestamp" in body


@pytest.mark.asyncio
async def test_health_response_has_environment(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    body = response.json()
    assert body["environment"] in {"development", "staging", "production", "test"}


@pytest.mark.asyncio
async def test_request_id_header_present(client: AsyncClient) -> None:
    """Every response must include an X-Request-Id header for traceability."""
    response = await client.get("/api/v1/health")
    assert "x-request-id" in response.headers
    request_id = response.headers["x-request-id"]
    assert len(request_id) == 36  # UUID4 format
