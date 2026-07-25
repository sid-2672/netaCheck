"""
Development seed data.

Populates the database with a representative set of test data:
- 5 real Indian states
- 5 constituencies
- 3 political parties
- 5 politicians (slugs only, no real personal data used for non-public figures)
- Source providers (ADR, PRS)
- Legislative terms, elections, and sample attendance records

Run via: make seed
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import date, datetime, timezone

import structlog

from netacheck.core.database import async_session_factory

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Seed data definitions
# ---------------------------------------------------------------------------

STATES = [
    {"name": "Uttar Pradesh", "slug": "uttar-pradesh", "iso_code": "IN-UP", "is_union_territory": False},
    {"name": "Maharashtra", "slug": "maharashtra", "iso_code": "IN-MH", "is_union_territory": False},
    {"name": "Tamil Nadu", "slug": "tamil-nadu", "iso_code": "IN-TN", "is_union_territory": False},
    {"name": "West Bengal", "slug": "west-bengal", "iso_code": "IN-WB", "is_union_territory": False},
    {"name": "Gujarat", "slug": "gujarat", "iso_code": "IN-GJ", "is_union_territory": False},
]

PARTIES = [
    {
        "name": "Bharatiya Janata Party",
        "slug": "bjp",
        "abbreviation": "BJP",
        "eci_id": "INC-001",
        "is_national_party": True,
        "is_active": True,
    },
    {
        "name": "Indian National Congress",
        "slug": "inc",
        "abbreviation": "INC",
        "eci_id": "INC-002",
        "is_national_party": True,
        "is_active": True,
    },
    {
        "name": "Aam Aadmi Party",
        "slug": "aap",
        "abbreviation": "AAP",
        "eci_id": "INC-003",
        "is_national_party": True,
        "is_active": True,
    },
]

POLITICIANS = [
    {
        "name": "Test Politician Alpha",
        "slug": "test-politician-alpha",
        "gender": "MALE",
        "date_of_birth": date(1960, 3, 15),
    },
    {
        "name": "Test Politician Beta",
        "slug": "test-politician-beta",
        "gender": "FEMALE",
        "date_of_birth": date(1975, 8, 22),
    },
    {
        "name": "Test Politician Gamma",
        "slug": "test-politician-gamma",
        "gender": "MALE",
        "date_of_birth": date(1955, 12, 1),
    },
    {
        "name": "Test Politician Delta",
        "slug": "test-politician-delta",
        "gender": "FEMALE",
        "date_of_birth": date(1980, 5, 10),
    },
    {
        "name": "Test Politician Epsilon",
        "slug": "test-politician-epsilon",
        "gender": "MALE",
        "date_of_birth": date(1968, 7, 30),
    },
]

SOURCE_PROVIDERS = [
    {
        "name": "Association for Democratic Reforms / MyNeta",
        "short_code": "ADR",
        "base_url": "https://myneta.info",
        "description": "Affidavit data from ECI election filings",
        "is_official": True,
        "request_delay_seconds": 2.0,
    },
    {
        "name": "PRS Legislative Research",
        "short_code": "PRS",
        "base_url": "https://prsindia.org",
        "description": "Legislative activity and attendance data",
        "is_official": False,
        "request_delay_seconds": 1.5,
    },
    {
        "name": "Lok Sabha Secretariat",
        "short_code": "LOK_SABHA",
        "base_url": "https://loksabha.nic.in",
        "description": "Official parliamentary records",
        "is_official": True,
        "request_delay_seconds": 3.0,
    },
]


# ---------------------------------------------------------------------------
# Seed runner
# ---------------------------------------------------------------------------

async def seed() -> None:
    """Run all seed operations inside a single transaction."""
    from netacheck.models.geography import State, Constituency, ConstituencyType
    from netacheck.models.politician import Politician, PoliticalParty, Gender, PartyMembership
    from netacheck.models.source import SourceProvider, SourceSnapshot
    from netacheck.models.legislature import LegislativeTerm
    from netacheck.models.election import Election, ElectionResult, ElectionType
    from netacheck.models.affidavit import Affidavit, AffidavitEntry
    from netacheck.models.attendance import AttendanceRecord
    from netacheck.models.politician import House

    async with async_session_factory() as session:
        async with session.begin():
            log.info("seed_start")

            # ---- States ----
            state_objects: dict[str, State] = {}
            for s in STATES:
                state = State(**s)
                session.add(state)
                await session.flush()
                state_objects[s["slug"]] = state
            log.info("seed_states_done", count=len(state_objects))

            # ---- Constituencies ----
            constituency_objects: list[Constituency] = []
            for i, (slug, state) in enumerate(state_objects.items()):
                c = Constituency(
                    name=f"{state.name} Constituency {i+1}",
                    slug=f"{slug}-constituency-{i+1}",
                    state_id=state.id,
                    constituency_type=ConstituencyType.LOK_SABHA,
                    number=i + 1,
                )
                session.add(c)
                constituency_objects.append(c)
            await session.flush()
            log.info("seed_constituencies_done", count=len(constituency_objects))

            # ---- Parties ----
            party_objects: dict[str, PoliticalParty] = {}
            for p in PARTIES:
                party = PoliticalParty(**p)
                session.add(party)
                await session.flush()
                party_objects[p["slug"]] = party
            log.info("seed_parties_done", count=len(party_objects))

            # ---- Source Providers ----
            provider_objects: dict[str, SourceProvider] = {}
            for sp in SOURCE_PROVIDERS:
                provider = SourceProvider(**sp)
                session.add(provider)
                await session.flush()
                provider_objects[sp["short_code"]] = provider
            log.info("seed_providers_done", count=len(provider_objects))

            # ---- Snapshot (shared dummy) ----
            dummy_content = b"<html><body>Test affidavit data</body></html>"
            dummy_url = "https://myneta.info/test/affidavit.html"
            snapshot = SourceSnapshot(
                provider_id=provider_objects["ADR"].id,
                url=dummy_url,
                url_hash=hashlib.sha256(dummy_url.encode()).hexdigest(),
                content_hash=hashlib.sha256(dummy_content).hexdigest(),
                fetched_at=datetime.now(tz=timezone.utc),
                http_status=200,
                parser_version="0.1.0",
                raw_content_size_bytes=len(dummy_content),
                notes="Seed data snapshot",
            )
            session.add(snapshot)
            await session.flush()

            # ---- Politicians + Memberships + Elections ----
            party_list = list(party_objects.values())
            for i, p_data in enumerate(POLITICIANS):
                politician = Politician(
                    name=p_data["name"],
                    slug=p_data["slug"],
                    date_of_birth=p_data["date_of_birth"],
                    gender=Gender(p_data["gender"]),
                )
                session.add(politician)
                await session.flush()

                # Party membership
                party = party_list[i % len(party_list)]
                membership = PartyMembership(
                    politician_id=politician.id,
                    party_id=party.id,
                    from_date=date(2019, 5, 1),
                    is_primary=True,
                )
                session.add(membership)

                # Constituency + Election
                constituency = constituency_objects[i]
                election = Election(
                    constituency_id=constituency.id,
                    election_type=ElectionType.GENERAL,
                    election_date=date(2024, 5, 4),
                    year=2024,
                    phase=1,
                )
                session.add(election)
                await session.flush()

                election_result = ElectionResult(
                    election_id=election.id,
                    politician_id=politician.id,
                    party_id=party.id,
                    votes=450000 + i * 15000,
                    vote_share_pct=45.5 + i,
                    won=True,
                )
                session.add(election_result)
                await session.flush()

                # Legislative term
                term = LegislativeTerm(
                    politician_id=politician.id,
                    constituency_id=constituency.id,
                    house=House.LOK_SABHA,
                    from_date=date(2024, 6, 1),
                    lok_sabha_number=18,
                )
                session.add(term)
                await session.flush()

                # Affidavit
                affidavit = Affidavit(
                    election_result_id=election_result.id,
                    source_snapshot_id=snapshot.id,
                    filing_date=date(2024, 4, 15),
                    is_revised=False,
                )
                session.add(affidavit)
                await session.flush()

                affidavit_entry = AffidavitEntry(
                    affidavit_id=affidavit.id,
                    source_snapshot_id=snapshot.id,
                    field_name="total_assets",
                    field_value=str(1_000_000 * (i + 1)),
                    raw_value=f"Rs. {1_000_000 * (i+1):,}",
                    section="VI",
                )
                session.add(affidavit_entry)

                # Attendance
                attendance = AttendanceRecord(
                    legislative_term_id=term.id,
                    source_snapshot_id=snapshot.id,
                    session_name="Budget Session 2024",
                    session_year=2024,
                    days_present=60 - i * 3,
                    days_total=66,
                    attendance_pct=round((60 - i * 3) / 66 * 100, 2),
                )
                session.add(attendance)

            await session.flush()
            log.info("seed_politicians_done", count=len(POLITICIANS))

        log.info("seed_complete")


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
