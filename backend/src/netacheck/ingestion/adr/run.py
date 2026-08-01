"""
ADR ingestion CLI runner.

Usage:
    python -m netacheck.ingestion.adr.run          # Full run (all 543 winners)
    python -m netacheck.ingestion.adr.run --limit 5  # Test: 5 candidates only
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import structlog

from netacheck.core.database import async_session_factory
from netacheck.ingestion.adr.normalizer import AdrNormalizer
from netacheck.ingestion.adr.parser import AdrParser
from netacheck.ingestion.adr.scraper import AdrScraper
from netacheck.ingestion.adr.writer import AdrWriter
from netacheck.ingestion.base import (
    DuplicateSnapshotError,
    RateLimiter,
    RobotsPolicy,
    ScraperHTTPError,
    ScraperSession,
)

logger = structlog.get_logger(__name__)


async def ingest_loksabha2024(limit: int | None = None) -> None:
    """
    Main ingestion coroutine.

    Iterates all Lok Sabha 2024 winner candidates and persists their affidavit
    data into the database.

    Args:
        limit: If set, stop after processing this many candidates (useful for testing).
    """
    parser = AdrParser()
    normalizer = AdrNormalizer()
    rate_limiter = RateLimiter(delay_seconds=2.0)
    robots_policy = RobotsPolicy()

    stats = {
        "processed": 0,
        "skipped_duplicate": 0,
        "skipped_sparse": 0,
        "errors": 0,
    }

    logger.info("ingest_start", election="loksabha2024", limit=limit)

    async with ScraperSession() as session:
        scraper = AdrScraper(
            session=session,
            rate_limiter=rate_limiter,
            robots_policy=robots_policy,
        )

        async for candidate_id in scraper.iter_winner_candidate_ids():
            if limit is not None and stats["processed"] >= limit:
                logger.info("ingest_limit_reached", limit=limit)
                break

            source_url = (
                f"https://myneta.info/loksabha2024/candidate.php?candidate_id={candidate_id}"
            )
            log = logger.bind(candidate_id=candidate_id)

            try:
                # 1. Fetch
                html = await scraper.fetch_candidate_detail(candidate_id)

                # 2. Parse
                raw = parser.parse(html, candidate_id=candidate_id, source_url=source_url)

                # 3. Normalise
                candidate = normalizer.normalise(raw)
                if candidate is None:
                    log.warning("candidate_sparse_skip", name=raw.name)
                    stats["skipped_sparse"] += 1
                    continue

                # 4. Write (in its own transaction per candidate)
                async with async_session_factory() as db:
                    try:
                        writer = AdrWriter(db)
                        await writer.write(candidate, html)
                        await db.commit()
                        stats["processed"] += 1
                        log.info(
                            "candidate_ingested",
                            name=candidate.name,
                            party=candidate.party_abbreviation,
                            constituency=candidate.constituency_name,
                            criminal_cases=len(candidate.criminal_cases),
                            assets=len(candidate.assets),
                        )
                    except DuplicateSnapshotError:
                        await db.rollback()
                        log.info("candidate_already_ingested", name=raw.name)
                        stats["skipped_duplicate"] += 1
                    except Exception:
                        await db.rollback()
                        raise

            except ScraperHTTPError as exc:
                log.warning("candidate_http_error", error=str(exc))
                stats["errors"] += 1
            except Exception as exc:
                log.error("candidate_error", error=str(exc), exc_info=True)
                stats["errors"] += 1

    logger.info(
        "ingest_complete",
        **stats,
    )

    if stats["errors"] > 0:
        logger.warning("ingest_had_errors", error_count=stats["errors"])


def main() -> None:
    arg_parser = argparse.ArgumentParser(
        description="Ingest ADR / MyNeta Lok Sabha 2024 affidavit data"
    )
    arg_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Stop after N candidates (useful for testing)",
    )
    args = arg_parser.parse_args()
    asyncio.run(ingest_loksabha2024(limit=args.limit))


if __name__ == "__main__":
    main()
