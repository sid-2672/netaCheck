"""Criminal case model."""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from netacheck.core.database import Base
from netacheck.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class CaseStatus(str, enum.Enum):
    PENDING = "PENDING"
    CHARGE_FRAMED = "CHARGE_FRAMED"
    CONVICTED = "CONVICTED"
    ACQUITTED = "ACQUITTED"
    DISCHARGED = "DISCHARGED"
    COMPOUNDED = "COMPOUNDED"
    UNKNOWN = "UNKNOWN"


class Severity(str, enum.Enum):
    HEINOUS = "HEINOUS"
    SERIOUS = "SERIOUS"
    MINOR = "MINOR"
    UNKNOWN = "UNKNOWN"


class CriminalCase(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A criminal case declared in an election affidavit."""

    __tablename__ = "criminal_case"

    affidavit_entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("affidavit_entry.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    case_number: Mapped[str | None] = mapped_column(String(200), nullable=True)
    court: Mapped[str | None] = mapped_column(String(300), nullable=True)
    section_of_law: Mapped[str | None] = mapped_column(Text, nullable=True)
    offence_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[CaseStatus] = mapped_column(
        Enum(CaseStatus, name="case_status_enum"),
        default=CaseStatus.UNKNOWN,
        nullable=False,
    )
    severity: Mapped[Severity] = mapped_column(
        Enum(Severity, name="case_severity_enum"),
        default=Severity.UNKNOWN,
        nullable=False,
    )
    year_filed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_cognizable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    affidavit_entry: Mapped["AffidavitEntry"] = relationship(  # type: ignore[name-defined]
        "AffidavitEntry", back_populates="criminal_cases"
    )

    def __repr__(self) -> str:
        return f"<CriminalCase {self.case_number} status={self.status}>"
