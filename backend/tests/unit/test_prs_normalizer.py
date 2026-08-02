"""
Unit tests for the PRS normalizer.

Tests the conversion of PrsRaw* objects into typed NormalisedMp* objects.
No database, no network — pure unit tests.

Coverage targets:
  - PrsAttendanceNormalizer: valid sessions, invalid data rejection, pct computation
  - PrsActivityNormalizer: question types, debate type mapping, bill normalisation
  - Helper functions: _parse_int, _parse_decimal_pct, _parse_date, _map_debate_type
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from netacheck.ingestion.prs.normalizer import (
    PrsActivityNormalizer,
    PrsAttendanceNormalizer,
    _map_debate_type,
    _parse_date,
    _parse_decimal_pct,
    _parse_int,
)
from netacheck.ingestion.prs.parser import (
    PrsRawAttendanceSession,
    PrsRawBill,
    PrsRawDebate,
    PrsRawMpActivity,
    PrsRawMpAttendance,
    PrsRawQuestion,
)
from netacheck.models.legislative import ActivityType

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# _parse_int
# ---------------------------------------------------------------------------


class TestParseInt:
    def test_plain_integer(self) -> None:
        assert _parse_int("42") == 42

    def test_integer_with_whitespace(self) -> None:
        assert _parse_int("  28  ") == 28

    def test_integer_with_comma(self) -> None:
        assert _parse_int("1,234") == 1234

    def test_zero(self) -> None:
        assert _parse_int("0") == 0

    def test_empty_string(self) -> None:
        assert _parse_int("") is None

    def test_non_numeric(self) -> None:
        assert _parse_int("N/A") is None

    def test_mixed_text(self) -> None:
        # Should extract first digit sequence
        assert _parse_int("28 days") == 28


# ---------------------------------------------------------------------------
# _parse_decimal_pct
# ---------------------------------------------------------------------------


class TestParseDecimalPct:
    def test_percent_with_symbol(self) -> None:
        result = _parse_decimal_pct("80%")
        assert result == Decimal("80.00")

    def test_percent_with_decimal(self) -> None:
        result = _parse_decimal_pct("82.5%")
        assert result == Decimal("82.50")

    def test_percent_without_symbol(self) -> None:
        result = _parse_decimal_pct("77.78")
        assert result == Decimal("77.78")

    def test_fraction_form_converted(self) -> None:
        # 0.80 should be treated as a fraction and converted to 80%
        result = _parse_decimal_pct("0.80")
        assert result == Decimal("80.00")

    def test_100_percent(self) -> None:
        result = _parse_decimal_pct("100%")
        assert result == Decimal("100.00")

    def test_empty_string(self) -> None:
        assert _parse_decimal_pct("") is None

    def test_invalid_string(self) -> None:
        assert _parse_decimal_pct("N/A") is None

    def test_out_of_range_returns_none(self) -> None:
        assert _parse_decimal_pct("150%") is None


# ---------------------------------------------------------------------------
# _parse_date
# ---------------------------------------------------------------------------


class TestParseDate:
    def test_dd_mm_yyyy_slash(self) -> None:
        result = _parse_date("15/03/2024")
        assert result == date(2024, 3, 15)

    def test_dd_mm_yyyy_hyphen(self) -> None:
        result = _parse_date("15-03-2024")
        assert result == date(2024, 3, 15)

    def test_dd_mmm_yyyy(self) -> None:
        result = _parse_date("15 Mar 2024")
        assert result == date(2024, 3, 15)

    def test_dd_full_month_yyyy(self) -> None:
        result = _parse_date("15 March 2024")
        assert result == date(2024, 3, 15)

    def test_iso_format(self) -> None:
        result = _parse_date("2024-03-15")
        assert result == date(2024, 3, 15)

    def test_month_year_only(self) -> None:
        result = _parse_date("Mar 2024")
        assert result == date(2024, 3, 1)

    def test_empty_string(self) -> None:
        assert _parse_date("") is None

    def test_invalid_string(self) -> None:
        assert _parse_date("invalid date") is None

    def test_december(self) -> None:
        result = _parse_date("15 Dec 2023")
        assert result == date(2023, 12, 15)


# ---------------------------------------------------------------------------
# _map_debate_type
# ---------------------------------------------------------------------------


class TestMapDebateType:
    def test_zero_hour(self) -> None:
        assert _map_debate_type("Zero Hour") == ActivityType.ZERO_HOUR

    def test_zero_hour_hyphenated(self) -> None:
        assert _map_debate_type("Zero-Hour Notice") == ActivityType.ZERO_HOUR

    def test_calling_attention(self) -> None:
        assert _map_debate_type("Calling Attention Motion") == ActivityType.CALLING_ATTENTION

    def test_short_duration(self) -> None:
        assert _map_debate_type("Short Duration Discussion") == ActivityType.SHORT_DURATION_DISCUSSION

    def test_private_member_bill(self) -> None:
        assert _map_debate_type("Private Member Bill Discussion") == ActivityType.PRIVATE_MEMBER_BILL

    def test_unknown_defaults_to_debate(self) -> None:
        assert _map_debate_type("Some Other Type") == ActivityType.DEBATE_PARTICIPATION

    def test_empty_string_defaults_to_debate(self) -> None:
        assert _map_debate_type("") == ActivityType.DEBATE_PARTICIPATION


# ---------------------------------------------------------------------------
# PrsAttendanceNormalizer
# ---------------------------------------------------------------------------


class TestPrsAttendanceNormalizer:
    """Tests for PRS attendance normalizer."""

    def _make_raw_attendance(
        self, sessions: list[PrsRawAttendanceSession] | None = None
    ) -> PrsRawMpAttendance:
        return PrsRawMpAttendance(
            prs_mp_id=12345,
            attendance_url="https://prsindia.org/test",
            sessions=sessions or [],
        )

    def test_empty_sessions(self) -> None:
        """No sessions → empty normalised sessions."""
        raw = self._make_raw_attendance([])
        result = PrsAttendanceNormalizer().normalise(raw)
        assert result.sessions == []
        assert result.prs_mp_id == 12345

    def test_valid_session(self) -> None:
        """Valid session with all fields → normalised session."""
        raw = self._make_raw_attendance([
            PrsRawAttendanceSession(
                session_name="Budget Session",
                session_year="2024",
                days_present="28",
                days_total="35",
                attendance_pct="80%",
            )
        ])
        result = PrsAttendanceNormalizer().normalise(raw)
        assert len(result.sessions) == 1
        s = result.sessions[0]
        assert s.session_name == "Budget Session"
        assert s.session_year == 2024
        assert s.days_present == 28
        assert s.days_total == 35
        assert s.attendance_pct == Decimal("80.00")

    def test_pct_computed_when_absent(self) -> None:
        """Attendance % should be computed from days if not provided."""
        raw = self._make_raw_attendance([
            PrsRawAttendanceSession(
                session_name="Monsoon Session",
                session_year="2023",
                days_present="16",
                days_total="20",
                attendance_pct="",  # Missing — should be computed
            )
        ])
        result = PrsAttendanceNormalizer().normalise(raw)
        assert len(result.sessions) == 1
        pct = result.sessions[0].attendance_pct
        assert pct is not None
        assert pct == Decimal("80.00")

    def test_invalid_days_skipped(self) -> None:
        """Session with invalid days_present should be skipped."""
        raw = self._make_raw_attendance([
            PrsRawAttendanceSession(
                session_name="Unknown Session",
                session_year="2023",
                days_present="N/A",
                days_total="20",
                attendance_pct="",
            )
        ])
        result = PrsAttendanceNormalizer().normalise(raw)
        assert result.sessions == []

    def test_zero_total_days_skipped(self) -> None:
        """Session with zero total days should be skipped (avoid division by zero)."""
        raw = self._make_raw_attendance([
            PrsRawAttendanceSession(
                session_name="Empty Session",
                session_year="2024",
                days_present="0",
                days_total="0",
                attendance_pct="",
            )
        ])
        result = PrsAttendanceNormalizer().normalise(raw)
        assert result.sessions == []

    def test_empty_session_name_skipped(self) -> None:
        """Session with empty name should be skipped."""
        raw = self._make_raw_attendance([
            PrsRawAttendanceSession(
                session_name="",
                session_year="2024",
                days_present="10",
                days_total="15",
                attendance_pct="66%",
            )
        ])
        result = PrsAttendanceNormalizer().normalise(raw)
        assert result.sessions == []

    def test_multiple_sessions(self) -> None:
        """Multiple valid sessions are all normalised."""
        raw = self._make_raw_attendance([
            PrsRawAttendanceSession(
                session_name="Budget Session",
                session_year="2024",
                days_present="28",
                days_total="35",
                attendance_pct="80%",
            ),
            PrsRawAttendanceSession(
                session_name="Winter Session",
                session_year="2023",
                days_present="14",
                days_total="18",
                attendance_pct="77.78%",
            ),
        ])
        result = PrsAttendanceNormalizer().normalise(raw)
        assert len(result.sessions) == 2

    def test_year_derived_from_session_name(self) -> None:
        """If session_year is empty, derive from session_name."""
        raw = self._make_raw_attendance([
            PrsRawAttendanceSession(
                session_name="Budget Session 2024",
                session_year="",  # Empty — should be derived
                days_present="20",
                days_total="30",
                attendance_pct="66%",
            )
        ])
        result = PrsAttendanceNormalizer().normalise(raw)
        assert len(result.sessions) == 1
        assert result.sessions[0].session_year == 2024


# ---------------------------------------------------------------------------
# PrsActivityNormalizer
# ---------------------------------------------------------------------------


class TestPrsActivityNormalizer:
    """Tests for PRS activity normalizer."""

    def _make_raw_activity(
        self,
        questions: list[PrsRawQuestion] | None = None,
        debates: list[PrsRawDebate] | None = None,
        bills: list[PrsRawBill] | None = None,
    ) -> PrsRawMpActivity:
        return PrsRawMpActivity(
            prs_mp_id=12345,
            activity_url="https://prsindia.org/test",
            questions=questions or [],
            debates=debates or [],
            bills=bills or [],
        )

    def test_empty_activity(self) -> None:
        """No activity → empty activities list."""
        raw = self._make_raw_activity()
        result = PrsActivityNormalizer().normalise(raw)
        assert result.activities == []

    def test_starred_question_normalised(self) -> None:
        """Starred question → ActivityType.STARRED_QUESTION."""
        raw = self._make_raw_activity(questions=[
            PrsRawQuestion(
                serial_no="1",
                question_type="STARRED",
                question_number="Q123",
                question_date="15 Mar 2024",
                session_name="Budget Session 2024",
                subject="Development projects in Varanasi",
                ministry="Ministry of Road Transport",
            )
        ])
        result = PrsActivityNormalizer().normalise(raw)
        assert len(result.activities) == 1
        act = result.activities[0]
        assert act.activity_type == ActivityType.STARRED_QUESTION
        assert "Varanasi" in (act.title or "")
        assert act.activity_date == date(2024, 3, 15)
        assert act.ministry_concerned == "Ministry of Road Transport"

    def test_unstarred_question_normalised(self) -> None:
        """Unstarred question → ActivityType.UNSTARRED_QUESTION."""
        raw = self._make_raw_activity(questions=[
            PrsRawQuestion(
                question_type="UNSTARRED",
                question_number="Q456",
                subject="Smart City Mission",
            )
        ])
        result = PrsActivityNormalizer().normalise(raw)
        assert len(result.activities) == 1
        assert result.activities[0].activity_type == ActivityType.UNSTARRED_QUESTION

    def test_empty_question_skipped(self) -> None:
        """Question with no subject and no number should be skipped."""
        raw = self._make_raw_activity(questions=[
            PrsRawQuestion(question_type="STARRED")
        ])
        result = PrsActivityNormalizer().normalise(raw)
        assert result.activities == []

    def test_debate_normalised(self) -> None:
        """Debate record → LegislativeActivity."""
        raw = self._make_raw_activity(debates=[
            PrsRawDebate(
                date="29 Jul 2024",
                session_name="Budget Session 2024",
                debate_type="Zero Hour",
                subject="Ganga Pollution Issues",
            )
        ])
        result = PrsActivityNormalizer().normalise(raw)
        assert len(result.activities) == 1
        act = result.activities[0]
        assert act.activity_type == ActivityType.ZERO_HOUR
        assert "Ganga" in (act.title or "")
        assert act.activity_date == date(2024, 7, 29)

    def test_calling_attention_debate(self) -> None:
        """Calling Attention debate maps to CALLING_ATTENTION type."""
        raw = self._make_raw_activity(debates=[
            PrsRawDebate(
                date="14 Dec 2023",
                debate_type="Calling Attention",
                subject="Flood Relief",
            )
        ])
        result = PrsActivityNormalizer().normalise(raw)
        assert result.activities[0].activity_type == ActivityType.CALLING_ATTENTION

    def test_empty_debate_skipped(self) -> None:
        """Debate with no subject and no date should be skipped."""
        raw = self._make_raw_activity(debates=[PrsRawDebate()])
        result = PrsActivityNormalizer().normalise(raw)
        assert result.activities == []

    def test_private_member_bill_normalised(self) -> None:
        """Private member bill → ActivityType.PRIVATE_MEMBER_BILL."""
        raw = self._make_raw_activity(bills=[
            PrsRawBill(
                bill_name="The Ganga Rejuvenation Authority Bill, 2022",
                date_introduced="15 Dec 2022",
                session_name="Winter Session 2022",
                status="Lapsed",
            )
        ])
        result = PrsActivityNormalizer().normalise(raw)
        assert len(result.activities) == 1
        act = result.activities[0]
        assert act.activity_type == ActivityType.PRIVATE_MEMBER_BILL
        assert "Ganga" in (act.title or "")
        assert act.description == "Lapsed"
        assert act.activity_date == date(2022, 12, 15)

    def test_empty_bill_skipped(self) -> None:
        """Bill with no name should be skipped."""
        raw = self._make_raw_activity(bills=[PrsRawBill(bill_name="")])
        result = PrsActivityNormalizer().normalise(raw)
        assert result.activities == []

    def test_mixed_activities_combined(self) -> None:
        """Questions + debates + bills should all appear in activities list."""
        raw = self._make_raw_activity(
            questions=[PrsRawQuestion(question_type="STARRED", subject="Infrastructure")],
            debates=[PrsRawDebate(date="01 Jan 2024", subject="Water crisis")],
            bills=[PrsRawBill(bill_name="Test Bill 2024")],
        )
        result = PrsActivityNormalizer().normalise(raw)
        assert len(result.activities) == 3

    def test_title_truncated_at_500_chars(self) -> None:
        """Titles longer than 500 chars should be truncated."""
        long_subject = "A" * 600
        raw = self._make_raw_activity(questions=[
            PrsRawQuestion(question_type="STARRED", subject=long_subject)
        ])
        result = PrsActivityNormalizer().normalise(raw)
        assert len(result.activities) == 1
        assert len(result.activities[0].title or "") <= 500
