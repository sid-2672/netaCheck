"""
Affidavit and affidavit entry models.

Affidavits are filed by candidates at election time and are the primary
source for criminal cases and asset declarations.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from netacheck.core.database import Base
from netacheck.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class Affidavit(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    An election nomination affidavit (Form 26) filed by a candidate.

    Linked to a specific election result (candidate + election) and the
    source snapshot from which it was parsed.
    """

    __tablename__ = "affidavit"

    election_result_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("election_result.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_snapshot.id", ondelete="RESTRICT"),
        nullable=False,
    )
    filing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    affidavit_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_revised: Mapped[bool] = mapped_column(default=False, nullable=False)

    election_result: Mapped["ElectionResult"] = relationship("ElectionResult", back_populates="affidavits")
    source_snapshot: Mapped["SourceSnapshot"] = relationship("SourceSnapshot")
    entries: Mapped[list["AffidavitEntry"]] = relationship(
        "AffidavitEntry", back_populates="affidavit"
    )

    def __repr__(self) -> str:
        return f"<Affidavit election_result={self.election_result_id}>"


class AffidavitEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    A single parsed field from an affidavit.

    Every entry has a source_snapshot reference — this is the core enforcement
    of the platform's hard constraint. No entry can exist without a source.

    Entries are immutable. New ingestions create new entries with newer timestamps;
    old entries are preserved for audit purposes.
    """

    __tablename__ = "affidavit_entry"

    affidavit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("affidavit.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_snapshot.id", ondelete="RESTRICT"),
        nullable=False,
        comment="Source required — no unsourced entries permitted",
    )
    field_name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="e.g. 'total_assets', 'educational_qualification'"
    )
    field_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_value: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Unparsed string from source document"
    )
    section: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="Section of the affidavit form"
    )

    affidavit: Mapped["Affidavit"] = relationship("Affidavit", back_populates="entries")
    source_snapshot: Mapped["SourceSnapshot"] = relationship("SourceSnapshot")
    criminal_cases: Mapped[list["CriminalCase"]] = relationship("CriminalCase", back_populates="affidavit_entry")
    asset_declarations: Mapped[list["AssetDeclaration"]] = relationship(
        "AssetDeclaration", back_populates="affidavit_entry"
    )

    def __repr__(self) -> str:
        return f"<AffidavitEntry {self.field_name}={self.field_value!r}>"
