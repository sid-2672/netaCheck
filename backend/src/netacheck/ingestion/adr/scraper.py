"""
ADR / MyNeta scraper.

Responsible only for fetching HTML pages — no parsing logic here.
URL pattern: https://myneta.info/loksabha2024/
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator

import structlog

from netacheck.ingestion.base import (
    RateLimiter,
    RobotsPolicy,
    ScraperHTTPError,
    ScraperSession,
)

logger = structlog.get_logger(__name__)

BASE_URL = "https://myneta.info"
ELECTION_FOLDER = "loksabha2024"

# MyNeta Lok Sabha 2024 has constituency IDs 1–580 (not all exist — gaps OK)
LS2024_CONSTITUENCY_IDS = list(range(1, 581))


class AdrScraper:
    """
    Fetches HTML pages from myneta.info.

    Usage:
        async with ScraperSession() as session:
            scraper = AdrScraper(session, rate_limiter, robots_policy)
            html = await scraper.fetch_candidate_detail(candidate_id=7896)
    """

    def __init__(
        self,
        session: ScraperSession,
        rate_limiter: RateLimiter,
        robots_policy: RobotsPolicy,
        election_folder: str = ELECTION_FOLDER,
    ) -> None:
        self._session = session
        self._rate_limiter = rate_limiter
        self._robots = robots_policy
        self._folder = election_folder
        self._domain = "myneta.info"

    def _candidates_list_url(self, constituency_id: int) -> str:
        return (
            f"{BASE_URL}/{self._folder}/index.php"
            f"?action=show_candidates&constituency_id={constituency_id}"
        )

    def _candidate_detail_url(self, candidate_id: int) -> str:
        return f"{BASE_URL}/{self._folder}/candidate.php?candidate_id={candidate_id}"

    async def _fetch(self, url: str) -> bytes:
        """Rate-limit + robots check + fetch."""
        await self._robots.check(url, self._session)
        await self._rate_limiter.wait(self._domain)
        return await self._session.get_raw(url)

    async def fetch_candidate_list(self, constituency_id: int) -> bytes:
        """Return raw HTML for the candidate list page of a constituency."""
        url = self._candidates_list_url(constituency_id)
        logger.debug("fetch_candidate_list", constituency_id=constituency_id, url=url)
        return await self._fetch(url)

    async def fetch_candidate_detail(self, candidate_id: int) -> bytes:
        """Return raw HTML for an individual candidate's affidavit detail page."""
        url = self._candidate_detail_url(candidate_id)
        logger.debug("fetch_candidate_detail", candidate_id=candidate_id, url=url)
        return await self._fetch(url)

    async def iter_winner_candidate_ids(self) -> AsyncIterator[int]:
        """
        Iterate over candidate_ids of election winners across all constituencies.

        Parses each constituency list page and yields IDs where '(Winner)' is
        present next to the candidate name.

        Silently skips constituencies that 404 or have no candidates listed.
        """
        # Pattern for candidate links: candidate.php?candidate_id=NNN
        candidate_link_re = re.compile(r"candidate\.php\?candidate_id=(\d+)")
        # Pattern that identifies a winner row (green "Winner" text)
        winner_marker_re = re.compile(r"Winner", re.IGNORECASE)

        for cid in LS2024_CONSTITUENCY_IDS:
            try:
                html = await self.fetch_candidate_list(cid)
            except ScraperHTTPError as exc:
                logger.debug("constituency_skip", constituency_id=cid, reason=str(exc))
                continue
            except Exception as exc:
                logger.warning("constituency_fetch_error", constituency_id=cid, error=str(exc))
                continue

            text = html.decode("utf-8", errors="ignore")

            # Find all <tr> blocks, look for winner + candidate_id together
            # The list page emits one <tr> per candidate with optional "Winner" font tag
            # Strategy: find rows that contain both a candidate link and "Winner"
            # Split on <tr> boundaries
            rows = re.split(r"<tr[\s>]", text, flags=re.IGNORECASE)
            for row in rows:
                if winner_marker_re.search(row):
                    match = candidate_link_re.search(row)
                    if match:
                        candidate_id = int(match.group(1))
                        logger.info(
                            "winner_found",
                            constituency_id=cid,
                            candidate_id=candidate_id,
                        )
                        yield candidate_id
