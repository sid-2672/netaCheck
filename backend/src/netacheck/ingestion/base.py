"""
Base infrastructure for all NetaCheck scrapers.

Every scraper must:
  - Check robots.txt before fetching any URL
  - Rate-limit requests per domain
  - Use exponential backoff on transient errors
  - Identify itself via User-Agent
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = structlog.get_logger(__name__)

USER_AGENT = (
    "NetaCheck-Scraper/1.0 "
    "(civic transparency platform; contact: contact@netacheck.in; "
    "https://netacheck.in/about)"
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ScraperError(Exception):
    """Base class for all scraper errors."""


class RobotsDisallowedError(ScraperError):
    """Raised when robots.txt disallows the requested URL."""


class ScraperHTTPError(ScraperError):
    """Raised on non-retriable HTTP errors (4xx client errors)."""


class DuplicateSnapshotError(ScraperError):
    """Raised when the content hash matches an existing SourceSnapshot — skip."""


# ---------------------------------------------------------------------------
# Rate limiter — simple token-bucket per domain
# ---------------------------------------------------------------------------


class RateLimiter:
    """
    Token-bucket rate limiter.

    Enforces a minimum delay between requests to the same domain.
    Default: 2 seconds (conservative — respects community sites).
    """

    def __init__(self, delay_seconds: float = 2.0) -> None:
        self._delay = delay_seconds
        self._last_call: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def wait(self, domain: str) -> None:
        async with self._lock:
            now = time.monotonic()
            last = self._last_call.get(domain, 0.0)
            gap = now - last
            if gap < self._delay:
                await asyncio.sleep(self._delay - gap)
            self._last_call[domain] = time.monotonic()


# ---------------------------------------------------------------------------
# Robots.txt checker
# ---------------------------------------------------------------------------


class RobotsPolicy:
    """
    Reads and caches robots.txt per domain.

    Raises RobotsDisallowedError if the URL is disallowed for our User-Agent.
    """

    def __init__(self) -> None:
        self._cache: dict[str, RobotFileParser] = {}

    async def check(self, url: str, session: ScraperSession) -> None:
        parsed = urlparse(url)
        domain = f"{parsed.scheme}://{parsed.netloc}"
        if domain not in self._cache:
            robots_url = urljoin(domain, "/robots.txt")
            try:
                resp = await session.get_raw(robots_url)
                parser = RobotFileParser()
                parser.set_url(robots_url)
                parser.parse(resp.decode("utf-8", errors="ignore").splitlines())
                self._cache[domain] = parser
                logger.debug("robots_txt_loaded", domain=domain)
            except Exception as exc:
                logger.warning("robots_txt_load_failed", domain=domain, error=str(exc))
                # If we can't read robots.txt, assume allowed (benefit of doubt)
                self._cache[domain] = RobotFileParser()

        parser = self._cache[domain]
        if not parser.can_fetch(USER_AGENT, url):
            raise RobotsDisallowedError(f"robots.txt disallows {url}")


# ---------------------------------------------------------------------------
# HTTP session
# ---------------------------------------------------------------------------


class ScraperSession:
    """
    Async HTTP client with retry, backoff, and User-Agent.

    Uses httpx.AsyncClient under the hood.
    """

    def __init__(self, timeout: float = 30.0) -> None:
        self._client: httpx.AsyncClient | None = None
        self._timeout = timeout

    async def __aenter__(self) -> ScraperSession:
        self._client = httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=self._timeout,
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @retry(
        retry=retry_if_exception_type(
            (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    async def get_raw(self, url: str) -> bytes:
        """Fetch URL and return raw bytes. Raises ScraperHTTPError on 4xx."""
        if self._client is None:
            raise RuntimeError("ScraperSession must be used as async context manager")

        logger.debug("http_get", url=url)
        response = await self._client.get(url)

        if response.status_code == 404:
            raise ScraperHTTPError(f"404 Not Found: {url}")
        if 400 <= response.status_code < 500:
            raise ScraperHTTPError(f"HTTP {response.status_code}: {url}")

        response.raise_for_status()
        return response.content


# ---------------------------------------------------------------------------
# Content hashing
# ---------------------------------------------------------------------------


def content_hash(data: bytes) -> str:
    """SHA-256 hex digest of raw bytes — used as idempotency key."""
    return hashlib.sha256(data).hexdigest()
