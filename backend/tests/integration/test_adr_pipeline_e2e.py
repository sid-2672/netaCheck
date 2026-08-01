"""
End-to-end pipeline test for Phase 3 (ADR ingestion).

Feeds real fixture HTML bytes through the full pipeline:
  AdrParser → AdrNormalizer → AdrWriter → Postgres

No HTTP requests — all data comes from committed fixture files.
Validates that a complete, sourced data chain is created in the DB.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from netacheck.ingestion.adr.normalizer import AdrNormalizer
from netacheck.ingestion.adr.parser import AdrParser
from netacheck.ingestion.adr.writer import AdrWriter
from netacheck.ingestion.base import DuplicateSnapshotError
from netacheck.models.affidavit import AffidavitEntry
from netacheck.models.assets import AssetDeclaration
from netacheck.models.criminal import CriminalCase
from netacheck.models.election import ElectionResult
from netacheck.models.geography import Constituency, State
from netacheck.models.politician import PoliticalParty, Politician, PoliticianAlias
from netacheck.models.source import SourceProvider, SourceSnapshot

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).parent.parent / "fixtures" / "adr_html"


def _load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _count_result(scalars: list) -> int:
    return len(scalars)


# ---------------------------------------------------------------------------
# Full E2E pipeline tests
# ---------------------------------------------------------------------------


class TestAdrPipelineE2E:
    """Full pipeline: real HTML fixtures → parser → normalizer → writer → DB."""

    async def test_winner_with_cases_pipeline(self, db_session: AsyncSession) -> None:
        """
        Praveen Khandelwal (BJP, Chandni Chowk) — winner.
        Verifies the full data chain is created from real HTML.
        """
        html = _load("candidate_winner_with_cases.html")
        source_url = "https://myneta.info/loksabha2024/candidate.php?candidate_id=7896"

        raw = AdrParser().parse(html, candidate_id=7896, source_url=source_url)
        candidate = AdrNormalizer().normalise(raw)

        assert candidate is not None, "Normalizer returned None — page is too sparse or parse failed"
        assert "khandelwal" in candidate.slug.lower()
        assert candidate.won is True

        writer = AdrWriter(db_session)
        politician = await writer.write(candidate, html)

        assert politician is not None
        assert isinstance(politician, Politician)

    async def test_clean_winner_pipeline(self, db_session: AsyncSession) -> None:
        """
        Sumathy T (DMK, Chennai South) — winner with asset data.
        """
        html = _load("candidate_winner_clean.html")
        source_url = "https://myneta.info/loksabha2024/candidate.php?candidate_id=100"

        raw = AdrParser().parse(html, candidate_id=100, source_url=source_url)
        candidate = AdrNormalizer().normalise(raw)

        assert candidate is not None
        assert "sumathy" in candidate.slug.lower() or "chennai" in candidate.slug.lower()

        writer = AdrWriter(db_session)
        politician = await writer.write(candidate, html)
        assert politician is not None

    async def test_sparse_page_normalizer_returns_none(self, db_session: AsyncSession) -> None:
        """
        candidate_id=9999 — Page Not Found.
        Normalizer must return None (no data to write).
        """
        html = _load("candidate_sparse.html")
        source_url = "https://myneta.info/loksabha2024/candidate.php?candidate_id=9999"

        raw = AdrParser().parse(html, candidate_id=9999, source_url=source_url)
        candidate = AdrNormalizer().normalise(raw)

        # "Page Not Found" page should fail normalisation (no name/constituency)
        assert candidate is None, "Expected None for a 'Page Not Found' page"


class TestAdrPipelineDataIntegrity:
    """Verify data integrity of pipeline output in the database."""

    async def test_source_snapshot_created(self, db_session: AsyncSession) -> None:
        html = _load("candidate_winner_with_cases.html")
        source_url = "https://myneta.info/loksabha2024/candidate.php?candidate_id=7896"
        raw = AdrParser().parse(html, candidate_id=7896, source_url=source_url)
        candidate = AdrNormalizer().normalise(raw)
        assert candidate is not None

        writer = AdrWriter(db_session)
        await writer.write(candidate, html)

        # Verify SourceSnapshot exists
        result = await db_session.execute(select(SourceSnapshot).where(SourceSnapshot.url == source_url))
        snap = result.scalar_one_or_none()
        assert snap is not None
        assert snap.parser_version == "1.0.0"
        assert snap.raw_content_size_bytes == len(html)

    async def test_source_provider_created(self, db_session: AsyncSession) -> None:
        html = _load("candidate_winner_with_cases.html")
        source_url = "https://myneta.info/loksabha2024/candidate.php?candidate_id=7896"
        raw = AdrParser().parse(html, candidate_id=7896, source_url=source_url)
        candidate = AdrNormalizer().normalise(raw)
        assert candidate is not None

        writer = AdrWriter(db_session)
        await writer.write(candidate, html)

        result = await db_session.execute(
            select(SourceProvider).where(SourceProvider.short_code == "MYNETA")
        )
        provider = result.scalar_one_or_none()
        assert provider is not None
        assert "myneta" in provider.base_url.lower()

    async def test_all_affidavit_entries_have_source_after_pipeline(self, db_session: AsyncSession) -> None:
        """
        THE most critical integrity check.
        After running the pipeline, zero AffidavitEntry rows should have null source_snapshot_id.
        """
        html = _load("candidate_winner_with_cases.html")
        source_url = "https://myneta.info/loksabha2024/candidate.php?candidate_id=7896"
        raw = AdrParser().parse(html, candidate_id=7896, source_url=source_url)
        candidate = AdrNormalizer().normalise(raw)
        assert candidate is not None

        writer = AdrWriter(db_session)
        await writer.write(candidate, html)

        result = await db_session.execute(
            text("SELECT COUNT(*) FROM affidavit_entry WHERE source_snapshot_id IS NULL")
        )
        null_count = result.scalar_one()
        assert null_count == 0, (
            f"CONSTRAINT VIOLATION: {null_count} AffidavitEntry rows have null source_snapshot_id"
        )

    async def test_politician_alias_created(self, db_session: AsyncSession) -> None:
        html = _load("candidate_winner_with_cases.html")
        source_url = "https://myneta.info/loksabha2024/candidate.php?candidate_id=7896"
        raw = AdrParser().parse(html, candidate_id=7896, source_url=source_url)
        candidate = AdrNormalizer().normalise(raw)
        assert candidate is not None

        writer = AdrWriter(db_session)
        politician = await writer.write(candidate, html)

        result = await db_session.execute(
            select(PoliticianAlias).where(PoliticianAlias.politician_id == politician.id)
        )
        aliases = result.scalars().all()
        assert len(aliases) >= 1
        assert any(a.source == "myneta.info" for a in aliases)


class TestAdrPipelineIdempotency:
    """Verify idempotency: running the pipeline twice with the same HTML is safe."""

    async def test_re_run_same_html_raises_duplicate_snapshot_error(self, db_session: AsyncSession) -> None:
        """
        Running the pipeline twice with the exact same HTML bytes must raise
        DuplicateSnapshotError on the second run — not silently create duplicate data.
        """
        html = _load("candidate_winner_with_cases.html")
        source_url = "https://myneta.info/loksabha2024/candidate.php?candidate_id=7896"
        raw = AdrParser().parse(html, candidate_id=7896, source_url=source_url)
        candidate = AdrNormalizer().normalise(raw)
        assert candidate is not None

        writer = AdrWriter(db_session)
        await writer.write(candidate, html)  # First run — succeeds

        # Second run with same HTML — must raise DuplicateSnapshotError
        with pytest.raises(DuplicateSnapshotError):
            await writer.write(candidate, html)

    async def test_state_not_duplicated_on_re_run(self, db_session: AsyncSession) -> None:
        """Running two different pages from the same state → state created only once."""
        html1 = _load("candidate_winner_with_cases.html")
        html2 = _load("candidate_winner_clean.html")

        url1 = "https://myneta.info/loksabha2024/candidate.php?candidate_id=7896"
        url2 = "https://myneta.info/loksabha2024/candidate.php?candidate_id=100"

        raw1 = AdrParser().parse(html1, candidate_id=7896, source_url=url1)
        raw2 = AdrParser().parse(html2, candidate_id=100, source_url=url2)

        cand1 = AdrNormalizer().normalise(raw1)
        cand2 = AdrNormalizer().normalise(raw2)

        writer = AdrWriter(db_session)

        if cand1:
            await writer.write(cand1, html1)
        if cand2:
            await writer.write(cand2, html2)

        # Verify states are not duplicated
        result = await db_session.execute(select(State))
        states = result.scalars().all()
        state_names = [s.name for s in states]
        # Each state name should appear exactly once
        for name in state_names:
            assert state_names.count(name) == 1, f"State '{name}' duplicated in DB!"


class TestAdrPipelineWithCriminalCasesFixture:
    """Verify criminal case data is correctly persisted from real HTML."""

    async def test_criminal_cases_have_affidavit_entry_link(self, db_session: AsyncSession) -> None:
        html = _load("candidate_winner_with_cases.html")
        source_url = "https://myneta.info/loksabha2024/candidate.php?candidate_id=7896"
        raw = AdrParser().parse(html, candidate_id=7896, source_url=source_url)
        candidate = AdrNormalizer().normalise(raw)
        assert candidate is not None

        writer = AdrWriter(db_session)
        await writer.write(candidate, html)

        # All criminal cases must have affidavit_entry_id
        result = await db_session.execute(
            text("SELECT COUNT(*) FROM criminal_case WHERE affidavit_entry_id IS NULL")
        )
        null_count = result.scalar_one()
        assert null_count == 0

    async def test_assets_have_affidavit_entry_link(self, db_session: AsyncSession) -> None:
        html = _load("candidate_winner_with_cases.html")
        source_url = "https://myneta.info/loksabha2024/candidate.php?candidate_id=7896"
        raw = AdrParser().parse(html, candidate_id=7896, source_url=source_url)
        candidate = AdrNormalizer().normalise(raw)
        assert candidate is not None

        writer = AdrWriter(db_session)
        await writer.write(candidate, html)

        # All assets must have affidavit_entry_id
        result = await db_session.execute(
            text("SELECT COUNT(*) FROM asset_declaration WHERE affidavit_entry_id IS NULL")
        )
        null_count = result.scalar_one()
        assert null_count == 0
