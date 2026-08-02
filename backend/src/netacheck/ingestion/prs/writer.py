"""
PRS writer — idempotent persistence of PRS attendance and legislative
activity data to the database.

Design:
  - All writes use get-or-create patterns (idempotent)
  - Every AttendanceRecord MUST reference a SourceSnapshot (hard constraint)
  - Every LegislativeActivity MUST reference a SourceSnapshot
  - LegislativeTerm is created if it does not exist for the politician
  - Attendance idempotency key: (legislative_term_id, session_name, session_year)
  - Activity idempotency key: (legislative_term_id, activity_type, title, activity_date)
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select

from netacheck.ingestion.base import DuplicateSnapshotError, content_hash
from netacheck.models.attendance import AttendanceRecord
from netacheck.models.legislative import LegislativeActivity
from netacheck.models.legislature import LegislativeTerm
from netacheck.models.politician import House
from netacheck.models.source import SourceProvider, SourceSnapshot

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from netacheck.ingestion.prs.normalizer import (
        NormalisedAttendanceSession,
        NormalisedLegislativeActivity,
        NormalisedMpActivity,
        NormalisedMpAttendance,
    )
    from netacheck.models.politician import Politician

logger = structlog.get_logger(__name__)

PRS_PROVIDER_NAME = "PRS India"
PRS_PROVIDER_URL = "https://prsindia.org"


class PrsWriter:
    """
    Writes normalised PRS data to the database, idempotently.

    Call write_attendance() and write_activity() inside an open
    AsyncSession transaction. The caller is responsible for commit/rollback.

    Usage:
        writer = PrsWriter(session)
        await writer.write_attendance(politician, normalised_attendance, raw_html)
        await writer.write_activity(politician, normalised_activity, raw_html)
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Public write entry points
    # ------------------------------------------------------------------

    async def write_attendance(
        self,
        politician: Politician,
        attendance: NormalisedMpAttendance,
        raw_html: bytes,
        lok_sabha_number: int = 18,
    ) -> int:
        """
        Write all attendance sessions for an MP.

        Returns the number of new sessions written (duplicates skipped).

        Pipeline:
          1. Ensure SourceProvider (PRS)
          2. Create SourceSnapshot (idempotent by content_hash)
          3. Ensure LegislativeTerm for this politician
          4. Write each AttendanceRecord (idempotent by session+year)
        """
        db_log = logger.bind(
            prs_mp_id=attendance.prs_mp_id,
            politician_id=str(politician.id),
        )

        # 1. Source provider
        provider = await self._get_or_create_provider()

        # 2. Source snapshot — idempotent by content hash
        chash = content_hash(raw_html)
        try:
            snapshot = await self._create_snapshot(
                provider=provider,
                url=attendance.attendance_url,
                chash=chash,
                raw_html=raw_html,
            )
        except DuplicateSnapshotError:
            db_log.info("prs_attendance_snapshot_duplicate_skip", content_hash=chash[:12])
            return 0

        # 3. Ensure LegislativeTerm
        term = await self._get_or_create_legislative_term(
            politician=politician,
            lok_sabha_number=lok_sabha_number,
        )

        # 4. Write attendance records
        written = 0
        for session in attendance.sessions:
            created = await self._write_attendance_record(
                term=term,
                snapshot=snapshot,
                session=session,
            )
            if created:
                written += 1

        db_log.info("prs_attendance_written", sessions=written)
        await self._session.flush()
        return written

    async def write_activity(
        self,
        politician: Politician,
        activity: NormalisedMpActivity,
        raw_html: bytes,
        lok_sabha_number: int = 18,
    ) -> int:
        """
        Write all legislative activities for an MP.

        Returns the number of new activities written (duplicates skipped).

        Pipeline:
          1. Ensure SourceProvider (PRS)
          2. Create SourceSnapshot (idempotent by content_hash)
          3. Ensure LegislativeTerm for this politician
          4. Write each LegislativeActivity (idempotent by type+title+date)
        """
        db_log = logger.bind(
            prs_mp_id=activity.prs_mp_id,
            politician_id=str(politician.id),
        )

        # 1. Source provider
        provider = await self._get_or_create_provider()

        # 2. Source snapshot — idempotent by content hash
        chash = content_hash(raw_html)
        try:
            snapshot = await self._create_snapshot(
                provider=provider,
                url=activity.activity_url,
                chash=chash,
                raw_html=raw_html,
            )
        except DuplicateSnapshotError:
            db_log.info("prs_activity_snapshot_duplicate_skip", content_hash=chash[:12])
            return 0

        # 3. Ensure LegislativeTerm
        term = await self._get_or_create_legislative_term(
            politician=politician,
            lok_sabha_number=lok_sabha_number,
        )

        # 4. Write legislative activities
        written = 0
        for act in activity.activities:
            created = await self._write_legislative_activity(
                term=term,
                snapshot=snapshot,
                activity=act,
            )
            if created:
                written += 1

        db_log.info("prs_activity_written", activities=written)
        await self._session.flush()
        return written

    # ------------------------------------------------------------------
    # Get-or-create helpers
    # ------------------------------------------------------------------

    async def _get_or_create_provider(self) -> SourceProvider:
        """Get or create the PRS India SourceProvider."""
        result = await self._session.execute(
            select(SourceProvider).where(SourceProvider.name == PRS_PROVIDER_NAME)
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing

        provider = SourceProvider(
            name=PRS_PROVIDER_NAME,
            short_code="PRS",
            base_url=PRS_PROVIDER_URL,
            is_official=False,
            description=(
                "PRS Legislative Research — independent, non-partisan research "
                "organisation tracking parliamentary attendance and legislative "
                "activity for all sitting MPs."
            ),
        )
        self._session.add(provider)
        await self._session.flush()
        return provider

    async def _create_snapshot(
        self,
        provider: SourceProvider,
        url: str,
        chash: str,
        raw_html: bytes,
    ) -> SourceSnapshot:
        """
        Create a new SourceSnapshot.

        Raises DuplicateSnapshotError if the content hash already exists.
        This is the idempotency gate — callers must handle it.
        """
        result = await self._session.execute(
            select(SourceSnapshot).where(SourceSnapshot.content_hash == chash)
        )
        existing = result.scalar_one_or_none()
        if existing:
            raise DuplicateSnapshotError(
                f"PRS snapshot already exists for hash {chash[:12]}… (url={url})"
            )

        url_hash = hashlib.sha256(url.encode()).hexdigest()
        snapshot = SourceSnapshot(
            provider_id=provider.id,
            url=url,
            url_hash=url_hash,
            content_hash=chash,
            fetched_at=datetime.now(tz=UTC),
            parser_version="1.0.0",
            raw_content_size_bytes=len(raw_html),
        )
        self._session.add(snapshot)
        await self._session.flush()
        return snapshot

    async def _get_or_create_legislative_term(
        self,
        politician: Politician,
        lok_sabha_number: int,
    ) -> LegislativeTerm:
        """
        Get or create a LegislativeTerm for this politician in the Lok Sabha.

        Uses (politician_id, house=LOK_SABHA, lok_sabha_number) as the lookup key.
        If not found, creates a term with from_date = start of that Lok Sabha session.
        """
        result = await self._session.execute(
            select(LegislativeTerm).where(
                LegislativeTerm.politician_id == politician.id,
                LegislativeTerm.house == House.LOK_SABHA,
                LegislativeTerm.lok_sabha_number == lok_sabha_number,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing

        from datetime import date

        # Approximate start dates for each Lok Sabha
        lok_sabha_start_dates: dict[int, date] = {
            17: date(2019, 6, 17),
            18: date(2024, 6, 24),
        }
        from_date = lok_sabha_start_dates.get(lok_sabha_number, date(2024, 6, 24))

        term = LegislativeTerm(
            politician_id=politician.id,
            house=House.LOK_SABHA,
            from_date=from_date,
            lok_sabha_number=lok_sabha_number,
        )
        self._session.add(term)
        await self._session.flush()
        return term

    async def _write_attendance_record(
        self,
        term: LegislativeTerm,
        snapshot: SourceSnapshot,
        session: NormalisedAttendanceSession,
    ) -> bool:
        """
        Write one AttendanceRecord, idempotent by (term_id, session_name, session_year).

        Returns True if a new record was created, False if it already existed.
        """

        result = await self._session.execute(
            select(AttendanceRecord).where(
                AttendanceRecord.legislative_term_id == term.id,
                AttendanceRecord.session_name == session.session_name,
                AttendanceRecord.session_year == session.session_year,
            )
        )
        if result.scalar_one_or_none():
            return False

        record = AttendanceRecord(
            legislative_term_id=term.id,
            source_snapshot_id=snapshot.id,
            session_name=session.session_name,
            session_year=session.session_year,
            days_present=session.days_present,
            days_total=session.days_total,
            attendance_pct=session.attendance_pct,
        )
        self._session.add(record)
        return True

    async def _write_legislative_activity(
        self,
        term: LegislativeTerm,
        snapshot: SourceSnapshot,
        activity: NormalisedLegislativeActivity,
    ) -> bool:
        """
        Write one LegislativeActivity, idempotent by (term_id, activity_type, title, date).

        Returns True if a new record was created, False if it already existed.
        """
        # Build idempotency key from key fields
        stmt = select(LegislativeActivity).where(
            LegislativeActivity.legislative_term_id == term.id,
            LegislativeActivity.activity_type == activity.activity_type,
        )
        if activity.title:
            stmt = stmt.where(LegislativeActivity.title == activity.title)
        if activity.activity_date:
            stmt = stmt.where(LegislativeActivity.activity_date == activity.activity_date)

        result = await self._session.execute(stmt)
        if result.scalar_one_or_none():
            return False

        record = LegislativeActivity(
            legislative_term_id=term.id,
            source_snapshot_id=snapshot.id,
            activity_type=activity.activity_type,
            title=activity.title,
            description=activity.description,
            activity_date=activity.activity_date,
            session_name=activity.session_name,
            ministry_concerned=activity.ministry_concerned,
            is_admitted=activity.is_admitted,
        )
        self._session.add(record)
        return True

