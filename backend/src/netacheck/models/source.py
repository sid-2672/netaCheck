"""
Source provenance models.

These are the central enforcement mechanism for the platform's hard constraint:
every fact must trace to an immutable SourceSnapshot.

Design:
- SourceProvider: the organisation/website (ADR, PRS, Lok Sabha, ECI)
- SourceSnapshot: a single crawl of a specific URL, keyed by (url_hash, content_hash)
  for idempotent ingestion.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from netacheck.core.database import Base
from netacheck.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class SourceProvider(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    A registered data provider.

    Examples: ADR/MyNeta, PRS India, Lok Sabha Secretariat, ECI.
    Rate limiting and scraping policies are configured per provider.
    """

    __tablename__ = "source_provider"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    short_code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_official: Mapped[bool] = mapped_column(
        default=True, nullable=False, comment="True = government or quasi-government source"
    )
    request_delay_seconds: Mapped[float] = mapped_column(default=1.5, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    snapshots: Mapped[list[SourceSnapshot]] = relationship(
        "SourceSnapshot", back_populates="provider"
    )

    def __repr__(self) -> str:
        return f"<SourceProvider {self.short_code}>"


class SourceSnapshot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    An immutable record of a single fetch from a source URL.

    Idempotency key: (url_hash, content_hash).
    If both match a prior snapshot, the ingestion pipeline skips re-processing.
    If URL matches but content changed, a new snapshot is created.

    Rows in this table are never updated or deleted.
    """

    __tablename__ = "source_snapshot"

    __table_args__ = (UniqueConstraint("url_hash", "content_hash", name="uq_snapshot_url_content"),)

    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_provider.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    url_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True, comment="SHA-256 of normalised URL"
    )
    content_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="SHA-256 of raw response body"
    )
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parser_version: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="Semantic version of the parser used"
    )
    raw_content_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    provider: Mapped[SourceProvider] = relationship("SourceProvider", back_populates="snapshots")

    def __repr__(self) -> str:
        return f"<SourceSnapshot {self.url_hash[:8]}… @ {self.fetched_at}>"
