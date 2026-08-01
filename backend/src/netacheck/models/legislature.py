"""Legislative term model."""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from netacheck.core.database import Base
from netacheck.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from netacheck.models.politician import House

if TYPE_CHECKING:
    from netacheck.models.attendance import AttendanceRecord
    from netacheck.models.geography import Constituency
    from netacheck.models.legislative import LegislativeActivity
    from netacheck.models.politician import Politician


class LegislativeTerm(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "legislative_term"

    politician_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("politician.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    constituency_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("constituency.id", ondelete="RESTRICT"),
        nullable=True,
    )
    house: Mapped[House] = mapped_column(Enum(House, name="house_enum"), nullable=False)
    from_date: Mapped[date] = mapped_column(Date, nullable=False)
    to_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    lok_sabha_number: Mapped[int | None] = mapped_column(nullable=True)
    state_represented: Mapped[str | None] = mapped_column(String(100), nullable=True)

    politician: Mapped[Politician] = relationship("Politician", back_populates="legislative_terms")
    constituency: Mapped[Constituency] = relationship("Constituency")
    attendance_records: Mapped[list[AttendanceRecord]] = relationship(
        "AttendanceRecord", back_populates="legislative_term"
    )
    legislative_activities: Mapped[list[LegislativeActivity]] = relationship(
        "LegislativeActivity", back_populates="legislative_term"
    )

    def __repr__(self) -> str:
        return f"<LegislativeTerm politician={self.politician_id} house={self.house}>"
