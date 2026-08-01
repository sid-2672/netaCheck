"""
Source repository.

Handles idempotent snapshot creation keyed by (url_hash, content_hash).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy import select

from netacheck.models.source import SourceProvider, SourceSnapshot
from netacheck.repositories.base import AsyncRepository


class SourceProviderRepository(AsyncRepository[SourceProvider]):
    model = SourceProvider

    async def get_by_short_code(self, short_code: str) -> SourceProvider | None:
        stmt = select(SourceProvider).where(SourceProvider.short_code == short_code)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class SourceSnapshotRepository(AsyncRepository[SourceSnapshot]):
    model = SourceSnapshot

    @staticmethod
    def hash_url(url: str) -> str:
        """Produce a stable SHA-256 hash of the normalised URL."""
        return hashlib.sha256(url.strip().lower().encode()).hexdigest()

    @staticmethod
    def hash_content(content: bytes) -> str:
        """Produce a SHA-256 hash of raw response bytes."""
        return hashlib.sha256(content).hexdigest()

    async def get_by_hashes(self, url_hash: str, content_hash: str) -> SourceSnapshot | None:
        """Look up an existing snapshot by its idempotency key."""
        stmt = select(SourceSnapshot).where(
            SourceSnapshot.url_hash == url_hash,
            SourceSnapshot.content_hash == content_hash,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_or_create(
        self,
        *,
        provider_id: str,
        url: str,
        content: bytes,
        parser_version: str,
        http_status: int = 200,
        notes: str | None = None,
    ) -> tuple[SourceSnapshot, bool]:
        """
        Idempotently create a source snapshot.

        Returns (snapshot, created) where `created` is False if the snapshot
        already existed (same URL + content hash).
        """
        import uuid as _uuid

        url_hash = self.hash_url(url)
        content_hash = self.hash_content(content)

        existing = await self.get_by_hashes(url_hash, content_hash)
        if existing is not None:
            return existing, False

        snapshot = await self.create(
            provider_id=_uuid.UUID(str(provider_id)),
            url=url,
            url_hash=url_hash,
            content_hash=content_hash,
            fetched_at=datetime.now(tz=UTC),
            http_status=http_status,
            parser_version=parser_version,
            raw_content_size_bytes=len(content),
            notes=notes,
        )
        return snapshot, True
