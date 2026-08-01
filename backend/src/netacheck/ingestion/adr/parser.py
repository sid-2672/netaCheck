"""
ADR / MyNeta HTML parser.

Converts raw HTML bytes from candidate.php into structured AdrRawCandidate objects.
Uses BeautifulSoup4 + lxml for robust HTML parsing.

All raw string values are preserved so nothing is silently dropped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


def _bs4() -> "type[BeautifulSoup]":  # type: ignore[name-defined]  # noqa: F821
    """Lazy import to avoid top-level import cost."""
    from bs4 import BeautifulSoup  # type: ignore[import-untyped]
    return BeautifulSoup


# ---------------------------------------------------------------------------
# Raw data containers (pre-normalisation — strings only)
# ---------------------------------------------------------------------------


@dataclass
class AdrRawCriminalCase:
    serial_no: str = ""
    fir_no: str = ""
    case_no: str = ""
    court: str = ""
    ipc_sections: str = ""
    other_acts: str = ""
    charges_framed: str = ""
    charges_framed_date: str = ""
    appeal_filed: str = ""
    appeal_details: str = ""
    # "convicted" or "pending"
    case_type: str = "pending"


@dataclass
class AdrRawAsset:
    serial_no: str = ""
    description: str = ""
    # Ownership columns — raw text
    self_value: str = ""
    spouse_value: str = ""
    huf_value: str = ""
    dependent1_value: str = ""
    dependent2_value: str = ""
    dependent3_value: str = ""
    total_value: str = ""
    # "movable" | "immovable" | "liability"
    asset_type: str = "movable"


@dataclass
class AdrRawCandidate:
    candidate_id: int = 0
    source_url: str = ""
    name: str = ""
    party: str = ""
    constituency: str = ""
    state: str = ""
    age: str = ""
    won: bool = False
    photo_url: str = ""
    self_profession: str = ""
    spouse_profession: str = ""
    total_assets_inr: str = ""
    total_liabilities_inr: str = ""
    education: str = ""
    criminal_cases: list[AdrRawCriminalCase] = field(default_factory=list)
    movable_assets: list[AdrRawAsset] = field(default_factory=list)
    immovable_assets: list[AdrRawAsset] = field(default_factory=list)
    liabilities: list[AdrRawAsset] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class AdrParser:
    """
    Parses a candidate.php HTML page into AdrRawCandidate.

    This is intentionally defensive — missing sections return empty lists,
    not exceptions. The normalizer decides what to do with sparse data.
    """

    def parse(self, html: bytes, candidate_id: int, source_url: str) -> AdrRawCandidate:
        from bs4 import BeautifulSoup  # type: ignore[import-untyped]

        soup = BeautifulSoup(html, "lxml")
        raw = AdrRawCandidate(candidate_id=candidate_id, source_url=source_url)

        self._parse_identity(soup, raw)
        self._parse_criminal_cases(soup, raw)
        self._parse_movable_assets(soup, raw)
        self._parse_immovable_assets(soup, raw)
        self._parse_liabilities(soup, raw)

        return raw

    # ------------------------------------------------------------------
    # Identity block
    # ------------------------------------------------------------------

    def _parse_identity(self, soup: "BeautifulSoup", raw: AdrRawCandidate) -> None:  # type: ignore[name-defined]  # noqa: F821
        # Title: "DR. RAJESH MISHRA(BJP):Constituency- SIDHI(MADHYA PRADESH)"
        title_tag = soup.find("title")
        if title_tag:
            self._parse_title(title_tag.get_text(), raw)

        # Photo
        img = soup.find("img", src=re.compile(r"images_candidate", re.I))
        if img:
            raw.photo_url = str(img.get("src", ""))

        # The candidate info card is the first w3-card w3-row w3-panel w3-sand
        # All identity lookups must be scoped to this card, not the full page.
        card = soup.find("div", class_=re.compile(r"w3-card.*w3-sand|w3-sand.*w3-card"))
        scope = card if card else soup

        # Winner check — green "(Winner)" text next to name in h2
        h2 = scope.find("h2")
        if h2:
            raw.name = _clean(h2.get_text()).replace("(Winner)", "").strip()
            raw.won = bool(h2.find("font", color="green"))

        # Constituency + State from h5
        h5 = scope.find("h5")
        if h5:
            text = _clean(h5.get_text())
            # Format: " SIDHI  (MADHYA PRADESH) " or " CHANDNI CHOWK  (DELHI (NCT)) "
            # Take everything up to the last ')' as state, constituency is before first '('
            m = re.match(r"\s*(.+?)\s+\((.+?)\)\s*$", text)
            if m:
                raw.constituency = m.group(1).strip()
                raw.state = m.group(2).strip()

        # Party: look for <div><b>Party:</b>BJP</div> — scoped to card
        # The div must be short (< 50 chars) to avoid picking up big containers
        for div in scope.find_all("div"):
            text = div.get_text(separator="")
            if text.startswith("Party:") or "Party:" in text[:15]:
                party_text = text.replace("Party:", "").strip()
                # Guard: ignore anything longer than a reasonable party name
                if len(party_text) <= 100:
                    raw.party = party_text
                    break

        # Age — short div only
        for div in scope.find_all("div"):
            text = div.get_text(separator="")
            if "Age:" in text[:10]:
                age_text = text.replace("Age:", "").strip()
                if len(age_text) <= 10:
                    raw.age = age_text
                    break

        # Professions — from <p> inside the card
        for p in scope.find_all("p"):
            text = p.get_text(separator="\n")
            if "Self Profession:" in text:
                lines = text.splitlines()
                for line in lines:
                    if "Self Profession:" in line:
                        raw.self_profession = line.replace("Self Profession:", "").strip()
                    elif "Spouse Profession:" in line:
                        raw.spouse_profession = line.replace("Spouse Profession:", "").strip()
                break

        # Total assets / liabilities from the summary card (second card, w3-striped table)
        for tbl in soup.find_all("table", class_=re.compile(r"w3-striped")):
            rows = tbl.find_all("tr")
            for row in rows:
                cells = row.find_all("td")
                if len(cells) >= 2:
                    label = _clean(cells[0].get_text())
                    value_cell = cells[1].get_text()
                    if "Assets" in label and "liabilit" not in label.lower():
                        raw.total_assets_inr = _clean(value_cell)
                    elif "Liabilities" in label:
                        raw.total_liabilities_inr = _clean(value_cell)
            if raw.total_assets_inr:
                break  # found the summary table


    def _parse_title(self, title: str, raw: AdrRawCandidate) -> None:
        """
        Parse: "DR. RAJESH MISHRA(BJP):Constituency- SIDHI(MADHYA PRADESH) - Affidavit..."
        """
        # Name is everything before first "("
        m = re.match(r"^([^(]+)\(", title)
        if m and not raw.name:
            raw.name = m.group(1).strip()

        # Party: text inside first "()"
        m = re.search(r"\(([^)]+)\)", title)
        if m and not raw.party:
            raw.party = m.group(1).strip()

        # Constituency and State from "Constituency- SIDHI(MADHYA PRADESH)"
        m = re.search(r"Constituency[-–\s]+([^(]+)\(([^)]+)\)", title)
        if m:
            raw.constituency = m.group(1).strip()
            raw.state = m.group(2).strip()

    # ------------------------------------------------------------------
    # Criminal cases
    # ------------------------------------------------------------------

    def _parse_criminal_cases(
        self, soup: "BeautifulSoup", raw: AdrRawCandidate  # type: ignore[name-defined]  # noqa: F821
    ) -> None:
        # Two tables: "Cases where Pending" and "Cases where Convicted"
        sections = [
            ("Cases where Pending", "pending"),
            ("Cases where Convicted", "convicted"),
        ]
        for section_text, case_type in sections:
            section_div = _find_section_header(soup, section_text)
            if not section_div:
                continue
            table = section_div.find_next("table")
            if not table:
                continue
            rows = table.find_all("tr")
            if len(rows) <= 1:
                continue  # header only

            for row in rows[1:]:
                cells = [_clean(td.get_text()) for td in row.find_all("td")]
                if not cells or "No Cases" in " ".join(cells):
                    continue

                case = AdrRawCriminalCase(case_type=case_type)
                if case_type == "pending":
                    # Cols: Serial No | FIR No | Case No | Court | IPC Sections |
                    #       Other Details | Charges Framed | Date Framed | Appeal Filed | Details
                    case.serial_no = _get(cells, 0)
                    case.fir_no = _get(cells, 1)
                    case.case_no = _get(cells, 2)
                    case.court = _get(cells, 3)
                    case.ipc_sections = _get(cells, 4)
                    case.other_acts = _get(cells, 5)
                    case.charges_framed = _get(cells, 6)
                    case.charges_framed_date = _get(cells, 7)
                    case.appeal_filed = _get(cells, 8)
                    case.appeal_details = _get(cells, 9)
                else:
                    # Convicted: Serial No | Case No | Court | IPC | Other | Punishment | Date | Appeal | Details
                    case.serial_no = _get(cells, 0)
                    case.case_no = _get(cells, 1)
                    case.court = _get(cells, 2)
                    case.ipc_sections = _get(cells, 3)
                    case.other_acts = _get(cells, 4)
                    case.charges_framed = _get(cells, 5)
                    case.charges_framed_date = _get(cells, 6)
                    case.appeal_filed = _get(cells, 7)
                    case.appeal_details = _get(cells, 8)

                raw.criminal_cases.append(case)

    # ------------------------------------------------------------------
    # Movable assets
    # ------------------------------------------------------------------

    def _parse_movable_assets(
        self, soup: "BeautifulSoup", raw: AdrRawCandidate  # type: ignore[name-defined]  # noqa: F821
    ) -> None:
        table = soup.find("table", id="movable_assets")
        if table:
            raw.movable_assets = self._parse_asset_table(table, "movable")

    # ------------------------------------------------------------------
    # Immovable assets
    # ------------------------------------------------------------------

    def _parse_immovable_assets(
        self, soup: "BeautifulSoup", raw: AdrRawCandidate  # type: ignore[name-defined]  # noqa: F821
    ) -> None:
        table = soup.find("table", id="immovable_assets")
        if table:
            raw.immovable_assets = self._parse_asset_table(table, "immovable")

    # ------------------------------------------------------------------
    # Liabilities
    # ------------------------------------------------------------------

    def _parse_liabilities(
        self, soup: "BeautifulSoup", raw: AdrRawCandidate  # type: ignore[name-defined]  # noqa: F821
    ) -> None:
        table = soup.find("table", id="liabilities")
        if table:
            raw.liabilities = self._parse_asset_table(table, "liability")

    # ------------------------------------------------------------------
    # Shared asset table parser
    # ------------------------------------------------------------------

    def _parse_asset_table(
        self,
        table: "Tag",  # type: ignore[name-defined]  # noqa: F821
        asset_type: str,
    ) -> list[AdrRawAsset]:
        assets: list[AdrRawAsset] = []
        rows = table.find_all("tr", valign="top")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 3:
                continue
            texts = [_clean(td.get_text(separator=" ")) for td in cells]

            # Skip summary/total rows
            first = texts[0].lower()
            if any(kw in first for kw in ("total", "grand", "gross", "totals")):
                continue

            asset = AdrRawAsset(asset_type=asset_type)
            asset.serial_no = _get(texts, 0)
            asset.description = _get(texts, 1)
            asset.self_value = _get(texts, 2)
            asset.spouse_value = _get(texts, 3)
            asset.huf_value = _get(texts, 4)
            asset.dependent1_value = _get(texts, 5)
            asset.dependent2_value = _get(texts, 6)
            asset.dependent3_value = _get(texts, 7)
            # Last column is always the row total
            asset.total_value = _get(texts, len(texts) - 1)
            assets.append(asset)
        return assets


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clean(text: str) -> str:
    """Strip whitespace, collapse multiple spaces, drop NBSP."""
    return re.sub(r"\s+", " ", text.replace("\xa0", " ").replace("\n", " ")).strip()


def _get(lst: list[str], idx: int, default: str = "") -> str:
    try:
        return lst[idx]
    except IndexError:
        return default


def _find_section_header(
    soup: "BeautifulSoup", text: str  # type: ignore[name-defined]  # noqa: F821
) -> "Tag | None":  # type: ignore[name-defined]  # noqa: F821
    """Find a section header div/h3 containing the given text."""
    for tag in soup.find_all(["div", "h3"]):
        if text.lower() in tag.get_text().lower():
            return tag
    return None
