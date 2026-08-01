"""Election and election result models."""

from __future__ import annotations

import enum
import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Date, Enum, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from netacheck.core.database import Base
from netacheck.models.base import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from netacheck.models.affidavit import Affidavit
    from netacheck.models.geography import Constituency
    from netacheck.models.politician import PoliticalParty, Politician


class ElectionType(enum.StrEnum):
    GENERAL = "GENERAL"
    ASSEMBLY = "ASSEMBLY"
    BY_ELECTION = "BY_ELECTION"
    RAJYA_SABHA = "RAJYA_SABHA"


class Election(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "election"

    constituency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("constituency.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    election_type: Mapped[ElectionType] = mapped_column(
        Enum(ElectionType, name="election_type_enum"), nullable=False
    )
    election_date: Mapped[date] = mapped_column(Date, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    phase: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_voters: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_votes_polled: Mapped[int | None] = mapped_column(Integer, nullable=True)

    constituency: Mapped[Constituency] = relationship("Constituency", back_populates="elections")
    results: Mapped[list[ElectionResult]] = relationship(
        "ElectionResult", back_populates="election"
    )

    def __repr__(self) -> str:
        return f"<Election {self.election_type} {self.year}>"


class ElectionResult(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "election_result"

    election_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("election.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    politician_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("politician.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    party_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("political_party.id", ondelete="SET NULL"),
        nullable=True,
    )
    votes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vote_share_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    won: Mapped[bool] = mapped_column(default=False, nullable=False)
    runner_up: Mapped[bool] = mapped_column(default=False, nullable=False)
    margin: Mapped[int | None] = mapped_column(Integer, nullable=True)
    eci_form26_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    election: Mapped[Election] = relationship("Election", back_populates="results")
    politician: Mapped[Politician] = relationship("Politician", back_populates="election_results")
    party: Mapped[PoliticalParty] = relationship("PoliticalParty")
    affidavits: Mapped[list[Affidavit]] = relationship(
        "Affidavit", back_populates="election_result"
    )

    def __repr__(self) -> str:
        return f"<ElectionResult politician={self.politician_id} won={self.won}>"
