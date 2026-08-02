"""Correction request and history models."""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from netacheck.core.database import Base
from netacheck.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class CorrectionStatus(enum.StrEnum):
    PENDING = "PENDING"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class CorrectionRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "correction_request"

    politician_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("politician.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    submitter_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    submitter_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    field_name: Mapped[str] = mapped_column(String(200), nullable=False)
    current_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    claimed_correct_value: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[CorrectionStatus] = mapped_column(
        Enum(CorrectionStatus, name="correction_status_enum"),
        default=CorrectionStatus.PENDING,
        nullable=False,
        index=True,
    )
    reviewer_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    history: Mapped[list[CorrectionHistory]] = relationship(
        "CorrectionHistory", back_populates="correction_request"
    )

    def __repr__(self) -> str:
        return f"<CorrectionRequest field={self.field_name} status={self.status}>"


class CorrectionHistory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "correction_history"

    correction_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("correction_request.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    from_status: Mapped[CorrectionStatus | None] = mapped_column(
        Enum(CorrectionStatus, name="correction_status_enum"), nullable=True
    )
    to_status: Mapped[CorrectionStatus] = mapped_column(
        Enum(CorrectionStatus, name="correction_status_enum"), nullable=False
    )
    changed_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    correction_request: Mapped[CorrectionRequest] = relationship(
        "CorrectionRequest", back_populates="history"
    )

    def __repr__(self) -> str:
        return f"<CorrectionHistory {self.from_status} → {self.to_status}>"
