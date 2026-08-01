"""Geographic models: State and Constituency."""

from __future__ import annotations

import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from netacheck.core.database import Base
from netacheck.models.base import SlugMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from netacheck.models.election import Election


class ConstituencyType(enum.StrEnum):
    LOK_SABHA = "LOK_SABHA"
    VIDHAN_SABHA = "VIDHAN_SABHA"
    RAJYA_SABHA = "RAJYA_SABHA"


class State(UUIDPrimaryKeyMixin, SlugMixin, TimestampMixin, Base):
    __tablename__ = "state"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    iso_code: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)
    is_union_territory: Mapped[bool] = mapped_column(default=False, nullable=False)

    constituencies: Mapped[list[Constituency]] = relationship(
        "Constituency", back_populates="state", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<State {self.name} ({self.iso_code})>"


class Constituency(UUIDPrimaryKeyMixin, SlugMixin, TimestampMixin, Base):
    __tablename__ = "constituency"

    state_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("state.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    constituency_type: Mapped[ConstituencyType] = mapped_column(
        Enum(ConstituencyType, name="constituency_type_enum"), nullable=False
    )
    number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reserved_category: Mapped[str | None] = mapped_column(String(50), nullable=True)

    state: Mapped[State] = relationship("State", back_populates="constituencies")
    elections: Mapped[list[Election]] = relationship("Election", back_populates="constituency")

    def __repr__(self) -> str:
        return f"<Constituency {self.name} ({self.constituency_type})>"
