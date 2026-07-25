"""Politician identity models."""

from __future__ import annotations

import enum
import uuid
from datetime import date

from sqlalchemy import Date, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from netacheck.core.database import Base
from netacheck.models.base import SlugMixin, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Gender(str, enum.Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"
    OTHER = "OTHER"
    UNDISCLOSED = "UNDISCLOSED"


class House(str, enum.Enum):
    LOK_SABHA = "LOK_SABHA"
    RAJYA_SABHA = "RAJYA_SABHA"
    VIDHAN_SABHA = "VIDHAN_SABHA"
    VIDHAN_PARISHAD = "VIDHAN_PARISHAD"


class PoliticalParty(UUIDPrimaryKeyMixin, SlugMixin, TimestampMixin, Base):
    __tablename__ = "political_party"

    name: Mapped[str] = mapped_column(String(300), nullable=False)
    abbreviation: Mapped[str | None] = mapped_column(String(30), nullable=True)
    eci_id: Mapped[str | None] = mapped_column(String(50), unique=True, nullable=True)
    symbol_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_national_party: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    memberships: Mapped[list["PartyMembership"]] = relationship(
        "PartyMembership", back_populates="party"
    )

    def __repr__(self) -> str:
        return f"<PoliticalParty {self.abbreviation or self.name}>"


class Politician(UUIDPrimaryKeyMixin, SlugMixin, SoftDeleteMixin, TimestampMixin, Base):
    __tablename__ = "politician"

    name: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    name_hindi: Mapped[str | None] = mapped_column(String(300), nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    gender: Mapped[Gender] = mapped_column(
        Enum(Gender, name="gender_enum"),
        default=Gender.UNDISCLOSED,
        nullable=False,
    )
    photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    official_website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    eci_candidate_id: Mapped[str | None] = mapped_column(String(50), unique=True, nullable=True)
    pan_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)

    aliases: Mapped[list["PoliticianAlias"]] = relationship(
        "PoliticianAlias", back_populates="politician", lazy="selectin"
    )
    party_memberships: Mapped[list["PartyMembership"]] = relationship(
        "PartyMembership", back_populates="politician", lazy="selectin"
    )
    legislative_terms: Mapped[list["LegislativeTerm"]] = relationship(  # type: ignore[name-defined]
        "LegislativeTerm", back_populates="politician"
    )
    election_results: Mapped[list["ElectionResult"]] = relationship(  # type: ignore[name-defined]
        "ElectionResult", back_populates="politician"
    )
    grade_snapshots: Mapped[list["GradeSnapshot"]] = relationship(  # type: ignore[name-defined]
        "GradeSnapshot", back_populates="politician"
    )

    def __repr__(self) -> str:
        return f"<Politician {self.name} ({self.slug})>"


class PoliticianAlias(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "politician_alias"

    politician_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("politician.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    alias: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)

    politician: Mapped["Politician"] = relationship("Politician", back_populates="aliases")

    def __repr__(self) -> str:
        return f"<PoliticianAlias {self.alias}>"


class PartyMembership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "party_membership"

    politician_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("politician.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    party_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("political_party.id", ondelete="RESTRICT"),
        nullable=False,
    )
    from_date: Mapped[date] = mapped_column(Date, nullable=False)
    to_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_primary: Mapped[bool] = mapped_column(default=True, nullable=False)

    politician: Mapped["Politician"] = relationship("Politician", back_populates="party_memberships")
    party: Mapped["PoliticalParty"] = relationship("PoliticalParty", back_populates="memberships")

    def __repr__(self) -> str:
        return f"<PartyMembership politician={self.politician_id} party={self.party_id}>"
