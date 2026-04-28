import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.targets.enums import TargetLevel, TargetStatus


class KPITarget(Base):
    __tablename__ = "kpi_targets"

    __table_args__ = (
        # Enforce one individual target per KPI per cycle per user at DB level
        # (PostgreSQL unique index on individual targets is added in migration)
        Index("ix_kpi_target_review_cycle", "review_cycle_id"),
        Index("ix_kpi_target_assignee_user", "assignee_user_id"),
        Index("ix_kpi_target_kpi", "kpi_id"),
        Index("ix_kpi_target_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    kpi_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kpis.id", ondelete="RESTRICT"), nullable=False
    )
    review_cycle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("review_cycles.id", ondelete="CASCADE"),
        nullable=False,
    )
    assignee_type: Mapped[TargetLevel] = mapped_column(
        SAEnum(TargetLevel, name="targetlevel"), nullable=False
    )
    assignee_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    assignee_org_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=True,
    )

    target_value: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    stretch_target_value: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(18, 4), nullable=True
    )
    minimum_value: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(18, 4), nullable=True
    )
    weight: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("100.00")
    )
    status: Mapped[TargetStatus] = mapped_column(
        SAEnum(TargetStatus, name="targetstatus"),
        nullable=False,
        default=TargetStatus.DRAFT,
    )

    cascade_parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("kpi_targets.id", ondelete="SET NULL"),
        nullable=True,
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Target-level scoring config override — highest precedence
    scoring_config_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("kpi_scoring_configs.id", ondelete="SET NULL"),
        nullable=True,
        comment="Target-level override. Highest precedence. Falls back to KPI's config, then cycle config.",
    )

    set_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    acknowledged_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    locked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
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
    kpi: Mapped["KPI"] = relationship(  # type: ignore[name-defined]
        "KPI", foreign_keys=[kpi_id]
    )
    scoring_config: Mapped[Optional["KPIScoringConfig"]] = relationship(  # type: ignore[name-defined]
        "KPIScoringConfig", foreign_keys=[scoring_config_id]
    )
    review_cycle: Mapped["ReviewCycle"] = relationship(  # type: ignore[name-defined]
        "ReviewCycle", back_populates="targets"
    )
    assignee_user: Mapped[Optional["User"]] = relationship(  # type: ignore[name-defined]
        "User", foreign_keys=[assignee_user_id]
    )
    set_by: Mapped["User"] = relationship(  # type: ignore[name-defined]
        "User", foreign_keys=[set_by_id]
    )
    acknowledged_by: Mapped[Optional["User"]] = relationship(  # type: ignore[name-defined]
        "User", foreign_keys=[acknowledged_by_id]
    )
    cascade_parent: Mapped[Optional["KPITarget"]] = relationship(
        "KPITarget",
        remote_side="KPITarget.id",
        foreign_keys=[cascade_parent_id],
        back_populates="cascade_children",
    )
    cascade_children: Mapped[list["KPITarget"]] = relationship(
        "KPITarget",
        foreign_keys=[cascade_parent_id],
        back_populates="cascade_parent",
    )
    milestones: Mapped[list["TargetMilestone"]] = relationship(
        "TargetMilestone",
        back_populates="target",
        cascade="all, delete-orphan",
        order_by="TargetMilestone.milestone_date",
    )
    actuals: Mapped[list["KPIActual"]] = relationship(  # type: ignore[name-defined]
        "KPIActual", back_populates="target", order_by="KPIActual.period_date"
    )

    def __repr__(self) -> str:
        return f"<KPITarget id={self.id} kpi_id={self.kpi_id} status={self.status}>"


class TargetMilestone(Base):
    __tablename__ = "target_milestones"

    __table_args__ = (
        Index("ix_target_milestone_target", "target_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("kpi_targets.id", ondelete="CASCADE"),
        nullable=False,
    )
    milestone_date: Mapped[date] = mapped_column(Date, nullable=False)
    expected_value: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    label: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    target: Mapped["KPITarget"] = relationship("KPITarget", back_populates="milestones")

    def __repr__(self) -> str:
        return (
            f"<TargetMilestone id={self.id} target_id={self.target_id} "
            f"date={self.milestone_date}>"
        )
