"""Grading snapshot models."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from netacheck.core.database import Base
from netacheck.models.base import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from netacheck.models.politician import Politician


class GradeLetter(enum.StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    F = "F"
    NA = "N/A"


class Confidence(enum.StrEnum):
    OFFICIAL_PRIMARY = "OFFICIAL_PRIMARY"
    OFFICIAL_SECONDARY = "OFFICIAL_SECONDARY"
    INFERRED_DERIVED = "INFERRED_DERIVED"
    USER_SUBMITTED = "USER_SUBMITTED"


class GradeSnapshot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "grade_snapshot"

    politician_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("politician.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    overall_grade: Mapped[GradeLetter] = mapped_column(
        Enum(GradeLetter, name="grade_letter_enum"), nullable=False
    )
    overall_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    engine_version: Mapped[str] = mapped_column(String(50), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    politician: Mapped[Politician] = relationship("Politician", back_populates="grade_snapshots")
    metric_results: Mapped[list[GradeMetricResult]] = relationship(
        "GradeMetricResult", back_populates="grade_snapshot"
    )

    def __repr__(self) -> str:
        return f"<GradeSnapshot politician={self.politician_id} grade={self.overall_grade}>"


class GradeMetricResult(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "grade_metric_result"

    grade_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("grade_snapshot.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    metric_name: Mapped[str] = mapped_column(String(100), nullable=False)
    raw_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    grade: Mapped[GradeLetter] = mapped_column(
        Enum(GradeLetter, name="grade_letter_enum"), nullable=False
    )
    score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    weight: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[Confidence] = mapped_column(
        Enum(Confidence, name="confidence_enum"), nullable=False
    )

    grade_snapshot: Mapped[GradeSnapshot] = relationship(
        "GradeSnapshot", back_populates="metric_results"
    )

    def __repr__(self) -> str:
        return f"<GradeMetricResult {self.metric_name}={self.grade}>"
