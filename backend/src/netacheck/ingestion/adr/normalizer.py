"""
ADR normalizer — converts AdrRawCandidate into domain model instances.

Responsibilities:
  - Parse raw INR strings → Decimal
  - Map string enums → Python enums
  - Generate stable politician slugs
  - Build all ORM-ready objects (unsaved — the writer saves them)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from slugify import slugify

from netacheck.models.assets import AssetCategory, AssetOwnership
from netacheck.models.criminal import CaseStatus, Severity

if TYPE_CHECKING:
    from netacheck.ingestion.adr.parser import AdrRawAsset, AdrRawCandidate, AdrRawCriminalCase

# ---------------------------------------------------------------------------
# Normalised output containers (plain dataclasses — no SQLAlchemy yet)
# ---------------------------------------------------------------------------


@dataclass
class NormalisedCriminalCase:
    case_type: str  # "pending" | "convicted"
    fir_no: str | None
    case_no: str | None
    court: str | None
    section_of_law: str | None
    offence_description: str | None
    status: CaseStatus
    severity: Severity
    charges_framed: bool


@dataclass
class NormalisedAsset:
    category: AssetCategory
    ownership: AssetOwnership
    description: str | None
    value_inr: Decimal | None
    raw_value_text: str
    location: str | None = None


@dataclass
class NormalisedCandidate:
    # Identity
    name: str
    slug: str
    party_name: str
    party_abbreviation: str
    constituency_name: str
    state_name: str
    age: int | None
    won: bool
    photo_url: str | None
    source_url: str
    candidate_id: int
    election_year: int = 2024
    election_date: date = field(default_factory=lambda: date(2024, 4, 19))

    # Financial summary
    total_assets_inr: Decimal | None = None
    total_liabilities_inr: Decimal | None = None

    # Sub-records
    criminal_cases: list[NormalisedCriminalCase] = field(default_factory=list)
    assets: list[NormalisedAsset] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Normalizer
# ---------------------------------------------------------------------------


class AdrNormalizer:
    """Converts AdrRawCandidate → NormalisedCandidate."""

    def normalise(self, raw: AdrRawCandidate) -> NormalisedCandidate | None:
        """
        Returns None if the raw data is too sparse to be useful
        (e.g., completely empty page — deleted candidate).
        """
        if not raw.name or not raw.constituency:
            return None

        name = _clean_name(raw.name)
        slug = _make_slug(name, raw.constituency)

        party_abbr, party_full = _parse_party(raw.party)

        assets: list[NormalisedAsset] = []
        for a in raw.movable_assets:
            assets.extend(_normalise_asset_row(a, "movable"))
        for a in raw.immovable_assets:
            assets.extend(_normalise_asset_row(a, "immovable"))
        for a in raw.liabilities:
            assets.extend(_normalise_asset_row(a, "liability"))

        criminal_cases = [_normalise_case(c) for c in raw.criminal_cases]

        return NormalisedCandidate(
            name=name,
            slug=slug,
            party_name=party_full,
            party_abbreviation=party_abbr,
            constituency_name=raw.constituency,
            state_name=raw.state,
            age=_parse_int(raw.age),
            won=raw.won,
            photo_url=raw.photo_url or None,
            source_url=raw.source_url,
            candidate_id=raw.candidate_id,
            total_assets_inr=_parse_inr(raw.total_assets_inr),
            total_liabilities_inr=_parse_inr(raw.total_liabilities_inr),
            criminal_cases=criminal_cases,
            assets=assets,
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _clean_name(name: str) -> str:
    """Title-case, strip honorifics like DR., SHRI, SMT., COL., etc."""
    honorifics = r"^(DR\.?|SHRI|SMT\.?|SH\.?|ADV\.?|COL\.?|LT\.?|CAPT\.?|PROF\.?)\s+"
    name = re.sub(honorifics, "", name.upper(), flags=re.IGNORECASE).strip()
    return name.title()


def _make_slug(name: str, constituency: str) -> str:
    """
    Stable slug: slugify(name) + '-' + slugify(constituency).
    Ensures uniqueness even for common names (e.g., 'Ramesh Kumar').
    """
    return f"{slugify(name)}-{slugify(constituency)}"


def _parse_party(raw_party: str) -> tuple[str, str]:
    """
    Returns (abbreviation, full_name).

    MyNeta uses abbreviations like 'BJP', 'INC', 'IND'.
    If it looks like an abbreviation (≤6 chars, all caps/dots), treat it as one.
    """
    raw_party = raw_party.strip()
    if not raw_party:
        return ("IND", "Independent")

    # Known mappings
    known: dict[str, str] = {
        "BJP": "Bharatiya Janata Party",
        "INC": "Indian National Congress",
        "AAP": "Aam Aadmi Party",
        "BSP": "Bahujan Samaj Party",
        "SP": "Samajwadi Party",
        "NCP": "Nationalist Congress Party",
        "SS": "Shiv Sena",
        "TMC": "All India Trinamool Congress",
        "CPI(M)": "Communist Party of India (Marxist)",
        "CPI": "Communist Party of India",
        "TDP": "Telugu Desam Party",
        "JDU": "Janata Dal (United)",
        "RJD": "Rashtriya Janata Dal",
        "IND": "Independent",
        "NOTA": "None of the Above",
    }

    upper = raw_party.upper()
    if upper in known:
        return (raw_party, known[upper])

    # Looks like abbreviation if all uppercase and short
    if len(raw_party) <= 10 and re.match(r"^[A-Z()\-\.]+$", upper):
        return (raw_party, raw_party)

    # Longer name — derive abbreviation from initials
    words = raw_party.split()
    abbr = "".join(w[0].upper() for w in words if w and w[0].isalpha())[:6]
    return (abbr or raw_party[:6], raw_party)


def _parse_inr(raw: str) -> Decimal | None:
    """
    Parse MyNeta INR strings like:
      'Rs 1,28,280 1 Lacs+'    → Decimal('128280')
      'Rs 96,63,649.83 96 Lacs+' → Decimal('9663649.83')
      '14,40,08,066'            → Decimal('1440808066') [sic — Indian notation]
      'Nil'                     → None

    Strategy: strip Rs/nbsp/~ then extract the first contiguous number token
    (digits, commas, decimal points) before any space.
    """
    if not raw:
        return None
    # Strip currency symbol and whitespace noise
    cleaned = (
        raw.replace("Rs", "").replace("&nbsp;", "").replace("\xa0", " ").replace("~", "").strip()
    )
    if cleaned.lower() in ("nil", "0", "-", ""):
        return None
    # Extract the first "number" token — digits, commas, dots only
    m = re.match(r"^([0-9,\.]+)", cleaned)
    if not m:
        return None
    num_str = m.group(1).replace(",", "")
    try:
        val = Decimal(num_str)
        return val if val > 0 else None
    except InvalidOperation:
        return None


def _parse_int(raw: str) -> int | None:
    m = re.search(r"\d+", raw)
    return int(m.group()) if m else None


_SERIOUS_SECTIONS = {
    "302",
    "304",
    "307",
    "308",
    "376",
    "377",
    "395",
    "396",
    "397",
    "398",
    "399",
    "400",
    "436",
    "449",
    "450",
    "120B",
}

_SERIOUS_ACTS = [
    "prevention of corruption",
    "ndps",
    "pocso",
    "arms act",
    "explosives",
    "terrorism",
]


def _classify_severity(ipc: str, other: str) -> Severity:
    sections = re.findall(r"\d+[A-Z]?", ipc)
    for s in sections:
        if s in _SERIOUS_SECTIONS:
            return Severity.HEINOUS
    combined = (ipc + " " + other).lower()
    for act in _SERIOUS_ACTS:
        if act in combined:
            return Severity.SERIOUS
    if ipc.strip():
        return Severity.MINOR
    return Severity.UNKNOWN


def _normalise_case(raw: AdrRawCriminalCase) -> NormalisedCriminalCase:
    status = CaseStatus.PENDING if raw.case_type == "pending" else CaseStatus.CONVICTED
    severity = _classify_severity(raw.ipc_sections, raw.other_acts)

    section_parts = [raw.ipc_sections, raw.other_acts]
    section_of_law = " | ".join(p for p in section_parts if p.strip()) or None

    charges_framed = raw.charges_framed.strip().upper() in ("YES", "Y", "TRUE", "1")

    return NormalisedCriminalCase(
        case_type=raw.case_type,
        fir_no=raw.fir_no or None,
        case_no=raw.case_no or None,
        court=raw.court or None,
        section_of_law=section_of_law,
        offence_description=raw.other_acts or None,
        status=status,
        severity=severity,
        charges_framed=charges_framed,
    )


# Mapping from description keywords → AssetCategory
_MOVABLE_CATEGORY_MAP: list[tuple[str, AssetCategory]] = [
    ("cash", AssetCategory.MOVABLE),
    ("deposit", AssetCategory.FINANCIAL),
    ("bank", AssetCategory.FINANCIAL),
    ("bond", AssetCategory.FINANCIAL),
    ("share", AssetCategory.FINANCIAL),
    ("nss", AssetCategory.FINANCIAL),
    ("postal", AssetCategory.FINANCIAL),
    ("lic", AssetCategory.FINANCIAL),
    ("insurance", AssetCategory.FINANCIAL),
    ("loan", AssetCategory.LIABILITY),
    ("vehicle", AssetCategory.MOVABLE),
    ("motor", AssetCategory.MOVABLE),
    ("jewel", AssetCategory.MOVABLE),
    ("gold", AssetCategory.MOVABLE),
    ("silver", AssetCategory.MOVABLE),
]

_IMMOVABLE_CATEGORY_MAP: list[tuple[str, AssetCategory]] = [
    ("agricultural", AssetCategory.IMMOVABLE),
    ("land", AssetCategory.IMMOVABLE),
    ("building", AssetCategory.IMMOVABLE),
    ("residential", AssetCategory.IMMOVABLE),
    ("commercial", AssetCategory.IMMOVABLE),
    ("flat", AssetCategory.IMMOVABLE),
    ("house", AssetCategory.IMMOVABLE),
    ("plot", AssetCategory.IMMOVABLE),
]

_OWNERSHIP_MAP: dict[str, AssetOwnership] = {
    "self": AssetOwnership.SELF,
    "spouse": AssetOwnership.SPOUSE,
    "huf": AssetOwnership.HUF,
    "dependent": AssetOwnership.DEPENDENT,
}


def _guess_category(description: str, asset_type: str) -> AssetCategory:
    desc_lower = description.lower()
    if asset_type == "liability":
        return AssetCategory.LIABILITY
    table = _IMMOVABLE_CATEGORY_MAP if asset_type == "immovable" else _MOVABLE_CATEGORY_MAP
    for keyword, cat in table:
        if keyword in desc_lower:
            return cat
    return AssetCategory.MOVABLE if asset_type == "movable" else AssetCategory.IMMOVABLE


def _normalise_asset_row(raw: AdrRawAsset, asset_type: str) -> list[NormalisedAsset]:
    """
    Each asset row may have values for multiple owners (self, spouse, huf, dependents).
    We expand them into individual NormalisedAsset records.

    Note: Some candidates' pages render per-owner values as <img> tags (a bar chart image)
    rather than text. In that case, we fall back to the row total column.
    """
    category = _guess_category(raw.description, asset_type)
    results: list[NormalisedAsset] = []

    ownership_values = [
        (AssetOwnership.SELF, raw.self_value),
        (AssetOwnership.SPOUSE, raw.spouse_value),
        (AssetOwnership.HUF, raw.huf_value),
        (AssetOwnership.DEPENDENT, raw.dependent1_value),
        (AssetOwnership.DEPENDENT, raw.dependent2_value),
        (AssetOwnership.DEPENDENT, raw.dependent3_value),
    ]

    for ownership, raw_val in ownership_values:
        if not raw_val or raw_val.lower() in ("nil", "0", "-", ""):
            continue
        value = _parse_inr(raw_val)
        if value is None or value == 0:
            continue

        results.append(
            NormalisedAsset(
                category=category,
                ownership=ownership,
                description=raw.description or None,
                value_inr=value,
                raw_value_text=raw_val,
            )
        )

    # If no per-owner breakdown was parseable (e.g. values are images), use the total column.
    # This is the common case for large/prominent candidates on myneta.info.
    if not results:
        total_raw = raw.total_value.strip() if raw.total_value else ""
        if total_raw and total_raw.lower() not in ("nil", "0", "-", ""):
            value = _parse_inr(total_raw)
            if value and value > 0:
                results.append(
                    NormalisedAsset(
                        category=category,
                        ownership=AssetOwnership.SELF,
                        description=raw.description or None,
                        value_inr=value,
                        raw_value_text=total_raw,
                    )
                )

    return results
