"""Asset declaration model."""

from __future__ import annotations

import enum
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from netacheck.core.database import Base
from netacheck.models.base import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from netacheck.models.affidavit import AffidavitEntry


class AssetCategory(enum.StrEnum):
    IMMOVABLE = "IMMOVABLE"
    MOVABLE = "MOVABLE"
    FINANCIAL = "FINANCIAL"
    LIABILITY = "LIABILITY"
    OTHER = "OTHER"


class AssetOwnership(enum.StrEnum):
    SELF = "SELF"
    SPOUSE = "SPOUSE"
    DEPENDENT = "DEPENDENT"
    HUF = "HUF"
    OTHER = "OTHER"


class AssetDeclaration(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single asset line item from a candidate's affidavit."""

    __tablename__ = "asset_declaration"

    affidavit_entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("affidavit_entry.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    category: Mapped[AssetCategory] = mapped_column(
        Enum(AssetCategory, name="asset_category_enum"), nullable=False
    )
    ownership: Mapped[AssetOwnership] = mapped_column(
        Enum(AssetOwnership, name="asset_ownership_enum"),
        default=AssetOwnership.SELF,
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_inr: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    raw_value_text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    location: Mapped[str | None] = mapped_column(String(500), nullable=True)

    affidavit_entry: Mapped[AffidavitEntry] = relationship(
        "AffidavitEntry", back_populates="asset_declarations"
    )

    def __repr__(self) -> str:
        return f"<AssetDeclaration {self.category} ₹{self.value_inr}>"
