"""
Unit tests for the ADR HTML parser.

Uses real HTML fixtures saved from myneta.info (committed, no network needed).
Tests that the parser correctly extracts structured data from raw HTML.

Fixtures:
  - candidate_winner_with_cases.html: Praveen Khandelwal (BJP, Chandni Chowk) — winner with assets
  - candidate_winner_clean.html: Sumathy T (DMK, Chennai South) — winner
  - candidate_sparse.html: candidate_id=9999 (Page Not Found)
"""

from __future__ import annotations

from pathlib import Path

from netacheck.ingestion.adr.parser import AdrParser

FIXTURES = Path(__file__).parent.parent / "fixtures" / "adr_html"


def _load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class TestParserIdentity:
    """Parser correctly extracts candidate identity from real pages."""

    def test_winner_with_cases_name(self) -> None:
        html = _load("candidate_winner_with_cases.html")
        raw = AdrParser().parse(html, candidate_id=7896, source_url="https://myneta.info/test")
        # Praveen Khandelwal — honorific may or may not be stripped at parse stage
        assert "KHANDELWAL" in raw.name.upper() or "khandelwal" in raw.name.lower()

    def test_winner_with_cases_party(self) -> None:
        html = _load("candidate_winner_with_cases.html")
        raw = AdrParser().parse(html, candidate_id=7896, source_url="https://myneta.info/test")
        assert "BJP" in raw.party.upper() or "Bharatiya" in raw.party

    def test_winner_with_cases_constituency(self) -> None:
        html = _load("candidate_winner_with_cases.html")
        raw = AdrParser().parse(html, candidate_id=7896, source_url="https://myneta.info/test")
        assert "CHANDNI CHOWK" in raw.constituency.upper()

    def test_winner_with_cases_state(self) -> None:
        html = _load("candidate_winner_with_cases.html")
        raw = AdrParser().parse(html, candidate_id=7896, source_url="https://myneta.info/test")
        assert "DELHI" in raw.state.upper()

    def test_winner_flag_is_true(self) -> None:
        html = _load("candidate_winner_with_cases.html")
        raw = AdrParser().parse(html, candidate_id=7896, source_url="https://myneta.info/test")
        assert raw.won is True

    def test_clean_page_name(self) -> None:
        html = _load("candidate_winner_clean.html")
        raw = AdrParser().parse(html, candidate_id=100, source_url="https://myneta.info/test")
        assert "SUMATHY" in raw.name.upper()

    def test_clean_page_party(self) -> None:
        html = _load("candidate_winner_clean.html")
        raw = AdrParser().parse(html, candidate_id=100, source_url="https://myneta.info/test")
        assert "DMK" in raw.party.upper()

    def test_clean_page_constituency(self) -> None:
        html = _load("candidate_winner_clean.html")
        raw = AdrParser().parse(html, candidate_id=100, source_url="https://myneta.info/test")
        assert "CHENNAI SOUTH" in raw.constituency.upper()

    def test_clean_page_state(self) -> None:
        html = _load("candidate_winner_clean.html")
        raw = AdrParser().parse(html, candidate_id=100, source_url="https://myneta.info/test")
        assert "TAMIL NADU" in raw.state.upper()

    def test_clean_page_winner_is_true(self) -> None:
        html = _load("candidate_winner_clean.html")
        raw = AdrParser().parse(html, candidate_id=100, source_url="https://myneta.info/test")
        assert raw.won is True

    def test_candidate_id_preserved(self) -> None:
        html = _load("candidate_winner_with_cases.html")
        raw = AdrParser().parse(html, candidate_id=7896, source_url="https://myneta.info/test")
        assert raw.candidate_id == 7896

    def test_source_url_preserved(self) -> None:
        url = "https://myneta.info/loksabha2024/candidate.php?candidate_id=7896"
        html = _load("candidate_winner_with_cases.html")
        raw = AdrParser().parse(html, candidate_id=7896, source_url=url)
        assert raw.source_url == url


class TestParserSparse:
    """Parser handles missing/empty data gracefully — no exceptions."""

    def test_sparse_page_does_not_raise(self) -> None:
        html = _load("candidate_sparse.html")
        raw = AdrParser().parse(html, candidate_id=9999, source_url="https://myneta.info/test")
        # Should return an AdrRawCandidate with mostly empty fields, no exception
        assert raw is not None

    def test_sparse_page_empty_criminal_cases(self) -> None:
        html = _load("candidate_sparse.html")
        raw = AdrParser().parse(html, candidate_id=9999, source_url="https://myneta.info/test")
        assert raw.criminal_cases == []

    def test_sparse_page_empty_movable_assets(self) -> None:
        html = _load("candidate_sparse.html")
        raw = AdrParser().parse(html, candidate_id=9999, source_url="https://myneta.info/test")
        assert raw.movable_assets == []

    def test_sparse_page_empty_immovable_assets(self) -> None:
        html = _load("candidate_sparse.html")
        raw = AdrParser().parse(html, candidate_id=9999, source_url="https://myneta.info/test")
        assert raw.immovable_assets == []


class TestParserAssets:
    """Parser extracts asset data from the movable/immovable asset tables."""

    def test_winner_with_cases_has_movable_assets(self) -> None:
        html = _load("candidate_winner_with_cases.html")
        raw = AdrParser().parse(html, candidate_id=7896, source_url="https://myneta.info/test")
        # Praveen Khandelwal (BJP) should have declared assets
        assert (
            len(raw.movable_assets) > 0
            or len(raw.immovable_assets) > 0
            or raw.total_assets_inr != ""
        )

    def test_clean_page_has_asset_data(self) -> None:
        html = _load("candidate_winner_clean.html")
        raw = AdrParser().parse(html, candidate_id=100, source_url="https://myneta.info/test")
        # Sumathy T (DMK) — should have some financial data
        has_data = (
            len(raw.movable_assets) > 0
            or len(raw.immovable_assets) > 0
            or raw.total_assets_inr not in ("", "Nil")
        )
        assert has_data

    def test_asset_description_not_empty(self) -> None:
        html = _load("candidate_winner_clean.html")
        raw = AdrParser().parse(html, candidate_id=100, source_url="https://myneta.info/test")
        all_assets = raw.movable_assets + raw.immovable_assets
        for asset in all_assets:
            # description should not be the word "total" — those rows are skipped
            assert "total" not in asset.description.lower()


class TestParserTotalAssets:
    """Parser extracts total assets and liabilities from the summary table."""

    def test_winner_has_total_assets_string(self) -> None:
        html = _load("candidate_winner_with_cases.html")
        raw = AdrParser().parse(html, candidate_id=7896, source_url="https://myneta.info/test")
        # Should have extracted *something* for total assets
        assert raw.total_assets_inr != ""

    def test_liabilities_field_present(self) -> None:
        html = _load("candidate_winner_with_cases.html")
        raw = AdrParser().parse(html, candidate_id=7896, source_url="https://myneta.info/test")
        # liabilities field exists (may be "Nil" or an amount)
        assert hasattr(raw, "total_liabilities_inr")
