"""Legislative activity model."""

from __future__ import annotations

import enum
import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from netacheck.core.database import Base
from netacheck.models.base import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from netacheck.models.legislature import LegislativeTerm
    from netacheck.models.source import SourceSnapshot


class ActivityType(enum.StrEnum):
    STARRED_QUESTION = "STARRED_QUESTION"
    UNSTARRED_QUESTION = "UNSTARRED_QUESTION"
    PRIVATE_MEMBER_BILL = "PRIVATE_MEMBER_BILL"
    DEBATE_PARTICIPATION = "DEBATE_PARTICIPATION"
    ZERO_HOUR = "ZERO_HOUR"
    CALLING_ATTENTION = "CALLING_ATTENTION"
    SHORT_DURATION_DISCUSSION = "SHORT_DURATION_DISCUSSION"


class LegislativeActivity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single legislative activity record."""

    __tablename__ = "legislative_activity"

    legislative_term_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("legislative_term.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_snapshot.id", ondelete="RESTRICT"),
        nullable=False,
    )
    activity_type: Mapped[ActivityType] = mapped_column(
        Enum(ActivityType, name="activity_type_enum"), nullable=False, index=True
    )
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    activity_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    session_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ministry_concerned: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_admitted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    legislative_term: Mapped[LegislativeTerm] = relationship(
        "LegislativeTerm", back_populates="legislative_activities"
    )
    source_snapshot: Mapped[SourceSnapshot] = relationship("SourceSnapshot")

    def __repr__(self) -> str:
        return f"<LegislativeActivity {self.activity_type} {self.activity_date}>"
