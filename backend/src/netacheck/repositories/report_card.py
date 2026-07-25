"""
Report card repository.

Aggregates all data needed to build a politician's report card:
criminal cases, assets, attendance, legislative activity, and grade.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from netacheck.models.affidavit import Affidavit, AffidavitEntry
from netacheck.models.assets import AssetDeclaration
from netacheck.models.attendance import AttendanceRecord
from netacheck.models.criminal import CriminalCase
from netacheck.models.election import ElectionResult
from netacheck.models.grading import GradeSnapshot
from netacheck.models.legislative import LegislativeActivity
from netacheck.models.legislature import LegislativeTerm
from netacheck.repositories.base import AsyncRepository


class ReportCardRepository:
    """
    Composite repository for report card data.

    Does not inherit from AsyncRepository since it spans multiple models.
    """

    def __init__(self, session: object) -> None:
        self.session = session  # type: ignore[assignment]

    async def get_latest_grade(self, politician_id: uuid.UUID) -> GradeSnapshot | None:
        """Return the most recently computed grade snapshot for a politician."""
        stmt = (
            select(GradeSnapshot)
            .where(GradeSnapshot.politician_id == politician_id)
            .order_by(GradeSnapshot.computed_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_criminal_cases(self, politician_id: uuid.UUID) -> list[CriminalCase]:
        """Get all criminal cases for a politician across all elections."""
        stmt = (
            select(CriminalCase)
            .join(AffidavitEntry, CriminalCase.affidavit_entry_id == AffidavitEntry.id)
            .join(Affidavit, AffidavitEntry.affidavit_id == Affidavit.id)
            .join(ElectionResult, Affidavit.election_result_id == ElectionResult.id)
            .where(ElectionResult.politician_id == politician_id)
            .order_by(CriminalCase.year_filed.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_assets(
        self,
        politician_id: uuid.UUID,
        *,
        election_year: int | None = None,
    ) -> list[AssetDeclaration]:
        """Get asset declarations, optionally filtered by election year."""
        stmt = (
            select(AssetDeclaration)
            .join(AffidavitEntry, AssetDeclaration.affidavit_entry_id == AffidavitEntry.id)
            .join(Affidavit, AffidavitEntry.affidavit_id == Affidavit.id)
            .join(ElectionResult, Affidavit.election_result_id == ElectionResult.id)
            .where(ElectionResult.politician_id == politician_id)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_attendance(self, politician_id: uuid.UUID) -> list[AttendanceRecord]:
        """Get all attendance records for a politician."""
        stmt = (
            select(AttendanceRecord)
            .join(LegislativeTerm, AttendanceRecord.legislative_term_id == LegislativeTerm.id)
            .where(LegislativeTerm.politician_id == politician_id)
            .order_by(AttendanceRecord.session_year.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_legislative_activity(
        self,
        politician_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> list[LegislativeActivity]:
        """Get legislative activities for a politician, most recent first."""
        stmt = (
            select(LegislativeActivity)
            .join(
                LegislativeTerm,
                LegislativeActivity.legislative_term_id == LegislativeTerm.id,
            )
            .where(LegislativeTerm.politician_id == politician_id)
            .order_by(LegislativeActivity.activity_date.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
