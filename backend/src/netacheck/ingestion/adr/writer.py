"""
ADR writer — idempotent persistence of normalised candidates to the database.

All writes use get-or-create patterns.
The hard constraint: every AffidavitEntry MUST reference a SourceSnapshot.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from netacheck.ingestion.adr.normalizer import NormalisedAsset, NormalisedCandidate
from netacheck.ingestion.base import DuplicateSnapshotError, content_hash
from netacheck.models.affidavit import Affidavit, AffidavitEntry
from netacheck.models.assets import AssetDeclaration, AssetCategory
from netacheck.models.criminal import CriminalCase
from netacheck.models.election import Election, ElectionResult, ElectionType
from netacheck.models.geography import Constituency, ConstituencyType, State
from netacheck.models.politician import (
    PartyMembership,
    PoliticalParty,
    Politician,
    PoliticianAlias,
)
from netacheck.models.source import SourceProvider, SourceSnapshot

logger = structlog.get_logger(__name__)

ADR_PROVIDER_NAME = "myneta.info (ADR)"
ADR_PROVIDER_URL = "https://myneta.info"


class AdrWriter:
    """
    Writes a NormalisedCandidate to the database, idempotently.

    Call write() inside an open AsyncSession transaction.
    The caller is responsible for commit/rollback.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def write(
        self, candidate: NormalisedCandidate, raw_html: bytes
    ) -> Politician:
        """
        Full pipeline for one candidate:
          1. Ensure SourceProvider exists
          2. Create SourceSnapshot (idempotent by content_hash)
          3. Ensure State → Constituency → Election chain
          4. Ensure PoliticalParty
          5. Get or create Politician
          6. Link PartyMembership + ElectionResult
          7. Create Affidavit → AffidavitEntry → CriminalCases + AssetDeclarations
        """
        db = self._session
        log = logger.bind(
            candidate_id=candidate.candidate_id,
            name=candidate.name,
            constituency=candidate.constituency_name,
        )

        # 1. Source provider
        provider = await self._get_or_create_provider()

        # 2. Source snapshot — idempotent by content hash
        chash = content_hash(raw_html)
        snapshot = await self._get_or_create_snapshot(
            provider=provider,
            url=candidate.source_url,
            chash=chash,
            raw_html=raw_html,
        )

        # 3. State + Constituency + Election
        state = await self._get_or_create_state(candidate.state_name)
        constituency = await self._get_or_create_constituency(
            state=state, name=candidate.constituency_name
        )
        election = await self._get_or_create_election(
            constituency=constituency,
            year=candidate.election_year,
            election_date=candidate.election_date,
        )

        # 4. Political party
        party = await self._get_or_create_party(
            name=candidate.party_name,
            abbreviation=candidate.party_abbreviation,
        )

        # 5. Politician
        politician = await self._get_or_create_politician(candidate)

        # 6. Party membership
        await self._ensure_party_membership(
            politician=politician,
            party=party,
            from_date=candidate.election_date,
        )

        # 7. Election result
        election_result = await self._get_or_create_election_result(
            election=election,
            politician=politician,
            party=party,
            won=candidate.won,
        )

        # 8. Affidavit
        affidavit = await self._get_or_create_affidavit(
            election_result=election_result,
            snapshot=snapshot,
        )

        # 9. Affidavit entry (one per candidate per election)
        entry = await self._get_or_create_affidavit_entry(
            affidavit=affidavit, snapshot=snapshot
        )

        # 10. Criminal cases
        if candidate.criminal_cases:
            for case in candidate.criminal_cases:
                cc = CriminalCase(
                    affidavit_entry_id=entry.id,
                    case_number=case.fir_no or case.case_no,
                    court=case.court,
                    section_of_law=case.section_of_law,
                    offence_description=case.offence_description,
                    status=case.status,
                    severity=case.severity,
                    is_cognizable=case.charges_framed,
                )
                db.add(cc)

        # 11. Asset declarations
        for asset in candidate.assets:
            ad = AssetDeclaration(
                affidavit_entry_id=entry.id,
                category=asset.category,
                ownership=asset.ownership,
                description=asset.description,
                value_inr=asset.value_inr,
                raw_value_text=asset.raw_value_text,
            )
            db.add(ad)

        await self._session.flush()

        log.info(
            "candidate_written",
            criminal_cases=len(candidate.criminal_cases),
            assets=len(candidate.assets),
        )
        return politician

    # ------------------------------------------------------------------
    # Get-or-create helpers
    # ------------------------------------------------------------------

    async def _get_or_create_provider(self) -> SourceProvider:
        result = await self._session.execute(
            select(SourceProvider).where(SourceProvider.name == ADR_PROVIDER_NAME)
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing
        provider = SourceProvider(
            name=ADR_PROVIDER_NAME,
            short_code="MYNETA",
            base_url=ADR_PROVIDER_URL,
            is_official=True,
            description="MyNeta.info — open data repository of ADR (Association for Democratic Reforms). Contains self-declared affidavit data filed by election candidates with the Election Commission of India.",
        )
        self._session.add(provider)
        await self._session.flush()
        return provider

    async def _get_or_create_snapshot(
        self,
        provider: SourceProvider,
        url: str,
        chash: str,
        raw_html: bytes,
    ) -> SourceSnapshot:
        # Check if this exact content already exists
        result = await self._session.execute(
            select(SourceSnapshot).where(SourceSnapshot.content_hash == chash)
        )
        existing = result.scalar_one_or_none()
        if existing:
            raise DuplicateSnapshotError(
                f"Snapshot already exists for hash {chash[:12]}… (url={url})"
            )

        url_hash = hashlib.sha256(url.encode()).hexdigest()
        snapshot = SourceSnapshot(
            provider_id=provider.id,
            url=url,
            url_hash=url_hash,
            content_hash=chash,
            fetched_at=datetime.now(tz=timezone.utc),
            parser_version="1.0.0",
            raw_content_size_bytes=len(raw_html),
        )
        self._session.add(snapshot)
        await self._session.flush()
        return snapshot

    async def _get_or_create_state(self, name: str) -> State:
        result = await self._session.execute(
            select(State).where(State.name == name)
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing
        from slugify import slugify  # type: ignore[import-untyped]
        state = State(
            name=name,
            slug=slugify(name),
            iso_code=name[:4].upper().replace(" ", ""),
            is_union_territory=False,
        )
        self._session.add(state)
        await self._session.flush()
        return state

    async def _get_or_create_constituency(
        self, state: State, name: str
    ) -> Constituency:
        result = await self._session.execute(
            select(Constituency).where(
                Constituency.name == name,
                Constituency.state_id == state.id,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing
        from slugify import slugify  # type: ignore[import-untyped]
        constituency = Constituency(
            state_id=state.id,
            name=name,
            slug=slugify(f"{name}-{state.iso_code}"),
            constituency_type=ConstituencyType.LOK_SABHA,
        )
        self._session.add(constituency)
        await self._session.flush()
        return constituency

    async def _get_or_create_election(
        self, constituency: Constituency, year: int, election_date: date
    ) -> Election:
        result = await self._session.execute(
            select(Election).where(
                Election.constituency_id == constituency.id,
                Election.year == year,
                Election.election_type == ElectionType.GENERAL,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing
        election = Election(
            constituency_id=constituency.id,
            election_type=ElectionType.GENERAL,
            election_date=election_date,
            year=year,
        )
        self._session.add(election)
        await self._session.flush()
        return election

    async def _get_or_create_party(
        self, name: str, abbreviation: str
    ) -> PoliticalParty:
        result = await self._session.execute(
            select(PoliticalParty).where(PoliticalParty.abbreviation == abbreviation)
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing
        from slugify import slugify  # type: ignore[import-untyped]
        party = PoliticalParty(
            name=name,
            abbreviation=abbreviation,
            slug=slugify(abbreviation),
            is_active=True,
        )
        self._session.add(party)
        await self._session.flush()
        return party

    async def _get_or_create_politician(
        self, candidate: NormalisedCandidate
    ) -> Politician:
        # Look up by slug (most stable identifier)
        result = await self._session.execute(
            select(Politician).where(Politician.slug == candidate.slug)
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing

        politician = Politician(
            name=candidate.name,
            slug=candidate.slug,
            photo_url=candidate.photo_url,
        )
        self._session.add(politician)
        await self._session.flush()

        # Add alias for the original raw name
        alias = PoliticianAlias(
            politician_id=politician.id,
            alias=candidate.name,
            source="myneta.info",
        )
        self._session.add(alias)
        return politician

    async def _ensure_party_membership(
        self,
        politician: Politician,
        party: PoliticalParty,
        from_date: date,
    ) -> None:
        result = await self._session.execute(
            select(PartyMembership).where(
                PartyMembership.politician_id == politician.id,
                PartyMembership.party_id == party.id,
            )
        )
        if result.scalar_one_or_none():
            return
        membership = PartyMembership(
            politician_id=politician.id,
            party_id=party.id,
            from_date=from_date,
            is_primary=True,
        )
        self._session.add(membership)

    async def _get_or_create_election_result(
        self,
        election: Election,
        politician: Politician,
        party: PoliticalParty,
        won: bool,
    ) -> ElectionResult:
        result = await self._session.execute(
            select(ElectionResult).where(
                ElectionResult.election_id == election.id,
                ElectionResult.politician_id == politician.id,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing
        er = ElectionResult(
            election_id=election.id,
            politician_id=politician.id,
            party_id=party.id,
            won=won,
        )
        self._session.add(er)
        await self._session.flush()
        return er

    async def _get_or_create_affidavit(
        self,
        election_result: ElectionResult,
        snapshot: SourceSnapshot,
    ) -> Affidavit:
        result = await self._session.execute(
            select(Affidavit).where(
                Affidavit.election_result_id == election_result.id
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing
        affidavit = Affidavit(
            election_result_id=election_result.id,
            source_snapshot_id=snapshot.id,
        )
        self._session.add(affidavit)
        await self._session.flush()
        return affidavit

    async def _get_or_create_affidavit_entry(
        self,
        affidavit: Affidavit,
        snapshot: SourceSnapshot,
    ) -> AffidavitEntry:
        result = await self._session.execute(
            select(AffidavitEntry).where(
                AffidavitEntry.affidavit_id == affidavit.id
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing
        entry = AffidavitEntry(
            affidavit_id=affidavit.id,
            source_snapshot_id=snapshot.id,  # hard constraint
            field_name="affidavit_full",
            section="complete_affidavit",
        )
        self._session.add(entry)
        await self._session.flush()
        return entry
