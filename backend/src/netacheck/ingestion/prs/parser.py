"""
PRS India HTML parser.

Converts raw HTML bytes from prsindia.org into structured raw data objects.
Uses BeautifulSoup4 + lxml for robust HTML parsing.

PRS page structure (as of 2024):
  Attendance page: Table with sessions and days present/total
  Activity page:   Tables for starred/unstarred questions, debates, bills

All raw string values are preserved here - normalizer handles type conversion.

Design:
  - Defensive: missing sections return empty lists, not exceptions
  - Strictly typed raw containers (dataclasses, strings only)
  - No business logic - that belongs in the normalizer
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup, Tag


def _bs4() -> type[BeautifulSoup]:
    """Lazy import to keep top-level import cost zero."""
    from bs4 import BeautifulSoup

    return BeautifulSoup


# ---------------------------------------------------------------------------
# Raw data containers (pre-normalisation - strings only)
# ---------------------------------------------------------------------------


@dataclass
class PrsRawAttendanceSession:
    """Attendance data for one parliamentary session."""

    session_name: str = ""
    session_year: str = ""
    days_present: str = ""
    days_total: str = ""
    attendance_pct: str = ""


@dataclass
class PrsRawQuestion:
    """A single parliamentary question raised by an MP."""

    serial_no: str = ""
    question_type: str = ""  # "STARRED" | "UNSTARRED"
    question_number: str = ""
    question_date: str = ""
    session_name: str = ""
    subject: str = ""
    ministry: str = ""


@dataclass
class PrsRawDebate:
    """A participation in a parliamentary debate."""

    date: str = ""
    session_name: str = ""
    debate_type: str = ""
    subject: str = ""


@dataclass
class PrsRawBill:
    """A private member bill introduced by an MP."""

    bill_name: str = ""
    date_introduced: str = ""
    session_name: str = ""
    status: str = ""


@dataclass
class PrsRawMpProfile:
    """MP identity metadata scraped from PRS profile page."""

    prs_mp_id: int = 0
    name: str = ""
    constituency: str = ""
    state: str = ""
    party: str = ""
    lok_sabha_number: int = 0
    profile_url: str = ""


@dataclass
class PrsRawMpAttendance:
    """All attendance data for one MP."""

    prs_mp_id: int = 0
    attendance_url: str = ""
    sessions: list[PrsRawAttendanceSession] = field(default_factory=list)


@dataclass
class PrsRawMpActivity:
    """All legislative activity for one MP."""

    prs_mp_id: int = 0
    activity_url: str = ""
    questions: list[PrsRawQuestion] = field(default_factory=list)
    debates: list[PrsRawDebate] = field(default_factory=list)
    bills: list[PrsRawBill] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


class PrsProfileParser:
    """
    Parses an MP's profile landing page to extract identity metadata.

    PRS profile pages contain:
    - MP name (in <h1> or title)
    - Constituency, state, party (in info table or structured divs)
    """

    def parse(
        self, html: bytes, mp_id: int, profile_url: str, lok_sabha_number: int
    ) -> PrsRawMpProfile:
        """
        Parse a PRS MP profile page.

        Returns a PrsRawMpProfile with whatever data is extractable.
        Missing fields remain as empty strings - normalizer decides what to do.
        """
        bs4_cls = _bs4()
        soup: BeautifulSoup = bs4_cls(html, "lxml")

        profile = PrsRawMpProfile(
            prs_mp_id=mp_id,
            profile_url=profile_url,
            lok_sabha_number=lok_sabha_number,
        )

        # Extract MP name - try multiple selectors in order of reliability
        profile.name = self._extract_mp_name(soup)
        profile.constituency, profile.state, profile.party = self._extract_mp_info(soup)

        return profile

    def _extract_mp_name(self, soup: BeautifulSoup) -> str:
        """Try to extract MP name from profile page."""
        # PRS uses various layouts - try in order
        for selector in [
            "h1.mp-name",
            "h1",
            ".mptrack-name",
            ".mp-profile-name",
            "h2.name",
        ]:
            tag = soup.select_one(selector)
            if tag:
                name = tag.get_text(strip=True)
                if name and len(name) > 2:
                    return _clean_text(name)

        # Fallback: try page title
        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text(strip=True)
            # Remove site name suffix if present
            name = re.sub(r"\s*[|\-]\s*PRS.*$", "", title, flags=re.IGNORECASE).strip()
            if name and len(name) > 2:
                return _clean_text(name)

        return ""

    def _extract_mp_info(self, soup: BeautifulSoup) -> tuple[str, str, str]:
        """Extract constituency, state, and party from profile page."""
        constituency = ""
        state = ""
        party = ""

        # PRS has a profile-info section with key-value pairs
        info_section = soup.select_one(".mp-info, .profile-info, .mp-details")
        if info_section:
            text = info_section.get_text(" ", strip=True)
            constituency = _extract_after_label(text, "Constituency")
            state = _extract_after_label(text, "State")
            party = _extract_after_label(text, "Party")

        # Fallback: try structured divs/spans
        if not constituency:
            for tag in soup.select(".constituency, [data-constituency]"):
                constituency = tag.get_text(strip=True)
                if constituency:
                    break

        return constituency, state, party


class PrsAttendanceParser:
    """
    Parses an MP's attendance page from prsindia.org.

    PRS attendance page structure (as of 2024):
      - A table with rows for each parliamentary session
      - Columns: Session | Days Present | Days in Session | Attendance %
      - May also have a summary div with total stats
    """

    def parse(
        self, html: bytes, mp_id: int, attendance_url: str
    ) -> PrsRawMpAttendance:
        """
        Parse PRS attendance HTML into PrsRawMpAttendance.

        Defensive: returns empty sessions list if table not found.
        """
        bs4_cls = _bs4()
        soup: BeautifulSoup = bs4_cls(html, "lxml")

        result = PrsRawMpAttendance(
            prs_mp_id=mp_id,
            attendance_url=attendance_url,
        )

        result.sessions = self._extract_sessions(soup)
        return result

    def _extract_sessions(self, soup: BeautifulSoup) -> list[PrsRawAttendanceSession]:
        """
        Extract session-level attendance from the attendance table.

        PRS table headers (approximate): Session | Days Present | Total Days | %
        """
        sessions: list[PrsRawAttendanceSession] = []

        # Find the attendance table - PRS uses class="views-table" or similar
        table = self._find_attendance_table(soup)
        if table is None:
            return sessions

        from bs4 import Tag as BsTag

        rows = table.find_all("tr")
        header_cols = self._parse_header(rows)

        for row in rows[1:]:  # skip header row
            if not isinstance(row, BsTag):
                continue
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue

            session = self._parse_session_row(cells, header_cols)
            if session:
                sessions.append(session)

        return sessions

    def _find_attendance_table(self, soup: BeautifulSoup) -> Tag | None:
        """
        Locate the attendance table in the PRS page.

        PRS uses multiple possible class names across different page versions.
        """
        from bs4 import Tag as BsTag

        for selector in [
            "table.views-table",
            "table.attendance-table",
            "table.mp-attendance",
            "table",
        ]:
            table = soup.select_one(selector)
            if table and isinstance(table, BsTag):
                # Validate: should have at least one row with attendance-looking data
                rows = table.find_all("tr")
                if len(rows) >= 2:
                    return table  # type: ignore[return-value]

        return None

    def _parse_header(self, rows: list[Tag]) -> dict[str, int]:
        """
        Parse the header row to determine column indices.

        Returns dict mapping normalized column names to column indices.
        """
        from bs4 import Tag as BsTag

        if not rows:
            return {}

        header_row = rows[0]
        if not isinstance(header_row, BsTag):
            return {}

        headers: dict[str, int] = {}
        for i, th in enumerate(header_row.find_all(["th", "td"])):
            if isinstance(th, BsTag):
                text = th.get_text(strip=True).lower()
                if "session" in text:
                    headers["session"] = i
                elif "present" in text:
                    headers["days_present"] = i
                elif "total" in text or "days in" in text or "sitting" in text:
                    headers["days_total"] = i
                elif "%" in text or "percent" in text or "attendance" in text:
                    headers["attendance_pct"] = i

        # Fallback defaults if headers not recognized
        if "session" not in headers:
            headers["session"] = 0
        if "days_present" not in headers:
            headers["days_present"] = 1
        if "days_total" not in headers:
            headers["days_total"] = 2
        if "attendance_pct" not in headers:
            headers["attendance_pct"] = 3

        return headers

    def _parse_session_row(
        self, cells: list[Tag], header_cols: dict[str, int]
    ) -> PrsRawAttendanceSession | None:
        """Parse a single attendance table row into PrsRawAttendanceSession."""
        from bs4 import Tag as BsTag

        def cell_text(idx: int, row_cells: list[Tag] = cells) -> str:
            if idx < len(row_cells) and isinstance(row_cells[idx], BsTag):
                return row_cells[idx].get_text(strip=True)
            return ""

        session_raw = cell_text(header_cols.get("session", 0))
        if not session_raw:
            return None

        session_name, session_year = _parse_session_name(session_raw)

        return PrsRawAttendanceSession(
            session_name=session_name,
            session_year=session_year,
            days_present=cell_text(header_cols.get("days_present", 1)),
            days_total=cell_text(header_cols.get("days_total", 2)),
            attendance_pct=cell_text(header_cols.get("attendance_pct", 3)),
        )


class PrsActivityParser:
    """
    Parses an MP's legislative activity page from prsindia.org.

    PRS activity page contains multiple sections:
    - Starred Questions asked
    - Unstarred Questions asked
    - Debates participated in
    - Private Member Bills introduced
    """

    def parse(self, html: bytes, mp_id: int, activity_url: str) -> PrsRawMpActivity:
        """
        Parse PRS activity HTML into PrsRawMpActivity.

        Defensive: missing sections return empty lists.
        """
        bs4_cls = _bs4()
        soup: BeautifulSoup = bs4_cls(html, "lxml")

        result = PrsRawMpActivity(
            prs_mp_id=mp_id,
            activity_url=activity_url,
        )

        result.questions = self._extract_questions(soup)
        result.debates = self._extract_debates(soup)
        result.bills = self._extract_bills(soup)

        return result

    def _extract_questions(self, soup: BeautifulSoup) -> list[PrsRawQuestion]:
        """
        Extract parliamentary questions (starred and unstarred).

        PRS lists questions in a single table, often with a "Type" column
        indicating Starred (S) or Unstarred (U).
        """
        questions: list[PrsRawQuestion] = []

        from bs4 import Tag as BsTag

        # Find questions table - typically has columns: No | Type | Date | Subject | Ministry
        tables = soup.find_all("table")
        for table in tables:
            if not isinstance(table, BsTag):
                continue
            caption = table.find("caption")
            table_text = table.get_text(" ", strip=True).lower()
            caption_text = caption.get_text(strip=True).lower() if caption else ""

            # Identify question tables by caption or column headers
            if any(
                kw in caption_text or kw in table_text[:200]
                for kw in ["question", "starred", "unstarred"]
            ):
                questions.extend(self._parse_question_table(table))

        return questions

    def _parse_question_table(self, table: Tag) -> list[PrsRawQuestion]:
        """Parse a single questions table."""
        from bs4 import Tag as BsTag

        questions: list[PrsRawQuestion] = []
        rows = table.find_all("tr")
        if len(rows) < 2:
            return questions

        header_cols = self._parse_question_header(rows[0])

        for row in rows[1:]:
            if not isinstance(row, BsTag):
                continue
            row_cells = row.find_all(["td", "th"])
            if len(row_cells) < 2:
                continue

            def cell(idx: int, rc: list[Tag] = row_cells) -> str:
                if idx < len(rc) and isinstance(rc[idx], BsTag):
                    return _clean_text(rc[idx].get_text(strip=True))
                return ""

            q_type_raw = cell(header_cols.get("type", 1))
            # Normalize question type
            if q_type_raw.upper().startswith("S") and not q_type_raw.upper().startswith("UN"):
                q_type = "STARRED"
            elif q_type_raw.upper().startswith("U") or "unstarred" in q_type_raw.lower():
                q_type = "UNSTARRED"
            else:
                q_type = "UNSTARRED"

            question = PrsRawQuestion(
                serial_no=cell(header_cols.get("serial_no", 0)),
                question_type=q_type,
                question_number=cell(header_cols.get("question_number", 2)),
                question_date=cell(header_cols.get("date", 3)),
                session_name=cell(header_cols.get("session", -1)) if "session" in header_cols else "",
                subject=cell(header_cols.get("subject", 4)),
                ministry=cell(header_cols.get("ministry", 5)),
            )
            if question.subject or question.question_number:
                questions.append(question)

        return questions

    def _parse_question_header(self, header_row: Tag) -> dict[str, int]:
        """Parse question table header row."""
        from bs4 import Tag as BsTag

        headers: dict[str, int] = {}
        if not isinstance(header_row, BsTag):
            return headers

        for i, th in enumerate(header_row.find_all(["th", "td"])):
            if not isinstance(th, BsTag):
                continue
            text = th.get_text(strip=True).lower()
            if text in ("sl", "no", "sno", "s.no", "sr", "#"):
                headers["serial_no"] = i
            elif "type" in text:
                headers["type"] = i
            elif "question no" in text or "q.no" in text or "qno" in text:
                headers["question_number"] = i
            elif "date" in text:
                headers["date"] = i
            elif "session" in text:
                headers["session"] = i
            elif "subject" in text or "title" in text:
                headers["subject"] = i
            elif "ministry" in text or "department" in text:
                headers["ministry"] = i

        return headers

    def _extract_debates(self, soup: BeautifulSoup) -> list[PrsRawDebate]:
        """Extract debate participations."""
        debates: list[PrsRawDebate] = []

        from bs4 import Tag as BsTag

        tables = soup.find_all("table")
        for table in tables:
            if not isinstance(table, BsTag):
                continue
            caption = table.find("caption")
            table_text = table.get_text(" ", strip=True).lower()
            caption_text = caption.get_text(strip=True).lower() if caption else ""

            if any(
                kw in caption_text or kw in table_text[:200]
                for kw in ["debate", "discussion", "zero hour", "calling attention"]
            ):
                debates.extend(self._parse_debate_table(table))

        return debates

    def _parse_debate_table(self, table: Tag) -> list[PrsRawDebate]:
        """Parse a single debate table."""
        from bs4 import Tag as BsTag

        debates: list[PrsRawDebate] = []
        rows = table.find_all("tr")
        if len(rows) < 2:
            return debates

        for row in rows[1:]:
            if not isinstance(row, BsTag):
                continue
            row_cells = row.find_all(["td", "th"])
            if len(row_cells) < 2:
                continue

            def cell(idx: int, rc: list[Tag] = row_cells) -> str:
                if idx < len(rc) and isinstance(rc[idx], BsTag):
                    return _clean_text(rc[idx].get_text(strip=True))
                return ""

            debate = PrsRawDebate(
                date=cell(0),
                session_name=cell(1) if len(row_cells) > 2 else "",
                debate_type=cell(2) if len(row_cells) > 3 else "",
                subject=cell(3) if len(row_cells) > 3 else cell(1),
            )
            if debate.subject or debate.date:
                debates.append(debate)

        return debates

    def _extract_bills(self, soup: BeautifulSoup) -> list[PrsRawBill]:
        """Extract private member bills introduced."""
        bills: list[PrsRawBill] = []

        from bs4 import Tag as BsTag

        tables = soup.find_all("table")
        for table in tables:
            if not isinstance(table, BsTag):
                continue
            caption = table.find("caption")
            table_text = table.get_text(" ", strip=True).lower()
            caption_text = caption.get_text(strip=True).lower() if caption else ""

            if any(
                kw in caption_text or kw in table_text[:200]
                for kw in ["bill", "private member"]
            ):
                bills.extend(self._parse_bill_table(table))

        return bills

    def _parse_bill_table(self, table: Tag) -> list[PrsRawBill]:
        """Parse a single bills table."""
        from bs4 import Tag as BsTag

        bills: list[PrsRawBill] = []
        rows = table.find_all("tr")
        if len(rows) < 2:
            return bills

        for row in rows[1:]:
            if not isinstance(row, BsTag):
                continue
            row_cells = row.find_all(["td", "th"])
            if len(row_cells) < 2:
                continue

            def cell(idx: int, rc: list[Tag] = row_cells) -> str:
                if idx < len(rc) and isinstance(rc[idx], BsTag):
                    return _clean_text(rc[idx].get_text(strip=True))
                return ""

            bill = PrsRawBill(
                bill_name=cell(0),
                date_introduced=cell(1),
                session_name=cell(2) if len(row_cells) > 3 else "",
                status=cell(3) if len(row_cells) > 3 else cell(2),
            )
            if bill.bill_name:
                bills.append(bill)

        return bills


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _clean_text(text: str) -> str:
    """Normalize whitespace in extracted text."""
    return " ".join(text.split())


def _extract_after_label(text: str, label: str) -> str:
    """
    Extract the value after a label in a text blob.

    E.g.: "Constituency: Varanasi State: UP" -> _extract_after_label(text, "Constituency") -> "Varanasi"
    """
    pattern = re.compile(rf"{label}\s*[:\-]\s*([^\n|:]+)", re.IGNORECASE)
    match = pattern.search(text)
    if match:
        return match.group(1).strip()
    return ""


def _parse_session_name(raw: str) -> tuple[str, str]:
    """
    Parse a PRS session name string into (session_name, session_year).

    Common formats:
      "Budget Session 2024"       -> ("Budget Session", "2024")
      "Winter Session 2023-24"    -> ("Winter Session", "2023")
      "Monsoon Session 2023"      -> ("Monsoon Session", "2023")
      "Special Session Sep 2023"  -> ("Special Session", "2023")
    """
    raw = _clean_text(raw)

    # Extract year - last 4-digit sequence or 4+2 range
    year_match = re.search(r"(\d{4})(?:-\d{2})?", raw)
    year = year_match.group(1) if year_match else ""

    # Session name - remove year from string
    session_name = re.sub(r"\d{4}(-\d{2})?", "", raw).strip(" -,")
    session_name = _clean_text(session_name)

    return session_name, year
