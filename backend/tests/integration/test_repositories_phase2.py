"""
Integration tests for Phase 2: Repository layer.

Tests every repository method against a real Postgres database.
Each test uses the rollback-per-test isolation from conftest.py.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from netacheck.models.affidavit import Affidavit, AffidavitEntry
from netacheck.models.assets import AssetCategory, AssetDeclaration, AssetOwnership
from netacheck.models.attendance import AttendanceRecord
from netacheck.models.criminal import CaseStatus, CriminalCase, Severity
from netacheck.models.election import Election, ElectionResult, ElectionType
from netacheck.models.geography import Constituency, ConstituencyType, State
from netacheck.models.grading import (
    Confidence,
    GradeLetter,
    GradeMetricResult,
    GradeSnapshot,
)
from netacheck.models.legislative import LegislativeActivity, ActivityType
from netacheck.models.legislature import LegislativeTerm
from netacheck.models.politician import Gender, House, PartyMembership, PoliticalParty, Politician
from netacheck.models.source import SourceProvider, SourceSnapshot
from netacheck.repositories.base import AsyncRepository
from netacheck.repositories.politician import PoliticianRepository
from netacheck.repositories.report_card import ReportCardRepository
from netacheck.repositories.source import SourceSnapshotRepository

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers — reused from test_models_phase2 (duplicated here for independence)
# ---------------------------------------------------------------------------


async def _make_state(session: AsyncSession, name: str | None = None) -> State:
    n = name or f"State {uuid.uuid4().hex[:6]}"
    state = State(
        name=n,
        slug=f"state-{uuid.uuid4().hex[:8]}",
        iso_code=f"IN{uuid.uuid4().hex[:3].upper()}",
        is_union_territory=False,
    )
    session.add(state)
    await session.flush()
    return state


async def _make_party(session: AsyncSession) -> PoliticalParty:
    party = PoliticalParty(
        name=f"Test Party {uuid.uuid4().hex[:6]}",
        slug=f"tp-{uuid.uuid4().hex[:8]}",
        abbreviation=f"TP{uuid.uuid4().hex[:2].upper()}",
    )
    session.add(party)
    await session.flush()
    return party


async def _make_politician(session: AsyncSession, *, name: str | None = None, slug: str | None = None) -> Politician:
    p = Politician(
        name=name or f"Test Politician {uuid.uuid4().hex[:6]}",
        slug=slug or f"tp-{uuid.uuid4().hex[:10]}",
    )
    session.add(p)
    await session.flush()
    return p


async def _make_provider(session: AsyncSession) -> SourceProvider:
    sp = SourceProvider(
        name=f"Test Provider {uuid.uuid4().hex[:4]}",
        short_code=f"TP{uuid.uuid4().hex[:4].upper()}",
        base_url="https://test.example.com",
    )
    session.add(sp)
    await session.flush()
    return sp


async def _make_snapshot(session: AsyncSession, provider: SourceProvider, content: bytes | None = None) -> SourceSnapshot:
    c = content or f"html-{uuid.uuid4()}".encode()
    snap = SourceSnapshot(
        provider_id=provider.id,
        url=f"https://test.example.com/{uuid.uuid4()}",
        url_hash=hashlib.sha256(f"url-{uuid.uuid4()}".encode()).hexdigest(),
        content_hash=hashlib.sha256(c).hexdigest(),
        fetched_at=datetime.now(tz=timezone.utc),
        parser_version="1.0.0",
    )
    session.add(snap)
    await session.flush()
    return snap


async def _make_full_data_chain(session: AsyncSession) -> tuple[Politician, AffidavitEntry]:
    """Create a complete politician → affidavit_entry data chain."""
    state = await _make_state(session)
    constituency = Constituency(
        name=f"C {uuid.uuid4().hex[:6]}", slug=f"c-{uuid.uuid4().hex[:8]}",
        state_id=state.id, constituency_type=ConstituencyType.LOK_SABHA,
    )
    session.add(constituency)
    await session.flush()

    election = Election(
        constituency_id=constituency.id, election_type=ElectionType.GENERAL,
        election_date=date(2024, 5, 4), year=2024,
    )
    session.add(election)
    await session.flush()

    politician = await _make_politician(session)
    party = await _make_party(session)
    er = ElectionResult(election_id=election.id, politician_id=politician.id, party_id=party.id, won=True)
    session.add(er)
    await session.flush()

    provider = await _make_provider(session)
    snap = await _make_snapshot(session, provider)
    affidavit = Affidavit(election_result_id=er.id, source_snapshot_id=snap.id)
    session.add(affidavit)
    await session.flush()

    entry = AffidavitEntry(affidavit_id=affidavit.id, source_snapshot_id=snap.id, field_name="affidavit_full")
    session.add(entry)
    await session.flush()

    return politician, entry


# ---------------------------------------------------------------------------
# Base Repository
# ---------------------------------------------------------------------------


class TestBaseRepository:
    """Tests for AsyncRepository[T] generic methods."""

    async def test_create(self, db_session: AsyncSession) -> None:
        class StateRepo(AsyncRepository[State]):
            model = State

        repo = StateRepo(db_session)
        state = await repo.create(
            name="Repo Test State",
            slug=f"repo-test-{uuid.uuid4().hex[:8]}",
            iso_code=f"RT{uuid.uuid4().hex[:3].upper()}",
            is_union_territory=False,
        )
        assert state.id is not None
        assert state.name == "Repo Test State"

    async def test_get_by_id(self, db_session: AsyncSession) -> None:
        class StateRepo(AsyncRepository[State]):
            model = State

        repo = StateRepo(db_session)
        state = await repo.create(
            name="Get By Id State",
            slug=f"gbi-{uuid.uuid4().hex[:8]}",
            iso_code=f"GB{uuid.uuid4().hex[:3].upper()}",
            is_union_territory=False,
        )
        fetched = await repo.get_by_id(state.id)
        assert fetched is not None
        assert fetched.id == state.id

    async def test_get_by_id_missing_returns_none(self, db_session: AsyncSession) -> None:
        class StateRepo(AsyncRepository[State]):
            model = State

        repo = StateRepo(db_session)
        result = await repo.get_by_id(uuid.uuid4())
        assert result is None

    async def test_get_by_slug(self, db_session: AsyncSession) -> None:
        class StateRepo(AsyncRepository[State]):
            model = State

        repo = StateRepo(db_session)
        slug = f"slug-test-{uuid.uuid4().hex[:8]}"
        await repo.create(name="Slug State", slug=slug, iso_code=f"SL{uuid.uuid4().hex[:3].upper()}", is_union_territory=False)
        found = await repo.get_by_slug(slug)
        assert found is not None
        assert found.slug == slug

    async def test_get_by_slug_missing_returns_none(self, db_session: AsyncSession) -> None:
        class StateRepo(AsyncRepository[State]):
            model = State

        repo = StateRepo(db_session)
        result = await repo.get_by_slug("definitely-not-existing-slug")
        assert result is None

    async def test_update(self, db_session: AsyncSession) -> None:
        class StateRepo(AsyncRepository[State]):
            model = State

        repo = StateRepo(db_session)
        state = await repo.create(
            name="Before Update",
            slug=f"before-{uuid.uuid4().hex[:8]}",
            iso_code=f"BF{uuid.uuid4().hex[:3].upper()}",
            is_union_territory=False,
        )
        updated = await repo.update(state, name="After Update")
        assert updated.name == "After Update"

    async def test_soft_delete(self, db_session: AsyncSession) -> None:
        class PolRepo(AsyncRepository[Politician]):
            model = Politician

        repo = PolRepo(db_session)
        p = await repo.create(name="To Soft Delete", slug=f"tsd-{uuid.uuid4().hex[:8]}")
        assert not p.is_deleted
        deleted = await repo.soft_delete(p)
        assert deleted.is_deleted

    async def test_count(self, db_session: AsyncSession) -> None:
        class PolRepo(AsyncRepository[Politician]):
            model = Politician

        repo = PolRepo(db_session)
        before = await repo.count()
        await repo.create(name="Count Test", slug=f"ct-{uuid.uuid4().hex[:8]}")
        after = await repo.count()
        assert after == before + 1

    async def test_list_paginated(self, db_session: AsyncSession) -> None:
        class PolRepo(AsyncRepository[Politician]):
            model = Politician

        repo = PolRepo(db_session)
        for i in range(3):
            await repo.create(name=f"Paginated {i}", slug=f"pag-{uuid.uuid4().hex[:8]}")
        items, total = await repo.list_paginated(limit=2, offset=0)
        assert len(items) == 2
        assert total >= 3


# ---------------------------------------------------------------------------
# PoliticianRepository
# ---------------------------------------------------------------------------


class TestPoliticianRepository:
    async def test_get_by_slug_found(self, db_session: AsyncSession) -> None:
        slug = f"test-pol-{uuid.uuid4().hex[:8]}"
        pol = Politician(name="Test", slug=slug)
        db_session.add(pol)
        await db_session.flush()

        repo = PoliticianRepository(db_session)
        found = await repo.get_by_slug(slug)
        assert found is not None
        assert found.slug == slug

    async def test_get_by_slug_not_found(self, db_session: AsyncSession) -> None:
        repo = PoliticianRepository(db_session)
        result = await repo.get_by_slug("no-such-politician-abc123")
        assert result is None

    async def test_get_by_slug_excludes_soft_deleted(self, db_session: AsyncSession) -> None:
        slug = f"deleted-pol-{uuid.uuid4().hex[:8]}"
        pol = Politician(name="Deleted", slug=slug, deleted_at=datetime.now(tz=timezone.utc))
        db_session.add(pol)
        await db_session.flush()

        repo = PoliticianRepository(db_session)
        result = await repo.get_by_slug(slug)
        assert result is None

    async def test_list_active_excludes_soft_deleted(self, db_session: AsyncSession) -> None:
        active = Politician(name="Active", slug=f"active-{uuid.uuid4().hex[:8]}")
        deleted = Politician(name="Deleted", slug=f"deleted-{uuid.uuid4().hex[:8]}", deleted_at=datetime.now(tz=timezone.utc))
        db_session.add_all([active, deleted])
        await db_session.flush()

        repo = PoliticianRepository(db_session)
        items, total = await repo.list_active(offset=0, limit=100)
        slugs = [p.slug for p in items]
        assert active.slug in slugs
        assert deleted.slug not in slugs

    async def test_search_by_name(self, db_session: AsyncSession) -> None:
        unique_name = f"ZuniqueSearchName{uuid.uuid4().hex[:6]}"
        pol = Politician(name=unique_name, slug=f"search-{uuid.uuid4().hex[:8]}")
        db_session.add(pol)
        await db_session.flush()

        repo = PoliticianRepository(db_session)
        results, total = await repo.search(unique_name[:10])
        slugs = [p.slug for p in results]
        assert pol.slug in slugs


# ---------------------------------------------------------------------------
# SourceRepository
# ---------------------------------------------------------------------------


class TestSourceRepository:
    async def test_get_by_hashes(self, db_session: AsyncSession) -> None:
        provider = await _make_provider(db_session)
        content = b"test content abc"
        url = f"https://test.example.com/{uuid.uuid4()}"
        snap = await _make_snapshot(db_session, provider, content=content)
        url_hash = snap.url_hash
        content_hash_val = snap.content_hash

        repo = SourceSnapshotRepository(db_session)
        found = await repo.get_by_hashes(url_hash, content_hash_val)
        assert found is not None
        assert found.id == snap.id

    async def test_get_by_hashes_not_found(self, db_session: AsyncSession) -> None:
        repo = SourceSnapshotRepository(db_session)
        result = await repo.get_by_hashes(
            "0" * 64,
            "1" * 64,
        )
        assert result is None

    async def test_get_or_create_idempotent(self, db_session: AsyncSession) -> None:
        """get_or_create returns (snap, False) on second call with same content."""
        provider = await _make_provider(db_session)
        url = f"https://test.example.com/{uuid.uuid4()}"
        content = b"unique idempotent content"

        repo = SourceSnapshotRepository(db_session)
        snap1, created1 = await repo.get_or_create(
            provider_id=str(provider.id),
            url=url,
            content=content,
            parser_version="1.0.0",
        )
        assert created1 is True

        snap2, created2 = await repo.get_or_create(
            provider_id=str(provider.id),
            url=url,
            content=content,
            parser_version="1.0.0",
        )
        assert created2 is False
        assert snap1.id == snap2.id


# ---------------------------------------------------------------------------
# ReportCardRepository
# ---------------------------------------------------------------------------


class TestReportCardRepository:
    async def test_get_criminal_cases_for_politician(self, db_session: AsyncSession) -> None:
        politician, entry = await _make_full_data_chain(db_session)

        case = CriminalCase(
            affidavit_entry_id=entry.id,
            section_of_law="302 IPC",
            status=CaseStatus.PENDING,
            severity=Severity.HEINOUS,
        )
        db_session.add(case)
        await db_session.flush()

        repo = ReportCardRepository(db_session)
        cases = await repo.get_criminal_cases(politician.id)
        assert len(cases) >= 1
        assert any(c.section_of_law == "302 IPC" for c in cases)

    async def test_get_assets_for_politician(self, db_session: AsyncSession) -> None:
        from decimal import Decimal
        politician, entry = await _make_full_data_chain(db_session)

        asset = AssetDeclaration(
            affidavit_entry_id=entry.id,
            category=AssetCategory.IMMOVABLE,
            ownership=AssetOwnership.SELF,
            description="Agricultural land",
            value_inr=Decimal("5000000.00"),
        )
        db_session.add(asset)
        await db_session.flush()

        repo = ReportCardRepository(db_session)
        assets = await repo.get_assets(politician.id)
        assert len(assets) >= 1

    async def test_get_attendance_for_politician(self, db_session: AsyncSession) -> None:
        politician = await _make_politician(db_session)
        state = await _make_state(db_session)
        constituency = Constituency(
            name=f"C {uuid.uuid4().hex[:6]}",
            slug=f"c-{uuid.uuid4().hex[:8]}",
            state_id=state.id,
            constituency_type=ConstituencyType.LOK_SABHA,
        )
        db_session.add(constituency)
        await db_session.flush()

        term = LegislativeTerm(
            politician_id=politician.id,
            constituency_id=constituency.id,
            house=House.LOK_SABHA,
            from_date=date(2024, 6, 1),
            lok_sabha_number=18,
        )
        db_session.add(term)
        await db_session.flush()

        provider = await _make_provider(db_session)
        snap = await _make_snapshot(db_session, provider)
        rec = AttendanceRecord(
            legislative_term_id=term.id,
            source_snapshot_id=snap.id,
            session_name="Budget 2024",
            session_year=2024,
            days_present=60,
            days_total=66,
            attendance_pct=90.9,
        )
        db_session.add(rec)
        await db_session.flush()

        repo = ReportCardRepository(db_session)
        records = await repo.get_attendance(politician.id)
        assert len(records) >= 1
        assert records[0].session_year == 2024

    async def test_get_legislative_activity(self, db_session: AsyncSession) -> None:
        politician = await _make_politician(db_session)
        state = await _make_state(db_session)
        constituency = Constituency(
            name=f"C {uuid.uuid4().hex[:6]}",
            slug=f"c-{uuid.uuid4().hex[:8]}",
            state_id=state.id,
            constituency_type=ConstituencyType.LOK_SABHA,
        )
        db_session.add(constituency)
        await db_session.flush()

        term = LegislativeTerm(
            politician_id=politician.id,
            constituency_id=constituency.id,
            house=House.LOK_SABHA,
            from_date=date(2024, 6, 1),
            lok_sabha_number=18,
        )
        db_session.add(term)
        await db_session.flush()

        provider = await _make_provider(db_session)
        snap = await _make_snapshot(db_session, provider)
        activity = LegislativeActivity(
            legislative_term_id=term.id,
            source_snapshot_id=snap.id,
            activity_type=ActivityType.STARRED_QUESTION,
            activity_date=date(2024, 7, 10),
            title="Q on inflation",
        )
        db_session.add(activity)
        await db_session.flush()

        repo = ReportCardRepository(db_session)
        activities = await repo.get_legislative_activity(politician.id)
        assert len(activities) >= 1

    async def test_get_latest_grade(self, db_session: AsyncSession) -> None:
        from decimal import Decimal
        politician = await _make_politician(db_session)

        gs = GradeSnapshot(
            politician_id=politician.id,
            overall_grade=GradeLetter.B,
            engine_version="1.0.0",
            computed_at=datetime.now(tz=timezone.utc),
            data_as_of=datetime.now(tz=timezone.utc),
        )
        db_session.add(gs)
        await db_session.flush()

        repo = ReportCardRepository(db_session)
        grade = await repo.get_latest_grade(politician.id)
        assert grade is not None
        assert grade.overall_grade == GradeLetter.B

    async def test_get_latest_grade_returns_none_when_no_grade(self, db_session: AsyncSession) -> None:
        politician = await _make_politician(db_session)
        repo = ReportCardRepository(db_session)
        grade = await repo.get_latest_grade(politician.id)
        assert grade is None

    async def test_criminal_cases_empty_for_unknown_politician(self, db_session: AsyncSession) -> None:
        repo = ReportCardRepository(db_session)
        cases = await repo.get_criminal_cases(uuid.uuid4())
        assert cases == []
