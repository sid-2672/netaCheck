"""
Politician repository.

Domain-specific queries for politician data access.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import or_, select

from netacheck.models.politician import PoliticalParty, Politician
from netacheck.repositories.base import AsyncRepository

if TYPE_CHECKING:
    import uuid


class PoliticianRepository(AsyncRepository[Politician]):
    model = Politician

    async def get_by_slug(self, slug: str) -> Politician | None:
        """Fetch a politician by slug, excluding soft-deleted records."""
        stmt = (
            select(Politician).where(Politician.slug == slug).where(Politician.deleted_at.is_(None))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def search(
        self,
        query: str,
        *,
        state_id: uuid.UUID | None = None,
        party_id: uuid.UUID | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Politician], int]:
        """
        Full-text search on politician name.

        Filters by state and/or party if provided.
        Returns (results, total_count).
        """
        from sqlalchemy import func

        stmt = (
            select(Politician)
            .where(Politician.deleted_at.is_(None))
            .where(
                or_(
                    Politician.name.ilike(f"%{query}%"),
                    Politician.name_hindi.ilike(f"%{query}%"),
                )
            )
        )

        count_stmt = (
            select(func.count())
            .select_from(Politician)
            .where(Politician.deleted_at.is_(None))
            .where(
                or_(
                    Politician.name.ilike(f"%{query}%"),
                    Politician.name_hindi.ilike(f"%{query}%"),
                )
            )
        )

        total_result = await self.session.execute(count_stmt)
        total = total_result.scalar_one()

        result = await self.session.execute(stmt.offset(offset).limit(limit))
        return list(result.scalars().all()), total

    async def list_active(
        self,
        *,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Politician], int]:
        """List all non-deleted politicians with pagination."""
        from sqlalchemy import func

        count_stmt = (
            select(func.count()).select_from(Politician).where(Politician.deleted_at.is_(None))
        )
        total_result = await self.session.execute(count_stmt)
        total = total_result.scalar_one()

        stmt = (
            select(Politician)
            .where(Politician.deleted_at.is_(None))
            .order_by(Politician.name)
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total


class PartyRepository(AsyncRepository[PoliticalParty]):
    model = PoliticalParty

    async def get_by_slug(self, slug: str) -> PoliticalParty | None:
        stmt = select(PoliticalParty).where(PoliticalParty.slug == slug)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_active(self) -> list[PoliticalParty]:
        stmt = (
            select(PoliticalParty)
            .where(PoliticalParty.is_active.is_(True))
            .order_by(PoliticalParty.name)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
