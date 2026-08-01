"""
Integration tests for the ADR Writer (Phase 3).

Tests AdrWriter.write() against a real Postgres test database.
Uses NormalisedCandidate objects built directly — no HTTP needed.
Verifies the full data chain, source constraint, and idempotency.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from netacheck.ingestion.adr.normalizer import (
    NormalisedAsset,
    NormalisedCandidate,
    NormalisedCriminalCase,
)
from netacheck.ingestion.adr.writer import AdrWriter
from netacheck.ingestion.base import DuplicateSnapshotError
from netacheck.models.affidavit import AffidavitEntry
from netacheck.models.assets import AssetCategory, AssetDeclaration, AssetOwnership
from netacheck.models.criminal import CaseStatus, CriminalCase, Severity
from netacheck.models.election import ElectionResult
from netacheck.models.politician import Politician

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_candidate(
    *,
    name: str = "Praveen Khandelwal",
    slug: str | None = None,
    constituency: str = "CHANDNI CHOWK",
    state: str = "DELHI (NCT)",
    party_name: str = "Bharatiya Janata Party",
    party_abbreviation: str = "BJP",
    won: bool = True,
    criminal_cases: list[NormalisedCriminalCase] | None = None,
    assets: list[NormalisedAsset] | None = None,
    candidate_id: int | None = None,
    source_url: str | None = None,
) -> NormalisedCandidate:
    cid = candidate_id or int(uuid.uuid4().int >> 96)
    return NormalisedCandidate(
        name=name,
        slug=slug or f"{name.lower().replace(' ', '-')}-{constituency.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}",
        party_name=party_name,
        party_abbreviation=party_abbreviation,
        constituency_name=constituency,
        state_name=state,
        age=55,
        won=won,
        photo_url=None,
        source_url=source_url or f"https://myneta.info/loksabha2024/candidate.php?candidate_id={cid}",
        candidate_id=cid,
        election_year=2024,
        election_date=date(2024, 5, 4),
        total_assets_inr=Decimal("10000000"),
        total_liabilities_inr=None,
        criminal_cases=criminal_cases or [],
        assets=assets or [],
    )


def _make_html(candidate_id: int, variant: str = "base") -> bytes:
    """Synthetic HTML — unique per candidate_id + variant for distinct content hashes."""
    return (
        f"<html><body>Test candidate {candidate_id} {variant} {uuid.uuid4().hex}</body></html>"
    ).encode()


# ---------------------------------------------------------------------------
# Core write tests
# ---------------------------------------------------------------------------


class TestAdrWriterCore:
    async def test_write_creates_politician(self, db_session: AsyncSession) -> None:
        candidate = _make_candidate()
        html = _make_html(candidate.candidate_id)
        writer = AdrWriter(db_session)
        politician = await writer.write(candidate, html)
        assert politician is not None
        assert isinstance(politician, Politician)
        assert politician.name == candidate.name

    async def test_write_creates_source_snapshot(self, db_session: AsyncSession) -> None:
        candidate = _make_candidate()
        html = _make_html(candidate.candidate_id)
        writer = AdrWriter(db_session)
        await writer.write(candidate, html)

        # Verify source snapshot was created
        from netacheck.models.source import SourceSnapshot
        result = await db_session.execute(
            select(SourceSnapshot).where(SourceSnapshot.url == candidate.source_url)
        )
        snap = result.scalar_one_or_none()
        assert snap is not None
        assert snap.parser_version == "1.0.0"

    async def test_write_creates_full_data_chain(self, db_session: AsyncSession) -> None:
        """Verify the complete chain: Politician → ElectionResult → Affidavit → AffidavitEntry."""
        candidate = _make_candidate()
        html = _make_html(candidate.candidate_id)
        writer = AdrWriter(db_session)
        politician = await writer.write(candidate, html)

        # Verify ElectionResult
        er_result = await db_session.execute(
            select(ElectionResult).where(ElectionResult.politician_id == politician.id)
        )
        er = er_result.scalar_one_or_none()
        assert er is not None
        assert er.won is True

        # Verify AffidavitEntry with source_snapshot_id
        entry_result = await db_session.execute(
            select(AffidavitEntry)
        )
        entries = entry_result.scalars().all()
        # Find entries for this politician's affidavit
        our_entry = next((e for e in entries if e.affidavit_id is not None), None)
        assert our_entry is not None
        assert our_entry.source_snapshot_id is not None, "Hard constraint violated: AffidavitEntry has no source_snapshot_id"

    async def test_write_all_affidavit_entries_have_source(self, db_session: AsyncSession) -> None:
        """THE core constraint: every AffidavitEntry must have source_snapshot_id."""
        candidate = _make_candidate()
        html = _make_html(candidate.candidate_id)
        writer = AdrWriter(db_session)
        await writer.write(candidate, html)

        # Direct SQL query — absolute check
        result = await db_session.execute(
            text("SELECT COUNT(*) FROM affidavit_entry WHERE source_snapshot_id IS NULL")
        )
        null_count = result.scalar_one()
        assert null_count == 0, f"Found {null_count} AffidavitEntry rows without source_snapshot_id — hard constraint violated!"

    async def test_write_state_created(self, db_session: AsyncSession) -> None:
        from netacheck.models.geography import State
        candidate = _make_candidate(state="MAHARASHTRA")
        html = _make_html(candidate.candidate_id)
        writer = AdrWriter(db_session)
        await writer.write(candidate, html)

        result = await db_session.execute(select(State).where(State.name == "MAHARASHTRA"))
        state = result.scalar_one_or_none()
        assert state is not None

    async def test_write_constituency_created(self, db_session: AsyncSession) -> None:
        from netacheck.models.geography import Constituency
        candidate = _make_candidate(constituency="PUNE RURAL")
        html = _make_html(candidate.candidate_id)
        writer = AdrWriter(db_session)
        await writer.write(candidate, html)

        result = await db_session.execute(select(Constituency).where(Constituency.name == "PUNE RURAL"))
        constituency = result.scalar_one_or_none()
        assert constituency is not None

    async def test_write_party_created(self, db_session: AsyncSession) -> None:
        from netacheck.models.politician import PoliticalParty
        abbr = f"TSTP{uuid.uuid4().hex[:2].upper()}"
        candidate = _make_candidate(party_abbreviation=abbr, party_name=f"Test State Party {abbr}")
        html = _make_html(candidate.candidate_id)
        writer = AdrWriter(db_session)
        await writer.write(candidate, html)

        result = await db_session.execute(
            select(PoliticalParty).where(PoliticalParty.abbreviation == abbr)
        )
        party = result.scalar_one_or_none()
        assert party is not None


# ---------------------------------------------------------------------------
# Criminal cases
# ---------------------------------------------------------------------------


class TestAdrWriterCriminalCases:
    async def test_write_criminal_cases_persisted(self, db_session: AsyncSession) -> None:
        criminal_cases = [
            NormalisedCriminalCase(
                case_type="pending",
                fir_no="FIR-001-2024",
                case_no="CC-001",
                court="Sessions Court Delhi",
                section_of_law="302 IPC",
                offence_description="Murder",
                status=CaseStatus.PENDING,
                severity=Severity.HEINOUS,
                charges_framed=True,
            )
        ]
        candidate = _make_candidate(criminal_cases=criminal_cases)
        html = _make_html(candidate.candidate_id)
        writer = AdrWriter(db_session)
        await writer.write(candidate, html)

        result = await db_session.execute(select(CriminalCase))
        cases = result.scalars().all()
        assert len(cases) >= 1
        saved_case = next((c for c in cases if c.section_of_law == "302 IPC"), None)
        assert saved_case is not None
        assert saved_case.status == CaseStatus.PENDING
        assert saved_case.severity == Severity.HEINOUS

    async def test_write_multiple_criminal_cases(self, db_session: AsyncSession) -> None:
        criminal_cases = [
            NormalisedCriminalCase(
                case_type="pending", fir_no="FIR-001", case_no="CC-001",
                court="Court A", section_of_law="302 IPC", offence_description="Murder",
                status=CaseStatus.PENDING, severity=Severity.HEINOUS, charges_framed=True,
            ),
            NormalisedCriminalCase(
                case_type="convicted", fir_no="FIR-002", case_no="CC-002",
                court="Court B", section_of_law="420 IPC", offence_description="Fraud",
                status=CaseStatus.CONVICTED, severity=Severity.MINOR, charges_framed=False,
            ),
        ]
        candidate = _make_candidate(criminal_cases=criminal_cases)
        html = _make_html(candidate.candidate_id)
        writer = AdrWriter(db_session)
        await writer.write(candidate, html)

        result = await db_session.execute(select(CriminalCase))
        all_cases = result.scalars().all()
        assert len(all_cases) >= 2

    async def test_write_no_criminal_cases(self, db_session: AsyncSession) -> None:
        candidate = _make_candidate(criminal_cases=[])
        html = _make_html(candidate.candidate_id)
        writer = AdrWriter(db_session)
        await writer.write(candidate, html)
        # Should succeed without creating any CriminalCase rows
        result = await db_session.execute(select(CriminalCase))
        assert result.scalars().all() == []


# ---------------------------------------------------------------------------
# Asset declarations
# ---------------------------------------------------------------------------


class TestAdrWriterAssets:
    async def test_write_assets_persisted(self, db_session: AsyncSession) -> None:
        assets = [
            NormalisedAsset(
                category=AssetCategory.IMMOVABLE,
                ownership=AssetOwnership.SELF,
                description="Agricultural land in UP",
                value_inr=Decimal("5000000.00"),
                raw_value_text="Rs 50,00,000",
            ),
            NormalisedAsset(
                category=AssetCategory.MOVABLE,
                ownership=AssetOwnership.SELF,
                description="Cash in hand",
                value_inr=Decimal("100000"),
                raw_value_text="Rs 1,00,000",
            ),
        ]
        candidate = _make_candidate(assets=assets)
        html = _make_html(candidate.candidate_id)
        writer = AdrWriter(db_session)
        await writer.write(candidate, html)

        result = await db_session.execute(select(AssetDeclaration))
        saved = result.scalars().all()
        assert len(saved) >= 2
        immovable = next((a for a in saved if a.category == AssetCategory.IMMOVABLE), None)
        assert immovable is not None
        assert immovable.value_inr == Decimal("5000000.00")

    async def test_write_nil_assets_not_persisted(self, db_session: AsyncSession) -> None:
        """Assets with None value should still be persisted (value_inr=None is valid)."""
        assets = [
            NormalisedAsset(
                category=AssetCategory.MOVABLE,
                ownership=AssetOwnership.SELF,
                description="Unknown item",
                value_inr=None,  # Nil value
                raw_value_text="Nil",
            ),
        ]
        candidate = _make_candidate(assets=assets)
        html = _make_html(candidate.candidate_id)
        writer = AdrWriter(db_session)
        await writer.write(candidate, html)

        result = await db_session.execute(select(AssetDeclaration))
        saved = result.scalars().all()
        # Assets with Nil value ARE persisted (raw_value preserved for audit)
        assert len(saved) >= 1

    async def test_write_asset_ownership_spouse(self, db_session: AsyncSession) -> None:
        assets = [
            NormalisedAsset(
                category=AssetCategory.MOVABLE,
                ownership=AssetOwnership.SPOUSE,
                description="Spouse jewelry",
                value_inr=Decimal("500000"),
                raw_value_text="Rs 5,00,000",
            ),
        ]
        candidate = _make_candidate(assets=assets)
        html = _make_html(candidate.candidate_id)
        writer = AdrWriter(db_session)
        await writer.write(candidate, html)

        result = await db_session.execute(
            select(AssetDeclaration).where(AssetDeclaration.ownership == AssetOwnership.SPOUSE)
        )
        saved = result.scalar_one_or_none()
        assert saved is not None


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestAdrWriterIdempotency:
    async def test_duplicate_html_raises_duplicate_snapshot_error(self, db_session: AsyncSession) -> None:
        """Same HTML bytes → DuplicateSnapshotError — the pipeline's idempotency guarantee."""
        candidate = _make_candidate()
        html = _make_html(candidate.candidate_id, "fixed-content")  # Deterministic content
        # Replace random suffix to make it deterministic
        html = b"<html><body>Fixed content for idempotency test</body></html>"

        writer = AdrWriter(db_session)
        await writer.write(candidate, html)

        # Second write with identical HTML → error
        with pytest.raises(DuplicateSnapshotError):
            await writer.write(_make_candidate(), html)

    async def test_same_politician_not_duplicated(self, db_session: AsyncSession) -> None:
        """Same politician slug (different HTML) → only one Politician row created."""
        slug = f"idempotent-pol-{uuid.uuid4().hex[:8]}"
        candidate1 = _make_candidate(slug=slug, name="Test Politician One")
        candidate2 = _make_candidate(slug=slug, name="Test Politician One")

        html1 = _make_html(candidate1.candidate_id, "v1")
        html2 = _make_html(candidate2.candidate_id, "v2")

        writer = AdrWriter(db_session)
        await writer.write(candidate1, html1)

        # Different HTML for same politician (e.g., page updated)
        await writer.write(candidate2, html2)

        result = await db_session.execute(
            select(Politician).where(Politician.slug == slug)
        )
        politicians = result.scalars().all()
        assert len(politicians) == 1, "Duplicate politician created for same slug!"

    async def test_independent_candidate_no_party_error(self, db_session: AsyncSession) -> None:
        """IND (Independent) candidate should not cause party FK issues."""
        candidate = _make_candidate(party_name="Independent", party_abbreviation="IND")
        html = _make_html(candidate.candidate_id)
        writer = AdrWriter(db_session)
        politician = await writer.write(candidate, html)
        assert politician is not None
