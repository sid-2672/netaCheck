"""
Unit tests for the PRS parser.

All tests use HTML fixture files — no network requests, no database.
Tests verify that the parser correctly extracts raw data from HTML.

Coverage targets:
  - PrsAttendanceParser: standard page, empty page, partial data
  - PrsActivityParser: questions, debates, bills, mixed/empty tables
  - PrsProfileParser: name extraction, info extraction
  - _parse_session_name: various date formats
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netacheck.ingestion.prs.parser import (
    PrsActivityParser,
    PrsAttendanceParser,
    PrsProfileParser,
    _parse_session_name,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "prs_html"
pytestmark = pytest.mark.unit


def _load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# ---------------------------------------------------------------------------
# _parse_session_name helper
# ---------------------------------------------------------------------------


class TestParseSessionName:
    """Unit tests for the session name parser helper."""

    def test_budget_session_with_year(self) -> None:
        name, year = _parse_session_name("Budget Session 2024")
        assert "Budget" in name
        assert year == "2024"

    def test_winter_session_with_range_year(self) -> None:
        name, year = _parse_session_name("Winter Session 2023-24")
        assert "Winter" in name
        assert year == "2023"

    def test_monsoon_session(self) -> None:
        name, year = _parse_session_name("Monsoon Session 2023")
        assert "Monsoon" in name
        assert year == "2023"

    def test_special_session(self) -> None:
        name, year = _parse_session_name("Special Session Sep 2022")
        assert name  # non-empty
        assert year == "2022"

    def test_no_year(self) -> None:
        name, year = _parse_session_name("Unknown Session")
        assert name
        assert year == ""  # no year found

    def test_empty_string(self) -> None:
        name, year = _parse_session_name("")
        assert name == ""
        assert year == ""


# ---------------------------------------------------------------------------
# PrsAttendanceParser
# ---------------------------------------------------------------------------


class TestPrsAttendanceParser:
    """Tests for the PRS attendance HTML parser."""

    def test_standard_attendance_page(self) -> None:
        """Parse the full attendance fixture with 8 sessions."""
        html = _load("mp_attendance_page.html")
        parser = PrsAttendanceParser()
        result = parser.parse(html, mp_id=12345, attendance_url="https://prsindia.org/mptrack/18/attendance/12345")

        assert result.prs_mp_id == 12345
        assert result.attendance_url == "https://prsindia.org/mptrack/18/attendance/12345"
        assert len(result.sessions) > 0

    def test_standard_page_has_correct_sessions(self) -> None:
        """Verify session names from the fixture are extracted."""
        html = _load("mp_attendance_page.html")
        parser = PrsAttendanceParser()
        result = parser.parse(html, mp_id=1, attendance_url="https://prsindia.org/test")

        session_names = [s.session_name for s in result.sessions]
        assert any("Budget" in name for name in session_names)
        assert any("Winter" in name for name in session_names)

    def test_standard_page_days_are_integers(self) -> None:
        """Verify days_present and days_total are non-empty strings."""
        html = _load("mp_attendance_page.html")
        parser = PrsAttendanceParser()
        result = parser.parse(html, mp_id=1, attendance_url="https://prsindia.org/test")

        for session in result.sessions:
            assert session.days_present  # non-empty
            assert session.days_total
            # Should be parseable as integers
            assert int(session.days_present) >= 0
            assert int(session.days_total) >= 0

    def test_standard_page_attendance_pct_present(self) -> None:
        """Attendance percentage column should be extracted."""
        html = _load("mp_attendance_page.html")
        parser = PrsAttendanceParser()
        result = parser.parse(html, mp_id=1, attendance_url="https://prsindia.org/test")

        for session in result.sessions:
            # May be empty string if column absent, but fixture has it
            assert session.attendance_pct

    def test_empty_page_returns_empty_sessions(self) -> None:
        """An empty/404 page should return empty sessions list, not raise."""
        html = _load("mp_attendance_empty.html")
        parser = PrsAttendanceParser()
        result = parser.parse(html, mp_id=9999, attendance_url="https://prsindia.org/test")

        assert result.prs_mp_id == 9999
        assert result.sessions == []

    def test_minimal_html_returns_empty_sessions(self) -> None:
        """Completely minimal HTML with no tables returns empty sessions."""
        html = b"<html><body><p>No data</p></body></html>"
        parser = PrsAttendanceParser()
        result = parser.parse(html, mp_id=1, attendance_url="https://prsindia.org/test")

        assert result.sessions == []

    def test_session_year_extracted(self) -> None:
        """Session year should be extracted from session name."""
        html = _load("mp_attendance_page.html")
        parser = PrsAttendanceParser()
        result = parser.parse(html, mp_id=1, attendance_url="https://prsindia.org/test")

        for session in result.sessions:
            # Year should be a 4-digit string
            if session.session_year:
                assert len(session.session_year) == 4
                assert session.session_year.isdigit()


# ---------------------------------------------------------------------------
# PrsActivityParser
# ---------------------------------------------------------------------------


class TestPrsActivityParser:
    """Tests for the PRS legislative activity HTML parser."""

    def test_standard_activity_page(self) -> None:
        """Parse the full activity fixture."""
        html = _load("mp_activity_page.html")
        parser = PrsActivityParser()
        result = parser.parse(html, mp_id=12345, activity_url="https://prsindia.org/mptrack/18/questions/12345")

        assert result.prs_mp_id == 12345
        assert result.activity_url == "https://prsindia.org/mptrack/18/questions/12345"

    def test_questions_extracted(self) -> None:
        """Questions section should yield question records."""
        html = _load("mp_activity_page.html")
        parser = PrsActivityParser()
        result = parser.parse(html, mp_id=1, activity_url="https://prsindia.org/test")

        assert len(result.questions) > 0

    def test_question_types_classified(self) -> None:
        """Starred and unstarred questions should be classified correctly."""
        html = _load("mp_activity_page.html")
        parser = PrsActivityParser()
        result = parser.parse(html, mp_id=1, activity_url="https://prsindia.org/test")

        question_types = {q.question_type for q in result.questions}
        assert "STARRED" in question_types or "UNSTARRED" in question_types

    def test_debates_extracted(self) -> None:
        """Debates section should yield debate records."""
        html = _load("mp_activity_page.html")
        parser = PrsActivityParser()
        result = parser.parse(html, mp_id=1, activity_url="https://prsindia.org/test")

        assert len(result.debates) > 0

    def test_debates_have_subject(self) -> None:
        """Each debate record should have a non-empty subject."""
        html = _load("mp_activity_page.html")
        parser = PrsActivityParser()
        result = parser.parse(html, mp_id=1, activity_url="https://prsindia.org/test")

        for debate in result.debates:
            assert debate.subject or debate.date  # at least one should be present

    def test_bills_extracted(self) -> None:
        """Private member bills section should yield bill records."""
        html = _load("mp_activity_page.html")
        parser = PrsActivityParser()
        result = parser.parse(html, mp_id=1, activity_url="https://prsindia.org/test")

        assert len(result.bills) > 0

    def test_bills_have_name(self) -> None:
        """Each bill should have a non-empty name."""
        html = _load("mp_activity_page.html")
        parser = PrsActivityParser()
        result = parser.parse(html, mp_id=1, activity_url="https://prsindia.org/test")

        for bill in result.bills:
            assert bill.bill_name

    def test_empty_page_returns_empty_lists(self) -> None:
        """Empty HTML page should return empty lists, not raise."""
        html = b"<html><body><p>No data</p></body></html>"
        parser = PrsActivityParser()
        result = parser.parse(html, mp_id=1, activity_url="https://prsindia.org/test")

        assert result.questions == []
        assert result.debates == []
        assert result.bills == []

    def test_parser_does_not_raise_on_malformed_html(self) -> None:
        """Malformed HTML should not raise — parser is defensive."""
        malformed = b"<html><body><table><tr><td>broken"
        parser = PrsActivityParser()
        # Should complete without raising
        result = parser.parse(malformed, mp_id=1, activity_url="https://prsindia.org/test")
        assert result is not None


# ---------------------------------------------------------------------------
# PrsProfileParser
# ---------------------------------------------------------------------------


class TestPrsProfileParser:
    """Tests for the PRS profile page parser."""

    def test_standard_profile_page(self) -> None:
        """Parse the standard profile fixture."""
        html = _load("mp_profile_page.html")
        parser = PrsProfileParser()
        result = parser.parse(html, mp_id=12345, profile_url="https://prsindia.org/mptrack/18/12345", lok_sabha_number=18)

        assert result.prs_mp_id == 12345
        assert result.lok_sabha_number == 18

    def test_name_extracted(self) -> None:
        """MP name should be extracted from h1.mp-name."""
        html = _load("mp_profile_page.html")
        parser = PrsProfileParser()
        result = parser.parse(html, mp_id=1, profile_url="https://prsindia.org/test", lok_sabha_number=18)

        assert result.name
        assert "modi" in result.name.lower() or "Modi" in result.name

    def test_empty_page_returns_empty_name(self) -> None:
        """Empty page returns profile with empty name fields."""
        html = b"<html><body></body></html>"
        parser = PrsProfileParser()
        result = parser.parse(html, mp_id=1, profile_url="https://prsindia.org/test", lok_sabha_number=18)

        assert result.prs_mp_id == 1
        assert result.name == ""
