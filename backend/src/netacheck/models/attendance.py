"""Parliamentary attendance record model."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from netacheck.core.database import Base
from netacheck.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class AttendanceRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Attendance for a politician during a parliamentary session."""

    __tablename__ = "attendance_record"

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
    session_name: Mapped[str] = mapped_column(String(100), nullable=False)
    session_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    days_present: Mapped[int] = mapped_column(Integer, nullable=False)
    days_total: Mapped[int] = mapped_column(Integer, nullable=False)
    attendance_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    legislative_term: Mapped["LegislativeTerm"] = relationship(  # type: ignore[name-defined]
        "LegislativeTerm", back_populates="attendance_records"
    )
    source_snapshot: Mapped["SourceSnapshot"] = relationship("SourceSnapshot")  # type: ignore[name-defined]

    def __repr__(self) -> str:
        return f"<AttendanceRecord {self.session_name} {self.days_present}/{self.days_total}>"
