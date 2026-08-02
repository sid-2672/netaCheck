"""
PRS India scraper.

Responsible only for HTTP fetch — no parsing logic here.

PRS India (https://prsindia.org) provides:
- MP attendance by parliamentary session
- Legislative activity: questions, debates, bills

URL patterns used:
  Attendance:         https://prsindia.org/mptrack/attendance
  MP attendance page: https://prsindia.org/mptrack/17/attendance/{mp_id}
  MP activity page:   https://prsindia.org/mptrack/17/questions/{mp_id}

Note on 17th Lok Sabha vs 18th:
  - 17th Lok Sabha ran 2019-2024.
  - 18th Lok Sabha began June 2024.
  We default to 18th Lok Sabha (number=18) for current data.
  The writer records `lok_sabha_number` on LegislativeTerm.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from netacheck.ingestion.base import (
    RateLimiter,
    RobotsPolicy,
    ScraperHTTPError,
    ScraperSession,
)

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)

BASE_URL = "https://prsindia.org"
DEFAULT_LOK_SABHA_NUMBER = 18  # 18th Lok Sabha (Jun 2024 onwards)


class PrsScraper:
    """
    Fetches HTML pages from prsindia.org.

    Follows the same base infrastructure as AdrScraper:
      - robots.txt checked per domain
      - Rate-limited (default 2s between requests — PRS is a small site)
      - Exponential backoff on transient errors

    Usage:
        async with ScraperSession() as session:
            scraper = PrsScraper(session, rate_limiter, robots_policy)
            html = await scraper.fetch_mp_attendance(mp_id=4190)
    """

    def __init__(
        self,
        session: ScraperSession,
        rate_limiter: RateLimiter,
        robots_policy: RobotsPolicy,
        lok_sabha_number: int = DEFAULT_LOK_SABHA_NUMBER,
    ) -> None:
        self._session = session
        self._rate_limiter = rate_limiter
        self._robots = robots_policy
        self._lok_sabha_number = lok_sabha_number
        self._domain = "prsindia.org"

    # ------------------------------------------------------------------
    # URL builders
    # ------------------------------------------------------------------

    def _mp_attendance_url(self, mp_id: int) -> str:
        """
        URL for an MP's attendance summary page.

        Pattern: /mptrack/{lok_sabha_number}/attendance/{mp_id}
        """
        return f"{BASE_URL}/mptrack/{self._lok_sabha_number}/attendance/{mp_id}"

    def _mp_activity_url(self, mp_id: int) -> str:
        """
        URL for an MP's legislative activity page (questions raised, debates, bills).

        Pattern: /mptrack/{lok_sabha_number}/questions/{mp_id}
        """
        return f"{BASE_URL}/mptrack/{self._lok_sabha_number}/questions/{mp_id}"

    def _mp_profile_url(self, mp_id: int) -> str:
        """
        URL for an MP's profile landing page.

        Pattern: /mptrack/{lok_sabha_number}/{mp_id}
        """
        return f"{BASE_URL}/mptrack/{self._lok_sabha_number}/{mp_id}"

    # ------------------------------------------------------------------
    # Fetch methods
    # ------------------------------------------------------------------

    async def _fetch(self, url: str) -> bytes:
        """Rate-limit + robots check + HTTP GET."""
        await self._robots.check(url, self._session)
        await self._rate_limiter.wait(self._domain)
        return await self._session.get_raw(url)

    async def fetch_mp_attendance(self, mp_id: int) -> bytes:
        """
        Return raw HTML for an MP's attendance page.

        Raises ScraperHTTPError if the MP does not exist (404).
        """
        url = self._mp_attendance_url(mp_id)
        logger.debug("fetch_mp_attendance", mp_id=mp_id, url=url)
        return await self._fetch(url)

    async def fetch_mp_activity(self, mp_id: int) -> bytes:
        """
        Return raw HTML for an MP's legislative questions/activity page.

        Raises ScraperHTTPError if the page does not exist.
        """
        url = self._mp_activity_url(mp_id)
        logger.debug("fetch_mp_activity", mp_id=mp_id, url=url)
        return await self._fetch(url)

    async def fetch_mp_profile(self, mp_id: int) -> bytes:
        """
        Return raw HTML for an MP's profile landing page.

        Used to extract MP name, constituency, party, and other metadata.
        """
        url = self._mp_profile_url(mp_id)
        logger.debug("fetch_mp_profile", mp_id=mp_id, url=url)
        return await self._fetch(url)

    async def try_fetch_mp_attendance(self, mp_id: int) -> bytes | None:
        """
        Fetch MP attendance page, returning None if not found (404).

        Suitable for batch iteration where some IDs may not exist.
        """
        try:
            return await self.fetch_mp_attendance(mp_id)
        except ScraperHTTPError as exc:
            logger.debug("mp_attendance_skip", mp_id=mp_id, reason=str(exc))
            return None

    async def try_fetch_mp_activity(self, mp_id: int) -> bytes | None:
        """
        Fetch MP activity page, returning None if not found (404).
        """
        try:
            return await self.fetch_mp_activity(mp_id)
        except ScraperHTTPError as exc:
            logger.debug("mp_activity_skip", mp_id=mp_id, reason=str(exc))
            return None
