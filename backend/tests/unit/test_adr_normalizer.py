"""
Unit tests for the ADR normalizer.

Pure function tests — no DB, no HTTP, no I/O of any kind.
Tests the logic that converts raw scraped strings into typed domain objects.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from netacheck.ingestion.adr.normalizer import (
    AdrNormalizer,
    NormalisedCandidate,
    _classify_severity,
    _clean_name,
    _make_slug,
    _normalise_asset_row,
    _parse_inr,
    _parse_party,
)
from netacheck.ingestion.adr.parser import AdrRawAsset, AdrRawCandidate, AdrRawCriminalCase
from netacheck.models.assets import AssetCategory, AssetOwnership
from netacheck.models.criminal import CaseStatus, Severity


# ---------------------------------------------------------------------------
# _clean_name
# ---------------------------------------------------------------------------


class TestCleanName:
    def test_strips_dr_prefix(self) -> None:
        assert _clean_name("DR. RAJESH KUMAR") == "Rajesh Kumar"

    def test_strips_shri_prefix(self) -> None:
        assert _clean_name("SHRI NARENDRA MODI") == "Narendra Modi"

    def test_strips_smt_prefix(self) -> None:
        assert _clean_name("SMT. PRIYA SHARMA") == "Priya Sharma"

    def test_strips_adv_prefix(self) -> None:
        assert _clean_name("ADV. AMIT SINGH") == "Amit Singh"

    def test_strips_col_prefix(self) -> None:
        assert _clean_name("COL. RAMESH VERMA") == "Ramesh Verma"

    def test_title_cases_result(self) -> None:
        result = _clean_name("PRAVEEN KHANDELWAL")
        assert result == "Praveen Khandelwal"

    def test_preserves_multi_word_name(self) -> None:
        result = _clean_name("RAHUL GANDHI")
        assert result == "Rahul Gandhi"

    def test_no_honorific_unchanged(self) -> None:
        result = _clean_name("SUMATHY T")
        assert result == "Sumathy T"


# ---------------------------------------------------------------------------
# _make_slug
# ---------------------------------------------------------------------------


class TestMakeSlug:
    def test_basic_slug_format(self) -> None:
        slug = _make_slug("Rahul Gandhi", "Wayanad")
        assert slug == "rahul-gandhi-wayanad"

    def test_slug_with_spaces_in_constituency(self) -> None:
        slug = _make_slug("Praveen Khandelwal", "Chandni Chowk")
        assert slug == "praveen-khandelwal-chandni-chowk"

    def test_slug_is_lowercase(self) -> None:
        slug = _make_slug("TEST NAME", "TEST PLACE")
        assert slug == slug.lower()

    def test_slug_has_no_special_chars(self) -> None:
        slug = _make_slug("Suresh K. Patel", "Delhi (NCT)")
        assert all(c.isalnum() or c == "-" for c in slug)

    def test_slug_uniqueness_by_constituency(self) -> None:
        slug1 = _make_slug("Ramesh Kumar", "Patna Sahib")
        slug2 = _make_slug("Ramesh Kumar", "Varanasi")
        assert slug1 != slug2


# ---------------------------------------------------------------------------
# _parse_inr
# ---------------------------------------------------------------------------


class TestParseInr:
    def test_lakh_notation(self) -> None:
        result = _parse_inr("Rs 1,28,280 1 Lacs+")
        assert result == Decimal("128280")

    def test_crore_notation(self) -> None:
        result = _parse_inr("Rs 96,63,649.83 96 Lacs+")
        assert result == Decimal("9663649.83")

    def test_plain_number(self) -> None:
        result = _parse_inr("14,40,08,066")
        assert result == Decimal("144008066")

    def test_nil_returns_none(self) -> None:
        assert _parse_inr("Nil") is None

    def test_empty_string_returns_none(self) -> None:
        assert _parse_inr("") is None

    def test_zero_string_returns_none(self) -> None:
        assert _parse_inr("0") is None

    def test_dash_returns_none(self) -> None:
        assert _parse_inr("-") is None

    def test_nbsp_stripped(self) -> None:
        result = _parse_inr("Rs\xa01,00,000")
        assert result == Decimal("100000")

    def test_tilde_stripped(self) -> None:
        result = _parse_inr("~50,000")
        assert result == Decimal("50000")

    def test_decimal_value(self) -> None:
        result = _parse_inr("Rs 1,50,000.50")
        assert result == Decimal("150000.50")


# ---------------------------------------------------------------------------
# _parse_party
# ---------------------------------------------------------------------------


class TestParseParty:
    def test_known_bjp(self) -> None:
        abbr, full = _parse_party("BJP")
        assert abbr == "BJP"
        assert "Bharatiya Janata Party" in full

    def test_known_inc(self) -> None:
        abbr, full = _parse_party("INC")
        assert full == "Indian National Congress"

    def test_known_aap(self) -> None:
        abbr, full = _parse_party("AAP")
        assert full == "Aam Aadmi Party"

    def test_known_ind(self) -> None:
        abbr, full = _parse_party("IND")
        assert full == "Independent"

    def test_empty_returns_independent(self) -> None:
        abbr, full = _parse_party("")
        assert abbr == "IND"
        assert full == "Independent"

    def test_unknown_long_name_derives_abbreviation(self) -> None:
        abbr, full = _parse_party("Janata Dal United")
        assert len(abbr) <= 6
        assert full == "Janata Dal United"

    def test_unknown_short_caps_treated_as_abbreviation(self) -> None:
        abbr, full = _parse_party("DMK")
        assert abbr == "DMK"


# ---------------------------------------------------------------------------
# _classify_severity
# ---------------------------------------------------------------------------


class TestClassifySeverity:
    def test_heinous_for_ipc_302(self) -> None:
        result = _classify_severity("302", "")
        assert result == Severity.HEINOUS

    def test_heinous_for_ipc_376(self) -> None:
        result = _classify_severity("376", "")
        assert result == Severity.HEINOUS

    def test_heinous_for_ipc_307(self) -> None:
        result = _classify_severity("307", "")
        assert result == Severity.HEINOUS

    def test_serious_for_ndps(self) -> None:
        result = _classify_severity("", "NDPS Act section 21")
        assert result == Severity.SERIOUS

    def test_serious_for_pocso(self) -> None:
        result = _classify_severity("", "POCSO Act")
        assert result == Severity.SERIOUS

    def test_minor_for_ordinary_ipc(self) -> None:
        result = _classify_severity("420", "")
        assert result == Severity.MINOR

    def test_unknown_for_empty(self) -> None:
        result = _classify_severity("", "")
        assert result == Severity.UNKNOWN


# ---------------------------------------------------------------------------
# _normalise_asset_row
# ---------------------------------------------------------------------------


class TestNormaliseAssetRow:
    def _make_raw(self, **kwargs: str) -> AdrRawAsset:
        defaults = {
            "serial_no": "1",
            "description": "Cash in hand",
            "self_value": "",
            "spouse_value": "",
            "huf_value": "",
            "dependent1_value": "",
            "dependent2_value": "",
            "dependent3_value": "",
            "total_value": "",
            "asset_type": "movable",
        }
        defaults.update(kwargs)
        return AdrRawAsset(**defaults)

    def test_expands_self_value_to_one_record(self) -> None:
        raw = self._make_raw(self_value="Rs 1,00,000")
        results = _normalise_asset_row(raw, "movable")
        assert len(results) == 1
        assert results[0].ownership == AssetOwnership.SELF
        assert results[0].value_inr == Decimal("100000")

    def test_expands_spouse_value_to_separate_record(self) -> None:
        raw = self._make_raw(self_value="Rs 1,00,000", spouse_value="Rs 50,000")
        results = _normalise_asset_row(raw, "movable")
        assert len(results) == 2
        ownerships = {r.ownership for r in results}
        assert AssetOwnership.SELF in ownerships
        assert AssetOwnership.SPOUSE in ownerships

    def test_nil_values_not_expanded(self) -> None:
        raw = self._make_raw(self_value="Nil", spouse_value="", total_value="Nil")
        results = _normalise_asset_row(raw, "movable")
        assert len(results) == 0

    def test_falls_back_to_total_when_per_owner_nil(self) -> None:
        raw = self._make_raw(total_value="Rs 5,00,000")
        results = _normalise_asset_row(raw, "movable")
        assert len(results) == 1
        assert results[0].value_inr == Decimal("500000")

    def test_liability_type_maps_to_liability_category(self) -> None:
        raw = self._make_raw(total_value="Rs 1,00,000")
        results = _normalise_asset_row(raw, "liability")
        assert results[0].category == AssetCategory.LIABILITY

    def test_immovable_maps_to_immovable_category(self) -> None:
        raw = self._make_raw(description="Agricultural land", total_value="Rs 10,00,000")
        results = _normalise_asset_row(raw, "immovable")
        assert results[0].category == AssetCategory.IMMOVABLE


# ---------------------------------------------------------------------------
# AdrNormalizer.normalise
# ---------------------------------------------------------------------------


class TestAdrNormalizer:
    def _make_raw(self, **kwargs: object) -> AdrRawCandidate:
        defaults = {
            "candidate_id": 42,
            "source_url": "https://myneta.info/loksabha2024/candidate.php?candidate_id=42",
            "name": "PRAVEEN KHANDELWAL",
            "party": "BJP",
            "constituency": "CHANDNI CHOWK",
            "state": "DELHI (NCT)",
            "age": "61",
            "won": True,
            "photo_url": "",
            "self_profession": "Business",
            "spouse_profession": "Homemaker",
            "total_assets_inr": "Rs 10,00,00,000",
            "total_liabilities_inr": "Nil",
            "education": "Graduate",
            "criminal_cases": [],
            "movable_assets": [],
            "immovable_assets": [],
            "liabilities": [],
        }
        defaults.update(kwargs)
        return AdrRawCandidate(**defaults)  # type: ignore[arg-type]

    def test_returns_none_for_empty_name(self) -> None:
        raw = self._make_raw(name="", constituency="DELHI")
        result = AdrNormalizer().normalise(raw)
        assert result is None

    def test_returns_none_for_empty_constituency(self) -> None:
        raw = self._make_raw(constituency="")
        result = AdrNormalizer().normalise(raw)
        assert result is None

    def test_name_cleaned(self) -> None:
        raw = self._make_raw(name="DR. PRAVEEN KHANDELWAL")
        result = AdrNormalizer().normalise(raw)
        assert result is not None
        assert result.name == "Praveen Khandelwal"

    def test_slug_generated(self) -> None:
        result = AdrNormalizer().normalise(self._make_raw())
        assert result is not None
        assert result.slug == "praveen-khandelwal-chandni-chowk"

    def test_party_resolved(self) -> None:
        result = AdrNormalizer().normalise(self._make_raw())
        assert result is not None
        assert result.party_abbreviation == "BJP"
        assert result.party_name == "Bharatiya Janata Party"

    def test_won_flag_preserved(self) -> None:
        result = AdrNormalizer().normalise(self._make_raw(won=True))
        assert result is not None
        assert result.won is True

    def test_assets_normalised(self) -> None:
        asset = AdrRawAsset(
            serial_no="1",
            description="Cash in hand",
            self_value="Rs 1,00,000",
            spouse_value="",
            huf_value="",
            dependent1_value="",
            dependent2_value="",
            dependent3_value="",
            total_value="Rs 1,00,000",
            asset_type="movable",
        )
        raw = self._make_raw(movable_assets=[asset])
        result = AdrNormalizer().normalise(raw)
        assert result is not None
        assert len(result.assets) >= 1

    def test_criminal_cases_normalised(self) -> None:
        case = AdrRawCriminalCase(
            case_type="pending",
            ipc_sections="302",
            other_acts="",
            charges_framed="Yes",
            fir_no="FIR-001",
            case_no="CC-001",
            court="Sessions Court Delhi",
        )
        raw = self._make_raw(criminal_cases=[case])
        result = AdrNormalizer().normalise(raw)
        assert result is not None
        assert len(result.criminal_cases) == 1
        assert result.criminal_cases[0].status == CaseStatus.PENDING
        assert result.criminal_cases[0].severity == Severity.HEINOUS
        assert result.criminal_cases[0].charges_framed is True

    def test_total_assets_parsed(self) -> None:
        result = AdrNormalizer().normalise(self._make_raw(total_assets_inr="Rs 10,00,00,000"))
        assert result is not None
        assert result.total_assets_inr == Decimal("100000000")

    def test_nil_liabilities_returns_none(self) -> None:
        result = AdrNormalizer().normalise(self._make_raw(total_liabilities_inr="Nil"))
        assert result is not None
        assert result.total_liabilities_inr is None
