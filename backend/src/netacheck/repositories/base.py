"""
Generic async repository base class.

Provides standard CRUD operations typed against a specific SQLAlchemy model.
All subclasses inherit from this and add domain-specific query methods.

Usage:
    class PoliticianRepository(AsyncRepository[Politician]):
        model = Politician

        async def get_by_slug(self, slug: str) -> Politician | None:
            ...
"""

from __future__ import annotations

import uuid
from typing import Any, Generic, TypeVar

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from netacheck.core.database import Base

ModelT = TypeVar("ModelT", bound=Base)


class AsyncRepository(Generic[ModelT]):
    """
    Generic async repository providing standard data access operations.

    Subclasses must set the `model` class attribute.
    """

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, record_id: uuid.UUID) -> ModelT | None:
        """Fetch a record by its UUID primary key."""
        result = await self.session.get(self.model, record_id)
        return result

    async def get_by_slug(self, slug: str) -> ModelT | None:
        """Fetch a record by its slug field. Model must have a `slug` column."""
        stmt = select(self.model).where(self.model.slug == slug)  # type: ignore[attr-defined]
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_paginated(
        self,
        *,
        offset: int = 0,
        limit: int = 20,
        **filters: Any,
    ) -> tuple[list[ModelT], int]:
        """
        Return a paginated list of records and the total count.

        Returns (items, total_count).
        """
        stmt = select(self.model)
        count_stmt = select(func.count()).select_from(self.model)

        for key, value in filters.items():
            if value is not None:
                col = getattr(self.model, key, None)
                if col is not None:
                    stmt = stmt.where(col == value)
                    count_stmt = count_stmt.where(col == value)

        total_result = await self.session.execute(count_stmt)
        total = total_result.scalar_one()

        stmt = stmt.offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def create(self, **kwargs: Any) -> ModelT:
        """Create and persist a new record."""
        instance = self.model(**kwargs)
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def update(self, instance: ModelT, **kwargs: Any) -> ModelT:
        """Update fields on an existing record."""
        for key, value in kwargs.items():
            setattr(instance, key, value)
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def soft_delete(self, instance: ModelT) -> ModelT:
        """
        Mark a record as deleted without physically removing it.

        Model must have a `deleted_at` field (SoftDeleteMixin).
        """
        from datetime import datetime, timezone
        instance.deleted_at = datetime.now(tz=timezone.utc)  # type: ignore[attr-defined]
        self.session.add(instance)
        await self.session.flush()
        return instance

    async def count(self, **filters: Any) -> int:
        """Return the total count of records matching the given filters."""
        stmt = select(func.count()).select_from(self.model)
        for key, value in filters.items():
            if value is not None:
                col = getattr(self.model, key, None)
                if col is not None:
                    stmt = stmt.where(col == value)
        result = await self.session.execute(stmt)
        return result.scalar_one()
