"""
PRS normalizer — converts PrsRaw* objects into domain model instances.

Responsibilities:
  - Parse raw strings → typed Python types (int, Decimal, date, enum)
  - Map activity type strings → ActivityType enum
  - Produce ORM-ready dataclasses (unsaved — writer saves them)
  - Validate data quality and reject unusable records

Design:
  - Pure functions where possible (no DB access, no side effects)
  - All normalisation failures return None / empty list (never raise)
  - Logging for data quality issues
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

import structlog

from netacheck.models.legislative import ActivityType

if TYPE_CHECKING:
    from netacheck.ingestion.prs.parser import (
        PrsRawAttendanceSession,
        PrsRawBill,
        PrsRawDebate,
        PrsRawMpActivity,
        PrsRawMpAttendance,
        PrsRawQuestion,
    )

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Normalised output containers (plain dataclasses — no SQLAlchemy)
# ---------------------------------------------------------------------------


@dataclass
class NormalisedAttendanceSession:
    """Typed attendance record for one parliamentary session."""

    session_name: str
    session_year: int
    days_present: int
    days_total: int
    attendance_pct: Decimal | None


@dataclass
class NormalisedLegislativeActivity:
    """Typed legislative activity record."""

    activity_type: ActivityType
    title: str | None
    description: str | None
    activity_date: date | None
    session_name: str | None
    ministry_concerned: str | None
    is_admitted: bool | None


@dataclass
class NormalisedMpAttendance:
    """All attendance data for one MP, ready for DB write."""

    prs_mp_id: int
    attendance_url: str
    sessions: list[NormalisedAttendanceSession] = field(default_factory=list)


@dataclass
class NormalisedMpActivity:
    """All legislative activity for one MP, ready for DB write."""

    prs_mp_id: int
    activity_url: str
    activities: list[NormalisedLegislativeActivity] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Normalizers
# ---------------------------------------------------------------------------


class PrsAttendanceNormalizer:
    """Converts PrsRawMpAttendance → NormalisedMpAttendance."""

    def normalise(self, raw: PrsRawMpAttendance) -> NormalisedMpAttendance:
        """
        Normalise all attendance sessions.

        Sessions with invalid/unparseable data are skipped with a warning log.
        Returns a NormalisedMpAttendance even if sessions is empty.
        """
        normalised_sessions: list[NormalisedAttendanceSession] = []

        for session in raw.sessions:
            result = self._normalise_session(session, raw.prs_mp_id)
            if result is not None:
                normalised_sessions.append(result)

        return NormalisedMpAttendance(
            prs_mp_id=raw.prs_mp_id,
            attendance_url=raw.attendance_url,
            sessions=normalised_sessions,
        )

    def _normalise_session(
        self,
        raw: PrsRawAttendanceSession,
        mp_id: int,
    ) -> NormalisedAttendanceSession | None:
        """
        Normalise one session row.

        Returns None if session_name is missing or days_present/days_total
        cannot be parsed into valid integers.
        """

        session_name = raw.session_name.strip()
        if not session_name:
            return None

        days_present = _parse_int(raw.days_present)
        days_total = _parse_int(raw.days_total)

        if days_present is None or days_total is None:
            logger.debug(
                "prs_session_skip_invalid_days",
                mp_id=mp_id,
                session=session_name,
                raw_present=raw.days_present,
                raw_total=raw.days_total,
            )
            return None

        if days_total == 0:
            logger.debug(
                "prs_session_skip_zero_total",
                mp_id=mp_id,
                session=session_name,
            )
            return None

        session_year = _parse_int(raw.session_year)
        if session_year is None:
            # Derive year from session name if possible
            year_match = re.search(r"\d{4}", session_name)
            session_year = int(year_match.group()) if year_match else datetime.now(tz=UTC).year

        attendance_pct = _parse_decimal_pct(raw.attendance_pct)
        if attendance_pct is None and days_total > 0:
            # Compute from days if not provided
            attendance_pct = Decimal(str(round(days_present * 100 / days_total, 2)))

        return NormalisedAttendanceSession(
            session_name=session_name,
            session_year=session_year,
            days_present=days_present,
            days_total=days_total,
            attendance_pct=attendance_pct,
        )


class PrsActivityNormalizer:
    """Converts PrsRawMpActivity → NormalisedMpActivity."""

    def normalise(self, raw: PrsRawMpActivity) -> NormalisedMpActivity:
        """
        Normalise all legislative activities.

        Converts questions, debates, and bills into NormalisedLegislativeActivity
        records using the ActivityType enum from the model.
        """
        activities: list[NormalisedLegislativeActivity] = []

        for question in raw.questions:
            result = self._normalise_question(question)
            if result is not None:
                activities.append(result)

        for debate in raw.debates:
            result = self._normalise_debate(debate)
            if result is not None:
                activities.append(result)

        for bill in raw.bills:
            result = self._normalise_bill(bill)
            if result is not None:
                activities.append(result)

        return NormalisedMpActivity(
            prs_mp_id=raw.prs_mp_id,
            activity_url=raw.activity_url,
            activities=activities,
        )

    def _normalise_question(
        self, raw: PrsRawQuestion
    ) -> NormalisedLegislativeActivity | None:
        """Normalise a parliamentary question record."""
        if not raw.subject and not raw.question_number:
            return None

        activity_type = (
            ActivityType.STARRED_QUESTION
            if raw.question_type == "STARRED"
            else ActivityType.UNSTARRED_QUESTION
        )

        title = raw.subject or f"Question No. {raw.question_number}"
        activity_date = _parse_date(raw.question_date)

        return NormalisedLegislativeActivity(
            activity_type=activity_type,
            title=title[:500] if title else None,
            description=None,
            activity_date=activity_date,
            session_name=raw.session_name or None,
            ministry_concerned=raw.ministry[:200] if raw.ministry else None,
            is_admitted=None,  # PRS doesn't provide admission status for questions
        )

    def _normalise_debate(
        self, raw: PrsRawDebate
    ) -> NormalisedLegislativeActivity | None:
        """Normalise a debate participation record."""
        if not raw.subject and not raw.date:
            return None

        activity_type = _map_debate_type(raw.debate_type)
        activity_date = _parse_date(raw.date)

        return NormalisedLegislativeActivity(
            activity_type=activity_type,
            title=raw.subject[:500] if raw.subject else None,
            description=None,
            activity_date=activity_date,
            session_name=raw.session_name or None,
            ministry_concerned=None,
            is_admitted=None,
        )

    def _normalise_bill(
        self, raw: PrsRawBill
    ) -> NormalisedLegislativeActivity | None:
        """Normalise a private member bill record."""
        if not raw.bill_name:
            return None

        activity_date = _parse_date(raw.date_introduced)

        return NormalisedLegislativeActivity(
            activity_type=ActivityType.PRIVATE_MEMBER_BILL,
            title=raw.bill_name[:500],
            description=raw.status or None,
            activity_date=activity_date,
            session_name=raw.session_name or None,
            ministry_concerned=None,
            is_admitted=None,
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_int(raw: str) -> int | None:
    """Parse raw string to integer, returning None on failure."""
    if not raw:
        return None
    cleaned = raw.strip().replace(",", "")
    match = re.search(r"\d+", cleaned)
    if match:
        try:
            return int(match.group())
        except ValueError:
            return None
    return None


def _parse_decimal_pct(raw: str) -> Decimal | None:
    """
    Parse a percentage string to Decimal.

    Handles: "82%", "82.5%", "82.5", "0.825" (fraction form)
    """
    if not raw:
        return None
    cleaned = raw.strip().replace("%", "").replace(",", "")
    match = re.search(r"\d+\.?\d*", cleaned)
    if not match:
        return None
    try:
        val = Decimal(match.group())
        # If value looks like a fraction (0.xx), convert to percentage
        if val < Decimal("1") and val > Decimal("0"):
            val = val * Decimal("100")
        # Clamp to valid range
        if val < Decimal("0") or val > Decimal("100"):
            return None
        return val.quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


_DATE_PATTERNS = [
    # DD-MM-YYYY
    (r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", lambda m: date(int(m.group(3)), int(m.group(2)), int(m.group(1)))),
    # DD MMM YYYY (e.g. "15 Mar 2024")
    (
        r"(\d{1,2})\s+([A-Za-z]{3,})\s+(\d{4})",
        lambda m: _parse_day_month_year(m.group(1), m.group(2), m.group(3)),
    ),
    # YYYY-MM-DD (ISO format)
    (r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", lambda m: date(int(m.group(1)), int(m.group(2)), int(m.group(3)))),
    # MMM YYYY (month + year only — use day=1)
    (r"([A-Za-z]{3,})\s+(\d{4})", lambda m: _parse_month_year(m.group(1), m.group(2))),
]

_MONTH_MAP: dict[str, int] = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}


def _parse_day_month_year(day: str, month: str, year: str) -> date | None:
    month_num = _MONTH_MAP.get(month.lower()[:3])
    if not month_num:
        return None
    try:
        return date(int(year), month_num, int(day))
    except ValueError:
        return None


def _parse_month_year(month: str, year: str) -> date | None:
    month_num = _MONTH_MAP.get(month.lower()[:3])
    if not month_num:
        return None
    try:
        return date(int(year), month_num, 1)
    except ValueError:
        return None


def _parse_date(raw: str) -> date | None:
    """
    Parse a date string from PRS pages.

    Tries multiple common date formats in order of specificity.
    Returns None if no format matches.
    """
    if not raw:
        return None
    raw = raw.strip()

    import re as _re

    for pattern, builder in _DATE_PATTERNS:
        match = _re.search(pattern, raw)
        if match:
            try:
                result = builder(match)
                return result
            except (ValueError, TypeError):
                continue

    return None


def _map_debate_type(debate_type_raw: str) -> ActivityType:
    """
    Map a raw debate type string to the ActivityType enum.

    PRS uses various naming conventions across pages.
    """
    raw_lower = debate_type_raw.lower()

    if "zero hour" in raw_lower or "zero-hour" in raw_lower:
        return ActivityType.ZERO_HOUR
    if "calling attention" in raw_lower:
        return ActivityType.CALLING_ATTENTION
    if "short duration" in raw_lower or "short notice" in raw_lower:
        return ActivityType.SHORT_DURATION_DISCUSSION
    if "private member" in raw_lower:
        return ActivityType.PRIVATE_MEMBER_BILL

    # Default for any unrecognized debate participation
    return ActivityType.DEBATE_PARTICIPATION
