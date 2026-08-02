"""
Integration tests for the PRS pipeline.

Tests:
  1. PrsWriter.write_attendance() — writes sessions to real DB
  2. PrsWriter.write_activity() — writes activities to real DB
  3. Idempotency — re-running produces no duplicates
  4. Source snapshot constraint — every record references a SourceSnapshot
  5. End-to-end: HTML fixture → parser → normalizer → writer → DB assertions

No HTTP requests — all HTML comes from committed fixture files.
All tests run in a rolled-back transaction (see conftest.py db_session fixture).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from netacheck.ingestion.prs.normalizer import (
    PrsActivityNormalizer,
    PrsAttendanceNormalizer,
)
from netacheck.ingestion.prs.parser import (
    PrsActivityParser,
    PrsAttendanceParser,
)
from netacheck.ingestion.prs.writer import PrsWriter
from netacheck.models.attendance import AttendanceRecord
from netacheck.models.legislative import LegislativeActivity
from netacheck.models.legislature import LegislativeTerm
from netacheck.models.politician import Politician
from netacheck.models.source import SourceProvider, SourceSnapshot

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).parent.parent / "fixtures" / "prs_html"


def _load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# ---------------------------------------------------------------------------
# Shared test politician fixture
# ---------------------------------------------------------------------------


async def _create_test_politician(session: AsyncSession) -> Politician:
    """Create a minimal Politician in the DB for writer tests."""
    politician = Politician(
        name="Narendra Modi",
        slug="narendra-modi-varanasi",
    )
    session.add(politician)
    await session.flush()
    return politician


# ---------------------------------------------------------------------------
# PrsWriter.write_attendance() tests
# ---------------------------------------------------------------------------


class TestPrsWriterAttendance:
    """Integration tests for attendance write pipeline."""

    async def test_write_attendance_creates_records(self, db_session: AsyncSession) -> None:
        """Writing normalised attendance creates AttendanceRecord rows in DB."""
        politician = await _create_test_politician(db_session)
        html = _load("mp_attendance_page.html")

        raw = PrsAttendanceParser().parse(
            html, mp_id=12345, attendance_url="https://prsindia.org/mptrack/18/attendance/12345"
        )
        normalised = PrsAttendanceNormalizer().normalise(raw)

        writer = PrsWriter(db_session)
        count = await writer.write_attendance(
            politician=politician,
            attendance=normalised,
            raw_html=html,
            lok_sabha_number=18,
        )

        assert count > 0

        # Verify records in DB
        result = await db_session.execute(
            select(AttendanceRecord).join(
                LegislativeTerm, AttendanceRecord.legislative_term_id == LegislativeTerm.id
            ).where(LegislativeTerm.politician_id == politician.id)
        )
        records = list(result.scalars().all())
        assert len(records) == count

    async def test_write_attendance_source_snapshot_created(self, db_session: AsyncSession) -> None:
        """Writing attendance creates a SourceSnapshot record."""
        politician = await _create_test_politician(db_session)
        html = _load("mp_attendance_page.html")

        raw = PrsAttendanceParser().parse(html, mp_id=1, attendance_url="https://prsindia.org/test")
        normalised = PrsAttendanceNormalizer().normalise(raw)

        writer = PrsWriter(db_session)
        await writer.write_attendance(politician=politician, attendance=normalised, raw_html=html)

        # SourceSnapshot should exist
        result = await db_session.execute(
            select(SourceSnapshot).join(
                SourceProvider, SourceSnapshot.provider_id == SourceProvider.id
            ).where(SourceProvider.short_code == "PRS")
        )
        snapshots = list(result.scalars().all())
        assert len(snapshots) >= 1

    async def test_write_attendance_source_provider_created(self, db_session: AsyncSession) -> None:
        """PRS SourceProvider is created on first write."""
        politician = await _create_test_politician(db_session)
        html = _load("mp_attendance_page.html")

        raw = PrsAttendanceParser().parse(html, mp_id=1, attendance_url="https://prsindia.org/test")
        normalised = PrsAttendanceNormalizer().normalise(raw)

        writer = PrsWriter(db_session)
        await writer.write_attendance(politician=politician, attendance=normalised, raw_html=html)

        result = await db_session.execute(
            select(SourceProvider).where(SourceProvider.short_code == "PRS")
        )
        provider = result.scalar_one_or_none()
        assert provider is not None
        assert provider.name == "PRS India"

    async def test_write_attendance_legislative_term_created(self, db_session: AsyncSession) -> None:
        """A LegislativeTerm is created for the politician."""
        politician = await _create_test_politician(db_session)
        html = _load("mp_attendance_page.html")

        raw = PrsAttendanceParser().parse(html, mp_id=1, attendance_url="https://prsindia.org/test")
        normalised = PrsAttendanceNormalizer().normalise(raw)

        writer = PrsWriter(db_session)
        await writer.write_attendance(politician=politician, attendance=normalised, raw_html=html)

        result = await db_session.execute(
            select(LegislativeTerm).where(LegislativeTerm.politician_id == politician.id)
        )
        term = result.scalar_one_or_none()
        assert term is not None
        assert term.lok_sabha_number == 18

    async def test_write_attendance_idempotent_same_html(self, db_session: AsyncSession) -> None:
        """
        Re-running write_attendance with the same HTML returns 0 (duplicate snapshot).

        The content hash gate prevents duplicate processing.
        """
        politician = await _create_test_politician(db_session)
        html = _load("mp_attendance_page.html")

        raw = PrsAttendanceParser().parse(html, mp_id=1, attendance_url="https://prsindia.org/test")
        normalised = PrsAttendanceNormalizer().normalise(raw)

        writer = PrsWriter(db_session)
        # First write
        count1 = await writer.write_attendance(politician=politician, attendance=normalised, raw_html=html)
        assert count1 > 0

        # Second write with identical HTML — DuplicateSnapshotError caught internally → 0
        count2 = await writer.write_attendance(politician=politician, attendance=normalised, raw_html=html)
        assert count2 == 0

    async def test_write_attendance_records_have_source_snapshot(self, db_session: AsyncSession) -> None:
        """Every AttendanceRecord must reference a non-null source_snapshot_id."""
        politician = await _create_test_politician(db_session)
        html = _load("mp_attendance_page.html")

        raw = PrsAttendanceParser().parse(html, mp_id=1, attendance_url="https://prsindia.org/test")
        normalised = PrsAttendanceNormalizer().normalise(raw)

        writer = PrsWriter(db_session)
        await writer.write_attendance(politician=politician, attendance=normalised, raw_html=html)

        result = await db_session.execute(select(AttendanceRecord))
        records = list(result.scalars().all())
        for record in records:
            assert record.source_snapshot_id is not None, (
                f"AttendanceRecord {record.id} has no source_snapshot_id — hard constraint violated"
            )

    async def test_write_empty_attendance_creates_no_records(self, db_session: AsyncSession) -> None:
        """Empty HTML page → no records written, no errors."""
        politician = await _create_test_politician(db_session)
        html = _load("mp_attendance_empty.html")

        raw = PrsAttendanceParser().parse(html, mp_id=9999, attendance_url="https://prsindia.org/test")
        normalised = PrsAttendanceNormalizer().normalise(raw)

        writer = PrsWriter(db_session)
        count = await writer.write_attendance(politician=politician, attendance=normalised, raw_html=html)

        assert count == 0


# ---------------------------------------------------------------------------
# PrsWriter.write_activity() tests
# ---------------------------------------------------------------------------


class TestPrsWriterActivity:
    """Integration tests for legislative activity write pipeline."""

    async def test_write_activity_creates_records(self, db_session: AsyncSession) -> None:
        """Writing normalised activities creates LegislativeActivity rows in DB."""
        politician = await _create_test_politician(db_session)
        html = _load("mp_activity_page.html")

        raw = PrsActivityParser().parse(
            html, mp_id=12345, activity_url="https://prsindia.org/mptrack/18/questions/12345"
        )
        normalised = PrsActivityNormalizer().normalise(raw)

        writer = PrsWriter(db_session)
        count = await writer.write_activity(
            politician=politician,
            activity=normalised,
            raw_html=html,
            lok_sabha_number=18,
        )

        assert count > 0

        # Verify records in DB
        result = await db_session.execute(
            select(LegislativeActivity).join(
                LegislativeTerm,
                LegislativeActivity.legislative_term_id == LegislativeTerm.id,
            ).where(LegislativeTerm.politician_id == politician.id)
        )
        records = list(result.scalars().all())
        assert len(records) == count

    async def test_write_activity_records_have_source_snapshot(self, db_session: AsyncSession) -> None:
        """Every LegislativeActivity must reference a non-null source_snapshot_id."""
        politician = await _create_test_politician(db_session)
        html = _load("mp_activity_page.html")

        raw = PrsActivityParser().parse(html, mp_id=1, activity_url="https://prsindia.org/test")
        normalised = PrsActivityNormalizer().normalise(raw)

        writer = PrsWriter(db_session)
        await writer.write_activity(politician=politician, activity=normalised, raw_html=html)

        result = await db_session.execute(select(LegislativeActivity))
        records = list(result.scalars().all())
        for record in records:
            assert record.source_snapshot_id is not None, (
                f"LegislativeActivity {record.id} has no source_snapshot_id — hard constraint violated"
            )

    async def test_write_activity_idempotent_same_html(self, db_session: AsyncSession) -> None:
        """Re-running with same HTML returns 0 (duplicate snapshot skipped)."""
        politician = await _create_test_politician(db_session)
        html = _load("mp_activity_page.html")

        raw = PrsActivityParser().parse(html, mp_id=1, activity_url="https://prsindia.org/test")
        normalised = PrsActivityNormalizer().normalise(raw)

        writer = PrsWriter(db_session)
        count1 = await writer.write_activity(politician=politician, activity=normalised, raw_html=html)
        assert count1 > 0

        count2 = await writer.write_activity(politician=politician, activity=normalised, raw_html=html)
        assert count2 == 0

    async def test_write_activity_legislative_term_reused(self, db_session: AsyncSession) -> None:
        """Attendance and activity writes share the same LegislativeTerm."""
        politician = await _create_test_politician(db_session)
        att_html = _load("mp_attendance_page.html")
        act_html = _load("mp_activity_page.html")

        att_raw = PrsAttendanceParser().parse(att_html, mp_id=1, attendance_url="https://prsindia.org/att")
        att_norm = PrsAttendanceNormalizer().normalise(att_raw)

        act_raw = PrsActivityParser().parse(act_html, mp_id=1, activity_url="https://prsindia.org/act")
        act_norm = PrsActivityNormalizer().normalise(act_raw)

        writer = PrsWriter(db_session)
        await writer.write_attendance(politician=politician, attendance=att_norm, raw_html=att_html)
        await writer.write_activity(politician=politician, activity=act_norm, raw_html=act_html)

        # Should have exactly 1 LegislativeTerm (reused across writes)
        result = await db_session.execute(
            select(LegislativeTerm).where(
                LegislativeTerm.politician_id == politician.id,
                LegislativeTerm.lok_sabha_number == 18,
            )
        )
        terms = list(result.scalars().all())
        assert len(terms) == 1, "Multiple LegislativeTerm rows created — should be reused"

    async def test_provider_created_only_once(self, db_session: AsyncSession) -> None:
        """PRS SourceProvider should be created only once even with multiple writes."""
        politician = await _create_test_politician(db_session)
        att_html = _load("mp_attendance_page.html")
        act_html = _load("mp_activity_page.html")

        att_raw = PrsAttendanceParser().parse(att_html, mp_id=1, attendance_url="https://prsindia.org/att")
        att_norm = PrsAttendanceNormalizer().normalise(att_raw)

        act_raw = PrsActivityParser().parse(act_html, mp_id=1, activity_url="https://prsindia.org/act")
        act_norm = PrsActivityNormalizer().normalise(act_raw)

        writer = PrsWriter(db_session)
        await writer.write_attendance(politician=politician, attendance=att_norm, raw_html=att_html)
        await writer.write_activity(politician=politician, activity=act_norm, raw_html=act_html)

        result = await db_session.execute(
            select(SourceProvider).where(SourceProvider.short_code == "PRS")
        )
        providers = list(result.scalars().all())
        assert len(providers) == 1


# ---------------------------------------------------------------------------
# End-to-end pipeline test
# ---------------------------------------------------------------------------


class TestPrsPipelineE2E:
    """Full pipeline: HTML fixture → parser → normalizer → writer → DB assertions."""

    async def test_full_attendance_pipeline(self, db_session: AsyncSession) -> None:
        """
        End-to-end: attendance HTML fixture → complete data chain in DB.

        Validates:
        - SourceProvider created
        - SourceSnapshot created
        - LegislativeTerm created
        - AttendanceRecords created
        - Every record references a SourceSnapshot
        """
        politician = await _create_test_politician(db_session)
        html = _load("mp_attendance_page.html")
        url = "https://prsindia.org/mptrack/18/attendance/12345"

        # Full pipeline
        raw = PrsAttendanceParser().parse(html, mp_id=12345, attendance_url=url)
        normalised = PrsAttendanceNormalizer().normalise(raw)
        writer = PrsWriter(db_session)
        count = await writer.write_attendance(
            politician=politician,
            attendance=normalised,
            raw_html=html,
        )

        # Assertions on the complete data chain
        assert count > 0, "Expected at least one attendance record to be written"

        # SourceProvider
        r = await db_session.execute(select(SourceProvider).where(SourceProvider.name == "PRS India"))
        assert r.scalar_one_or_none() is not None

        # SourceSnapshot
        r = await db_session.execute(select(SourceSnapshot).where(SourceSnapshot.url == url))
        snapshot = r.scalar_one_or_none()
        assert snapshot is not None

        # LegislativeTerm
        r = await db_session.execute(
            select(LegislativeTerm).where(LegislativeTerm.politician_id == politician.id)
        )
        term = r.scalar_one_or_none()
        assert term is not None
        assert term.lok_sabha_number == 18

        # AttendanceRecords — all linked to term and snapshot
        r = await db_session.execute(
            select(AttendanceRecord).where(
                AttendanceRecord.legislative_term_id == term.id
            )
        )
        records = list(r.scalars().all())
        assert len(records) == count
        for record in records:
            assert record.source_snapshot_id == snapshot.id
            assert record.days_total > 0
            assert record.days_present >= 0

    async def test_full_activity_pipeline(self, db_session: AsyncSession) -> None:
        """
        End-to-end: activity HTML fixture → complete data chain in DB.

        Validates:
        - Different activity types present (STARRED, UNSTARRED, ZERO_HOUR, etc.)
        - All linked to LegislativeTerm and SourceSnapshot
        """
        politician = await _create_test_politician(db_session)
        html = _load("mp_activity_page.html")
        url = "https://prsindia.org/mptrack/18/questions/12345"

        raw = PrsActivityParser().parse(html, mp_id=12345, activity_url=url)
        normalised = PrsActivityNormalizer().normalise(raw)
        writer = PrsWriter(db_session)
        count = await writer.write_activity(
            politician=politician,
            activity=normalised,
            raw_html=html,
        )

        assert count > 0

        r = await db_session.execute(
            select(LegislativeTerm).where(LegislativeTerm.politician_id == politician.id)
        )
        term = r.scalar_one_or_none()
        assert term is not None

        r = await db_session.execute(
            select(LegislativeActivity).where(
                LegislativeActivity.legislative_term_id == term.id
            )
        )
        activities = list(r.scalars().all())
        assert len(activities) == count

        # Check source constraint on all records
        for act in activities:
            assert act.source_snapshot_id is not None

        # Verify at least some expected activity types are present
        activity_types = {act.activity_type for act in activities}
        # Should have at least questions or debates from the fixture
        from netacheck.models.legislative import ActivityType
        assert bool(activity_types & {
            ActivityType.STARRED_QUESTION,
            ActivityType.UNSTARRED_QUESTION,
            ActivityType.ZERO_HOUR,
            ActivityType.CALLING_ATTENTION,
            ActivityType.PRIVATE_MEMBER_BILL,
        })

    async def test_double_run_is_idempotent(self, db_session: AsyncSession) -> None:
        """
        Running the full pipeline twice with the same HTML produces no duplicate records.
        The content hash gate prevents re-processing.
        """
        politician = await _create_test_politician(db_session)
        html = _load("mp_attendance_page.html")
        url = "https://prsindia.org/mptrack/18/attendance/99"

        raw = PrsAttendanceParser().parse(html, mp_id=99, attendance_url=url)
        normalised = PrsAttendanceNormalizer().normalise(raw)
        writer = PrsWriter(db_session)

        count1 = await writer.write_attendance(politician=politician, attendance=normalised, raw_html=html)
        count2 = await writer.write_attendance(politician=politician, attendance=normalised, raw_html=html)

        assert count1 > 0
        assert count2 == 0

        # Verify only count1 records in DB
        r = await db_session.execute(select(AttendanceRecord))
        all_records = list(r.scalars().all())
        assert len(all_records) == count1
