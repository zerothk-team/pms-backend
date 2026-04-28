"""
KPIScoringConfig model — per-KPI or per-target scoring threshold overrides.

Precedence (highest wins):
  target.scoring_config_id  >  kpi.scoring_config_id  >  cycle ScoreConfig
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.scoring.enums import ScoringPreset


class KPIScoringConfig(Base):
    """
    Per-KPI or per-target scoring threshold configuration.

    Business rule: all _min values must be strictly descending:
      exceptional_min > exceeds_min > meets_min > partially_meets_min >= 0
    """

    __tablename__ = "kpi_scoring_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    preset: Mapped[ScoringPreset] = mapped_column(
        SAEnum(ScoringPreset, name="scoringpreset"),
        nullable=False,
        default=ScoringPreset.CUSTOM,
    )

    # nullable org_id = system-wide preset (read-only, seeded by system)
    organisation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=True,
    )

    # Threshold values — achievement % required to reach each rating
    exceptional_min: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, default=Decimal("120.00")
    )
    exceeds_min: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, default=Decimal("100.00")
    )
    meets_min: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, default=Decimal("80.00")
    )
    partially_meets_min: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, default=Decimal("60.00")
    )
    does_not_meet_min: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, default=Decimal("0.00")
    )

    # Cap: achievement % above this is capped before scoring (prevents gaming)
    achievement_cap: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, default=Decimal("200.00")
    )

    # Optional: require justification if score is manually adjusted beyond this %
    adjustment_justification_threshold: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), nullable=True
    )

    is_system_preset: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    organisation: Mapped[Optional["Organisation"]] = relationship(  # type: ignore[name-defined]
        "Organisation", foreign_keys=[organisation_id]
    )
    created_by: Mapped[Optional["User"]] = relationship(  # type: ignore[name-defined]
        "User", foreign_keys=[created_by_id]
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<KPIScoringConfig id={self.id} name={self.name} preset={self.preset}>"
