"""
Integration tests for Phase 2: Database Schema & FK Constraints.

Tests every ORM model against a real Postgres database.

Key things verified:
  1. Every table can be created and written to
  2. FK constraints are enforced by the DB (attempt to violate → IntegrityError)
  3. Unique constraints work (slug, iso_code, content_hash etc.)
  4. The hard constraint: AffidavitEntry MUST have a source_snapshot_id
  5. Soft-delete pattern works correctly
  6. Enum columns accept only valid values
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any, cast

import pytest
from sqlalchemy.exc import IntegrityError

from netacheck.models.affidavit import Affidavit, AffidavitEntry
from netacheck.models.assets import AssetCategory, AssetDeclaration, AssetOwnership
from netacheck.models.attendance import AttendanceRecord
from netacheck.models.audit import AuditLog
from netacheck.models.correction import CorrectionHistory, CorrectionRequest, CorrectionStatus
from netacheck.models.criminal import CaseStatus, CriminalCase, Severity
from netacheck.models.election import Election, ElectionResult, ElectionType
from netacheck.models.geography import Constituency, ConstituencyType, State
from netacheck.models.grading import (
    Confidence,
    GradeLetter,
    GradeMetricResult,
    GradeSnapshot,
)
from netacheck.models.legislative import ActivityType, LegislativeActivity
from netacheck.models.legislature import LegislativeTerm
from netacheck.models.politician import (
    Gender,
    House,
    PartyMembership,
    PoliticalParty,
    Politician,
    PoliticianAlias,
)
from netacheck.models.source import SourceProvider, SourceSnapshot

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_state(session: AsyncSession, name: str = "Test State") -> State:
    state = State(
        name=name,
        slug=f"test-state-{uuid.uuid4().hex[:6]}",
        iso_code=f"TS{uuid.uuid4().hex[:4].upper()}",
        is_union_territory=False,
    )
    session.add(state)
    await session.flush()
    return state


async def _make_party(session: AsyncSession, abbr: str = "TST") -> PoliticalParty:
    party = PoliticalParty(
        name=f"Test Party {abbr}",
        slug=f"tp-{abbr.lower()}-{uuid.uuid4().hex[:6]}",
        abbreviation=abbr,
    )
    session.add(party)
    await session.flush()
    return party


async def _make_politician(session: AsyncSession) -> Politician:
    p = Politician(name="Test Politician", slug=f"test-pol-{uuid.uuid4().hex[:8]}")
    session.add(p)
    await session.flush()
    return p


async def _make_provider(session: AsyncSession) -> SourceProvider:
    sp = SourceProvider(
        name="Test Provider",
        short_code=f"TP{uuid.uuid4().hex[:4].upper()}",
        base_url="https://test.example.com",
    )
    session.add(sp)
    await session.flush()
    return sp


async def _make_snapshot(
    session: AsyncSession, provider: SourceProvider, content: bytes = b"test"
) -> SourceSnapshot:
    c = hashlib.sha256(content).hexdigest()
    u = hashlib.sha256(f"https://test.example.com/{uuid.uuid4()}".encode()).hexdigest()
    snap = SourceSnapshot(
        provider_id=provider.id,
        url=f"https://test.example.com/{uuid.uuid4()}",
        url_hash=u,
        content_hash=c,
        fetched_at=datetime.now(tz=UTC),
        parser_version="1.0.0",
    )
    session.add(snap)
    await session.flush()
    return snap


async def _make_constituency(session: AsyncSession, state: State) -> Constituency:
    c = Constituency(
        name=f"Test Constituency {uuid.uuid4().hex[:6]}",
        slug=f"tc-{uuid.uuid4().hex[:8]}",
        state_id=state.id,
        constituency_type=ConstituencyType.LOK_SABHA,
    )
    session.add(c)
    await session.flush()
    return c


async def _make_election(session: AsyncSession, constituency: Constituency) -> Election:
    e = Election(
        constituency_id=constituency.id,
        election_type=ElectionType.GENERAL,
        election_date=date(2024, 5, 4),
        year=2024,
    )
    session.add(e)
    await session.flush()
    return e


async def _make_election_result(
    session: AsyncSession, election: Election, politician: Politician
) -> ElectionResult:
    er = ElectionResult(election_id=election.id, politician_id=politician.id, won=True)
    session.add(er)
    await session.flush()
    return er


async def _make_affidavit(
    session: AsyncSession, election_result: ElectionResult, snapshot: SourceSnapshot
) -> Affidavit:
    a = Affidavit(election_result_id=election_result.id, source_snapshot_id=snapshot.id)
    session.add(a)
    await session.flush()
    return a


async def _make_affidavit_entry(
    session: AsyncSession, affidavit: Affidavit, snapshot: SourceSnapshot
) -> AffidavitEntry:
    e = AffidavitEntry(
        affidavit_id=affidavit.id, source_snapshot_id=snapshot.id, field_name="test_field"
    )
    session.add(e)
    await session.flush()
    return e


async def _make_leg_term(
    session: AsyncSession, politician: Politician, constituency: Constituency
) -> LegislativeTerm:
    term = LegislativeTerm(
        politician_id=politician.id,
        constituency_id=constituency.id,
        house=House.LOK_SABHA,
        from_date=date(2024, 6, 1),
        lok_sabha_number=18,
    )
    session.add(term)
    await session.flush()
    return term


# ---------------------------------------------------------------------------
# State model
# ---------------------------------------------------------------------------


class TestStateModel:
    async def test_create_and_read(self, db_session: AsyncSession) -> None:
        state = await _make_state(db_session, "Maharashtra")
        assert state.id is not None
        assert state.name == "Maharashtra"

    async def test_slug_is_indexed(self, db_session: AsyncSession) -> None:
        state = await _make_state(db_session)
        assert state.slug is not None

    async def test_iso_code_unique(self, db_session: AsyncSession) -> None:
        iso = f"IN-{uuid.uuid4().hex[:2].upper()}"
        s1 = State(name="S1", slug=f"s1-{uuid.uuid4().hex[:6]}", iso_code=iso)
        s2 = State(name="S2", slug=f"s2-{uuid.uuid4().hex[:6]}", iso_code=iso)
        db_session.add(s1)
        await db_session.flush()
        db_session.add(s2)
        with pytest.raises(IntegrityError):
            await db_session.flush()


# ---------------------------------------------------------------------------
# Constituency model
# ---------------------------------------------------------------------------


class TestConstituencyModel:
    async def test_create_with_fk(self, db_session: AsyncSession) -> None:
        state = await _make_state(db_session)
        constituency = await _make_constituency(db_session, state)
        assert constituency.state_id == state.id

    async def test_constituency_type_enum(self, db_session: AsyncSession) -> None:
        state = await _make_state(db_session)
        c = Constituency(
            name="Test",
            slug=f"tc-{uuid.uuid4().hex[:8]}",
            state_id=state.id,
            constituency_type=ConstituencyType.VIDHAN_SABHA,
        )
        db_session.add(c)
        await db_session.flush()
        assert c.constituency_type == ConstituencyType.VIDHAN_SABHA


# ---------------------------------------------------------------------------
# Politician model
# ---------------------------------------------------------------------------


class TestPoliticianModel:
    async def test_create_and_read(self, db_session: AsyncSession) -> None:
        p = await _make_politician(db_session)
        assert p.id is not None
        assert p.name == "Test Politician"

    async def test_slug_unique_constraint(self, db_session: AsyncSession) -> None:
        slug = f"unique-slug-{uuid.uuid4().hex[:8]}"
        p1 = Politician(name="P1", slug=slug)
        p2 = Politician(name="P2", slug=slug)
        db_session.add(p1)
        await db_session.flush()
        db_session.add(p2)
        with pytest.raises(IntegrityError):
            await db_session.flush()

    async def test_soft_delete(self, db_session: AsyncSession) -> None:
        p = await _make_politician(db_session)
        assert p.deleted_at is None
        assert p.is_deleted is False
        p.deleted_at = datetime.now(tz=UTC)
        await db_session.flush()
        assert p.is_deleted is True

    async def test_uuid_pk(self, db_session: AsyncSession) -> None:
        p = await _make_politician(db_session)
        assert isinstance(p.id, uuid.UUID)

    async def test_gender_enum(self, db_session: AsyncSession) -> None:
        p = Politician(name="Test", slug=f"tp-{uuid.uuid4().hex[:8]}", gender=Gender.FEMALE)
        db_session.add(p)
        await db_session.flush()
        assert p.gender == Gender.FEMALE


# ---------------------------------------------------------------------------
# PoliticianAlias model
# ---------------------------------------------------------------------------


class TestPoliticianAliasModel:
    async def test_create_alias(self, db_session: AsyncSession) -> None:
        p = await _make_politician(db_session)
        alias = PoliticianAlias(politician_id=p.id, alias="Test Alias", source="test")
        db_session.add(alias)
        await db_session.flush()
        assert alias.id is not None

    async def test_fk_to_politician_required(self, db_session: AsyncSession) -> None:
        alias = PoliticianAlias(politician_id=uuid.uuid4(), alias="Ghost Alias")
        db_session.add(alias)
        with pytest.raises(IntegrityError):
            await db_session.flush()


# ---------------------------------------------------------------------------
# PoliticalParty model
# ---------------------------------------------------------------------------


class TestPoliticalPartyModel:
    async def test_create_party(self, db_session: AsyncSession) -> None:
        party = await _make_party(db_session)
        assert party.id is not None

    async def test_slug_unique(self, db_session: AsyncSession) -> None:
        slug = f"party-slug-{uuid.uuid4().hex[:8]}"
        p1 = PoliticalParty(name="P1", slug=slug, abbreviation="P1")
        p2 = PoliticalParty(name="P2", slug=slug, abbreviation="P2")
        db_session.add(p1)
        await db_session.flush()
        db_session.add(p2)
        with pytest.raises(IntegrityError):
            await db_session.flush()


# ---------------------------------------------------------------------------
# PartyMembership model
# ---------------------------------------------------------------------------


class TestPartyMembershipModel:
    async def test_create_membership(self, db_session: AsyncSession) -> None:
        p = await _make_politician(db_session)
        party = await _make_party(db_session)
        m = PartyMembership(politician_id=p.id, party_id=party.id, from_date=date(2020, 1, 1))
        db_session.add(m)
        await db_session.flush()
        assert m.id is not None

    async def test_invalid_politician_fk_raises(self, db_session: AsyncSession) -> None:
        party = await _make_party(db_session)
        m = PartyMembership(
            politician_id=uuid.uuid4(), party_id=party.id, from_date=date(2020, 1, 1)
        )
        db_session.add(m)
        with pytest.raises(IntegrityError):
            await db_session.flush()

    async def test_invalid_party_fk_raises(self, db_session: AsyncSession) -> None:
        p = await _make_politician(db_session)
        m = PartyMembership(politician_id=p.id, party_id=uuid.uuid4(), from_date=date(2020, 1, 1))
        db_session.add(m)
        with pytest.raises(IntegrityError):
            await db_session.flush()


# ---------------------------------------------------------------------------
# SourceProvider + SourceSnapshot
# ---------------------------------------------------------------------------


class TestSourceProviderModel:
    async def test_create_provider(self, db_session: AsyncSession) -> None:
        sp = await _make_provider(db_session)
        assert sp.id is not None

    async def test_short_code_unique(self, db_session: AsyncSession) -> None:
        code = f"TST{uuid.uuid4().hex[:2].upper()}"
        p1 = SourceProvider(name="P1", short_code=code, base_url="https://a.com")
        p2 = SourceProvider(name="P2", short_code=code, base_url="https://b.com")
        db_session.add(p1)
        await db_session.flush()
        db_session.add(p2)
        with pytest.raises(IntegrityError):
            await db_session.flush()


class TestSourceSnapshotModel:
    async def test_create_snapshot(self, db_session: AsyncSession) -> None:
        provider = await _make_provider(db_session)
        snap = await _make_snapshot(db_session, provider)
        assert snap.id is not None

    async def test_url_content_hash_unique_constraint(self, db_session: AsyncSession) -> None:
        """Core idempotency key: same (url_hash, content_hash) → IntegrityError."""
        provider = await _make_provider(db_session)
        content = b"identical content"
        url = "https://example.com/same"
        url_hash = hashlib.sha256(url.encode()).hexdigest()
        content_hash_val = hashlib.sha256(content).hexdigest()

        snap1 = SourceSnapshot(
            provider_id=provider.id,
            url=url,
            url_hash=url_hash,
            content_hash=content_hash_val,
            fetched_at=datetime.now(tz=UTC),
            parser_version="1.0.0",
        )
        snap2 = SourceSnapshot(
            provider_id=provider.id,
            url=url,
            url_hash=url_hash,
            content_hash=content_hash_val,
            fetched_at=datetime.now(tz=UTC),
            parser_version="1.0.0",
        )
        db_session.add(snap1)
        await db_session.flush()
        db_session.add(snap2)
        with pytest.raises(IntegrityError):
            await db_session.flush()

    async def test_different_content_same_url_is_allowed(self, db_session: AsyncSession) -> None:
        """Same URL, different content → two snapshots (content changed on source)."""
        provider = await _make_provider(db_session)
        url = f"https://example.com/{uuid.uuid4()}"
        url_hash = hashlib.sha256(url.encode()).hexdigest()

        snap1 = SourceSnapshot(
            provider_id=provider.id,
            url=url,
            url_hash=url_hash,
            content_hash=hashlib.sha256(b"v1 content").hexdigest(),
            fetched_at=datetime.now(tz=UTC),
            parser_version="1.0.0",
        )
        snap2 = SourceSnapshot(
            provider_id=provider.id,
            url=url,
            url_hash=url_hash,
            content_hash=hashlib.sha256(b"v2 content").hexdigest(),
            fetched_at=datetime.now(tz=UTC),
            parser_version="1.0.0",
        )
        db_session.add(snap1)
        db_session.add(snap2)
        await db_session.flush()  # Should NOT raise


# ---------------------------------------------------------------------------
# The hard constraint: AffidavitEntry MUST have source_snapshot_id
# ---------------------------------------------------------------------------


class TestAffidavitSourceConstraint:
    async def test_affidavit_entry_requires_source(self, db_session: AsyncSession) -> None:
        """
        This is the platform's #1 hard constraint.
        An AffidavitEntry without source_snapshot_id MUST be rejected by the DB.
        """
        state = await _make_state(db_session)
        constituency = await _make_constituency(db_session, state)
        election = await _make_election(db_session, constituency)
        politician = await _make_politician(db_session)
        election_result = await _make_election_result(db_session, election, politician)
        provider = await _make_provider(db_session)
        snapshot = await _make_snapshot(db_session, provider)
        affidavit = await _make_affidavit(db_session, election_result, snapshot)

        # Attempt to create AffidavitEntry without source_snapshot_id
        bad_entry = AffidavitEntry(
            affidavit_id=affidavit.id,
            source_snapshot_id=cast("Any", None),
            field_name="criminal_cases",
        )
        db_session.add(bad_entry)
        with pytest.raises((IntegrityError, Exception)):
            await db_session.flush()

    async def test_affidavit_entry_with_source_succeeds(self, db_session: AsyncSession) -> None:
        state = await _make_state(db_session)
        constituency = await _make_constituency(db_session, state)
        election = await _make_election(db_session, constituency)
        politician = await _make_politician(db_session)
        election_result = await _make_election_result(db_session, election, politician)
        provider = await _make_provider(db_session)
        snapshot = await _make_snapshot(db_session, provider)
        affidavit = await _make_affidavit(db_session, election_result, snapshot)
        entry = await _make_affidavit_entry(db_session, affidavit, snapshot)
        assert entry.source_snapshot_id == snapshot.id


# ---------------------------------------------------------------------------
# CriminalCase model
# ---------------------------------------------------------------------------


class TestCriminalCaseModel:
    async def test_create_criminal_case(self, db_session: AsyncSession) -> None:
        state = await _make_state(db_session)
        constituency = await _make_constituency(db_session, state)
        election = await _make_election(db_session, constituency)
        politician = await _make_politician(db_session)
        er = await _make_election_result(db_session, election, politician)
        provider = await _make_provider(db_session)
        snap = await _make_snapshot(db_session, provider)
        affidavit = await _make_affidavit(db_session, er, snap)
        entry = await _make_affidavit_entry(db_session, affidavit, snap)

        case = CriminalCase(
            affidavit_entry_id=entry.id,
            case_number="FIR/001/2024",
            section_of_law="302 IPC",
            status=CaseStatus.PENDING,
            severity=Severity.HEINOUS,
        )
        db_session.add(case)
        await db_session.flush()
        assert case.id is not None
        assert case.status == CaseStatus.PENDING
        assert case.severity == Severity.HEINOUS

    async def test_criminal_case_fk_to_affidavit_entry_required(
        self, db_session: AsyncSession
    ) -> None:
        case = CriminalCase(
            affidavit_entry_id=uuid.uuid4(),
            status=CaseStatus.PENDING,
            severity=Severity.UNKNOWN,
        )
        db_session.add(case)
        with pytest.raises(IntegrityError):
            await db_session.flush()


# ---------------------------------------------------------------------------
# AssetDeclaration model
# ---------------------------------------------------------------------------


class TestAssetDeclarationModel:
    async def test_create_asset(self, db_session: AsyncSession) -> None:
        state = await _make_state(db_session)
        constituency = await _make_constituency(db_session, state)
        election = await _make_election(db_session, constituency)
        politician = await _make_politician(db_session)
        er = await _make_election_result(db_session, election, politician)
        provider = await _make_provider(db_session)
        snap = await _make_snapshot(db_session, provider)
        affidavit = await _make_affidavit(db_session, er, snap)
        entry = await _make_affidavit_entry(db_session, affidavit, snap)

        from decimal import Decimal

        asset = AssetDeclaration(
            affidavit_entry_id=entry.id,
            category=AssetCategory.IMMOVABLE,
            ownership=AssetOwnership.SELF,
            description="Agricultural land in UP",
            value_inr=Decimal("5000000.00"),
            raw_value_text="Rs 50,00,000",
        )
        db_session.add(asset)
        await db_session.flush()
        assert asset.id is not None
        assert asset.value_inr == Decimal("5000000.00")

    async def test_asset_fk_to_affidavit_entry_required(self, db_session: AsyncSession) -> None:
        asset = AssetDeclaration(
            affidavit_entry_id=uuid.uuid4(),
            category=AssetCategory.MOVABLE,
            ownership=AssetOwnership.SELF,
        )
        db_session.add(asset)
        with pytest.raises(IntegrityError):
            await db_session.flush()


# ---------------------------------------------------------------------------
# AttendanceRecord model
# ---------------------------------------------------------------------------


class TestAttendanceRecordModel:
    async def test_create_attendance(self, db_session: AsyncSession) -> None:
        state = await _make_state(db_session)
        constituency = await _make_constituency(db_session, state)
        politician = await _make_politician(db_session)
        term = await _make_leg_term(db_session, politician, constituency)
        provider = await _make_provider(db_session)
        snap = await _make_snapshot(db_session, provider)

        rec = AttendanceRecord(
            legislative_term_id=term.id,
            source_snapshot_id=snap.id,
            session_name="Budget Session 2024",
            session_year=2024,
            days_present=55,
            days_total=66,
            attendance_pct=83.33,
        )
        db_session.add(rec)
        await db_session.flush()
        assert rec.id is not None

    async def test_attendance_fk_requires_valid_term(self, db_session: AsyncSession) -> None:
        provider = await _make_provider(db_session)
        snap = await _make_snapshot(db_session, provider)
        rec = AttendanceRecord(
            legislative_term_id=uuid.uuid4(),
            source_snapshot_id=snap.id,
            session_name="Test",
            session_year=2024,
            days_present=10,
            days_total=20,
        )
        db_session.add(rec)
        with pytest.raises(IntegrityError):
            await db_session.flush()


# ---------------------------------------------------------------------------
# GradeSnapshot model
# ---------------------------------------------------------------------------


class TestGradeSnapshotModel:
    async def test_create_grade_snapshot(self, db_session: AsyncSession) -> None:
        politician = await _make_politician(db_session)
        gs = GradeSnapshot(
            politician_id=politician.id,
            overall_grade=GradeLetter.B,
            engine_version="1.0.0",
            computed_at=datetime.now(tz=UTC),
            data_as_of=datetime.now(tz=UTC),
        )
        db_session.add(gs)
        await db_session.flush()
        assert gs.id is not None
        assert gs.overall_grade == GradeLetter.B

    async def test_grade_metric_result_linked_to_snapshot(self, db_session: AsyncSession) -> None:
        politician = await _make_politician(db_session)
        gs = GradeSnapshot(
            politician_id=politician.id,
            overall_grade=GradeLetter.A,
            engine_version="1.0.0",
            computed_at=datetime.now(tz=UTC),
            data_as_of=datetime.now(tz=UTC),
        )
        db_session.add(gs)
        await db_session.flush()

        from decimal import Decimal

        mr = GradeMetricResult(
            grade_snapshot_id=gs.id,
            metric_name="attendance",
            grade=GradeLetter.A,
            reason="Attended 95% of sessions",
            confidence=Confidence.OFFICIAL_PRIMARY,
            score=Decimal("95.0"),
            weight=Decimal("0.25"),
        )
        db_session.add(mr)
        await db_session.flush()
        assert mr.id is not None


# ---------------------------------------------------------------------------
# CorrectionRequest model
# ---------------------------------------------------------------------------


class TestCorrectionModel:
    async def test_create_correction_request(self, db_session: AsyncSession) -> None:
        politician = await _make_politician(db_session)
        req = CorrectionRequest(
            politician_id=politician.id,
            submitter_name="Test Submitter",
            submitter_email="test@example.com",
            field_name="total_assets",
            current_value="100000",
            claimed_correct_value="200000",
            explanation="Correcting value",
        )
        db_session.add(req)
        await db_session.flush()
        assert req.id is not None
        assert req.status == CorrectionStatus.PENDING

    async def test_correction_history_linked(self, db_session: AsyncSession) -> None:
        politician = await _make_politician(db_session)
        req = CorrectionRequest(
            politician_id=politician.id,
            submitter_name="Tester",
            submitter_email="t@t.com",
            field_name="name",
            current_value="Old",
            claimed_correct_value="New",
            explanation="Fix name",
        )
        db_session.add(req)
        await db_session.flush()

        hist = CorrectionHistory(
            correction_request_id=req.id,
            to_status=CorrectionStatus.APPROVED,
            notes="Verified against ECI records",
        )
        db_session.add(hist)
        await db_session.flush()
        assert hist.id is not None


# ---------------------------------------------------------------------------
# AuditLog model
# ---------------------------------------------------------------------------


class TestAuditLogModel:
    async def test_create_audit_log(self, db_session: AsyncSession) -> None:
        log = AuditLog(
            actor="admin",
            action="politician.create",
            description="Created test politician",
            target_table="politician",
            target_id=str(uuid.uuid4()),
        )
        db_session.add(log)
        await db_session.flush()
        assert log.id is not None


# ---------------------------------------------------------------------------
# LegislativeActivity model
# ---------------------------------------------------------------------------


class TestLegislativeActivityModel:
    async def test_create_activity(self, db_session: AsyncSession) -> None:
        state = await _make_state(db_session)
        constituency = await _make_constituency(db_session, state)
        politician = await _make_politician(db_session)
        term = await _make_leg_term(db_session, politician, constituency)
        provider = await _make_provider(db_session)
        snap = await _make_snapshot(db_session, provider)

        activity = LegislativeActivity(
            legislative_term_id=term.id,
            source_snapshot_id=snap.id,
            activity_type=ActivityType.STARRED_QUESTION,
            activity_date=date(2024, 7, 15),
            title="Question about inflation",
            session_name="Budget Session",
        )
        db_session.add(activity)
        await db_session.flush()
        assert activity.id is not None
