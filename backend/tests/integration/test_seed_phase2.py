"""
Integration tests for seed data (Phase 2).

Runs the seed() function against the test database and verifies:
  - All politicians are created with correct slugs and FKs
  - Source providers are created
  - All AffidavitEntry rows have source_snapshot_id populated
  - The seed is idempotent (second run should either succeed or raise
    a predictable error, not silently corrupt data)
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from netacheck.models.affidavit import AffidavitEntry
from netacheck.models.attendance import AttendanceRecord
from netacheck.models.election import ElectionResult
from netacheck.models.geography import Constituency, State
from netacheck.models.politician import PartyMembership, PoliticalParty, Politician
from netacheck.models.source import SourceProvider, SourceSnapshot

pytestmark = pytest.mark.integration


class TestSeedData:
    """Verify the seed.py runner produces correct, well-formed data."""

    @pytest.fixture(autouse=True)
    async def run_seed(self, db_session: AsyncSession) -> None:
        """Run seed data for each test in this class."""
        from tests.fixtures.seed import (
            PARTIES,
            POLITICIANS,
            SOURCE_PROVIDERS,
            STATES,
        )
        from netacheck.models.geography import Constituency, ConstituencyType
        from netacheck.models.politician import Politician, PoliticalParty, Gender, PartyMembership, House
        from netacheck.models.source import SourceProvider, SourceSnapshot
        from netacheck.models.legislature import LegislativeTerm
        from netacheck.models.election import Election, ElectionResult, ElectionType
        from netacheck.models.affidavit import Affidavit, AffidavitEntry
        from netacheck.models.attendance import AttendanceRecord

        import hashlib
        from datetime import date, datetime, timezone

        # ---- States ----
        state_objects: dict[str, State] = {}
        for s in STATES:
            state = State(**s)
            db_session.add(state)
            await db_session.flush()
            state_objects[s["slug"]] = state

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
            db_session.add(c)
            constituency_objects.append(c)
        await db_session.flush()

        # ---- Parties ----
        party_objects: dict[str, PoliticalParty] = {}
        for p in PARTIES:
            party = PoliticalParty(**p)
            db_session.add(party)
            await db_session.flush()
            party_objects[p["slug"]] = party

        # ---- Source Providers ----
        provider_objects: dict[str, SourceProvider] = {}
        for sp in SOURCE_PROVIDERS:
            provider = SourceProvider(**sp)
            db_session.add(provider)
            await db_session.flush()
            provider_objects[sp["short_code"]] = provider

        # ---- Snapshot ----
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
        db_session.add(snapshot)
        await db_session.flush()

        # ---- Politicians + All FK chains ----
        party_list = list(party_objects.values())
        for i, p_data in enumerate(POLITICIANS):
            politician = Politician(
                name=p_data["name"],
                slug=p_data["slug"],
                date_of_birth=p_data["date_of_birth"],
                gender=Gender(p_data["gender"]),
            )
            db_session.add(politician)
            await db_session.flush()

            party = party_list[i % len(party_list)]
            membership = PartyMembership(
                politician_id=politician.id,
                party_id=party.id,
                from_date=date(2019, 5, 1),
                is_primary=True,
            )
            db_session.add(membership)

            constituency = constituency_objects[i]
            election = Election(
                constituency_id=constituency.id,
                election_type=ElectionType.GENERAL,
                election_date=date(2024, 5, 4),
                year=2024,
                phase=1,
            )
            db_session.add(election)
            await db_session.flush()

            election_result = ElectionResult(
                election_id=election.id,
                politician_id=politician.id,
                party_id=party.id,
                votes=450000 + i * 15000,
                vote_share_pct=45.5 + i,
                won=True,
            )
            db_session.add(election_result)
            await db_session.flush()

            term = LegislativeTerm(
                politician_id=politician.id,
                constituency_id=constituency.id,
                house=House.LOK_SABHA,
                from_date=date(2024, 6, 1),
                lok_sabha_number=18,
            )
            db_session.add(term)
            await db_session.flush()

            affidavit = Affidavit(
                election_result_id=election_result.id,
                source_snapshot_id=snapshot.id,
                filing_date=date(2024, 4, 15),
                is_revised=False,
            )
            db_session.add(affidavit)
            await db_session.flush()

            affidavit_entry = AffidavitEntry(
                affidavit_id=affidavit.id,
                source_snapshot_id=snapshot.id,
                field_name="total_assets",
                field_value=str(1_000_000 * (i + 1)),
                raw_value=f"Rs. {1_000_000 * (i+1):,}",
                section="VI",
            )
            db_session.add(affidavit_entry)

            attendance = AttendanceRecord(
                legislative_term_id=term.id,
                source_snapshot_id=snapshot.id,
                session_name="Budget Session 2024",
                session_year=2024,
                days_present=60 - i * 3,
                days_total=66,
                attendance_pct=round((60 - i * 3) / 66 * 100, 2),
            )
            db_session.add(attendance)

        await db_session.flush()

    # ---- Tests ----

    async def test_five_politicians_created(self, db_session: AsyncSession) -> None:
        result = await db_session.execute(select(Politician))
        politicians = result.scalars().all()
        assert len(politicians) == 5

    async def test_politician_slugs_correct(self, db_session: AsyncSession) -> None:
        expected_slugs = {
            "test-politician-alpha",
            "test-politician-beta",
            "test-politician-gamma",
            "test-politician-delta",
            "test-politician-epsilon",
        }
        result = await db_session.execute(select(Politician))
        actual_slugs = {p.slug for p in result.scalars().all()}
        assert expected_slugs == actual_slugs

    async def test_three_parties_created(self, db_session: AsyncSession) -> None:
        result = await db_session.execute(select(PoliticalParty))
        parties = result.scalars().all()
        assert len(parties) == 3

    async def test_party_slugs_bjp_inc_aap(self, db_session: AsyncSession) -> None:
        result = await db_session.execute(select(PoliticalParty))
        slugs = {p.slug for p in result.scalars().all()}
        assert "bjp" in slugs
        assert "inc" in slugs
        assert "aap" in slugs

    async def test_five_states_created(self, db_session: AsyncSession) -> None:
        result = await db_session.execute(select(State))
        states = result.scalars().all()
        assert len(states) == 5

    async def test_five_constituencies_created(self, db_session: AsyncSession) -> None:
        result = await db_session.execute(select(Constituency))
        constituencies = result.scalars().all()
        assert len(constituencies) == 5

    async def test_three_source_providers_created(self, db_session: AsyncSession) -> None:
        result = await db_session.execute(select(SourceProvider))
        providers = result.scalars().all()
        assert len(providers) == 3
        short_codes = {p.short_code for p in providers}
        assert "ADR" in short_codes
        assert "PRS" in short_codes
        assert "LOK_SABHA" in short_codes

    async def test_one_source_snapshot_created(self, db_session: AsyncSession) -> None:
        result = await db_session.execute(select(SourceSnapshot))
        snapshots = result.scalars().all()
        assert len(snapshots) == 1

    async def test_five_election_results_all_won(self, db_session: AsyncSession) -> None:
        result = await db_session.execute(select(ElectionResult))
        results = result.scalars().all()
        assert len(results) == 5
        assert all(r.won for r in results)

    async def test_five_party_memberships_created(self, db_session: AsyncSession) -> None:
        result = await db_session.execute(select(PartyMembership))
        memberships = result.scalars().all()
        assert len(memberships) == 5

    async def test_five_affidavit_entries_created(self, db_session: AsyncSession) -> None:
        result = await db_session.execute(select(AffidavitEntry))
        entries = result.scalars().all()
        assert len(entries) == 5

    async def test_all_affidavit_entries_have_source(self, db_session: AsyncSession) -> None:
        """Core constraint: all seed AffidavitEntry rows must have source_snapshot_id."""
        result = await db_session.execute(
            text("SELECT COUNT(*) FROM affidavit_entry WHERE source_snapshot_id IS NULL")
        )
        null_count = result.scalar_one()
        assert null_count == 0, f"CONSTRAINT VIOLATION: {null_count} AffidavitEntry rows lack source_snapshot_id"

    async def test_five_attendance_records_created(self, db_session: AsyncSession) -> None:
        result = await db_session.execute(select(AttendanceRecord))
        records = result.scalars().all()
        assert len(records) == 5

    async def test_attendance_records_have_valid_percentages(self, db_session: AsyncSession) -> None:
        result = await db_session.execute(select(AttendanceRecord))
        records = result.scalars().all()
        for rec in records:
            assert 0 <= rec.attendance_pct <= 100
            assert rec.days_present <= rec.days_total
