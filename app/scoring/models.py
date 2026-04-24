"""
Scoring models: ScoreConfig, PerformanceScore, CompositeScore,
ScoreAdjustment, CalibrationSession.
"""

import json
import uuid as _uuid_mod
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.database import Base
from app.scoring.enums import CalibrationStatus, RatingLabel, ScoreStatus


class _UUIDListType(TypeDecorator):
    """
    Cross-database list-of-UUIDs column.

    On PostgreSQL: stored as a native ARRAY(UUID).
    On SQLite (tests): stored as a JSON text array of UUID strings.
    """

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import ARRAY, UUID as PG_UUID
            return dialect.type_descriptor(ARRAY(PG_UUID(as_uuid=True)))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return [_uuid_mod.UUID(str(v)) if not isinstance(v, _uuid_mod.UUID) else v for v in value]
        return json.dumps([str(v) for v in value])

    def process_result_value(self, value, dialect):
        if value is None:
            return []
        if isinstance(value, list):
            return [_uuid_mod.UUID(str(v)) if not isinstance(v, _uuid_mod.UUID) else v for v in value]
        # SQLite returns a JSON string
        return [_uuid_mod.UUID(v) for v in json.loads(value)]


class ScoreConfig(Base):
    """
    Scoring configuration for an organisation within a review cycle.

    Defines the numeric thresholds that map achievement percentages to
    rating labels (e.g. EXCEPTIONAL ≥ 120 %, EXCEEDS ≥ 100 %, etc.).
    HR admins create one config per cycle; updating a config after scoring
    has run will require a re-compute.
    """

    __tablename__ = "score_configs"

    __table_args__ = (
        UniqueConstraint("organisation_id", "review_cycle_id", name="uq_score_config_org_cycle"),
    )

    id: Mapped[_uuid_mod.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid_mod.uuid4
    )
    organisation_id: Mapped[_uuid_mod.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
    )
    review_cycle_id: Mapped[_uuid_mod.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("review_cycles.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Rating thresholds (achievement %)
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

    # Adjustment settings
    allow_manager_adjustment: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    max_adjustment_points: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("10.00")
    )
    requires_calibration: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
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
    organisation: Mapped["Organisation"] = relationship(  # type: ignore[name-defined]
        "Organisation", foreign_keys=[organisation_id]
    )
    review_cycle: Mapped["ReviewCycle"] = relationship(  # type: ignore[name-defined]
        "ReviewCycle", foreign_keys=[review_cycle_id]
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ScoreConfig org={self.organisation_id} cycle={self.review_cycle_id}>"


class PerformanceScore(Base):
    """
    One row per employee × KPI × review cycle.

    Stores the raw achievement percentage, the weighted score, the
    manager-adjusted score (if any), and the final locked value used
    for composite calculation.  Foreign keys to `kpi_targets`,
    `users`, and `kpis` are all NOT NULL — the user and kpi columns
    are denormalised from the target for fast querying.
    """

    __tablename__ = "performance_scores"

    __table_args__ = (
        UniqueConstraint("target_id", "review_cycle_id", name="uq_perf_score_target_cycle"),
        Index("ix_perf_score_user_cycle", "user_id", "review_cycle_id"),
        Index("ix_perf_score_kpi_cycle", "kpi_id", "review_cycle_id"),
        Index("ix_perf_score_status", "status"),
    )

    id: Mapped[_uuid_mod.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid_mod.uuid4
    )
    target_id: Mapped[_uuid_mod.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("kpi_targets.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Denormalised for query performance
    user_id: Mapped[_uuid_mod.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    kpi_id: Mapped[_uuid_mod.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("kpis.id", ondelete="RESTRICT"),
        nullable=False,
    )
    review_cycle_id: Mapped[_uuid_mod.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("review_cycles.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Score values
    achievement_percentage: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), nullable=False, default=Decimal("0.0000")
    )
    weighted_score: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), nullable=False, default=Decimal("0.0000")
    )
    computed_score: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), nullable=False, default=Decimal("0.0000")
    )
    adjusted_score: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(8, 4), nullable=True
    )
    final_score: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), nullable=False, default=Decimal("0.0000")
    )

    rating: Mapped[RatingLabel] = mapped_column(
        SAEnum(RatingLabel, name="ratinglabel"),
        nullable=False,
        default=RatingLabel.NOT_RATED,
    )
    status: Mapped[ScoreStatus] = mapped_column(
        SAEnum(ScoreStatus, name="scorestatus"),
        nullable=False,
        default=ScoreStatus.COMPUTED,
    )

    computed_at: Mapped[datetime] = mapped_column(
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
    target: Mapped["KPITarget"] = relationship(  # type: ignore[name-defined]
        "KPITarget", foreign_keys=[target_id]
    )
    user: Mapped["User"] = relationship(  # type: ignore[name-defined]
        "User", foreign_keys=[user_id]
    )
    kpi: Mapped["KPI"] = relationship(  # type: ignore[name-defined]
        "KPI", foreign_keys=[kpi_id]
    )
    review_cycle: Mapped["ReviewCycle"] = relationship(  # type: ignore[name-defined]
        "ReviewCycle", foreign_keys=[review_cycle_id]
    )
    adjustments: Mapped[list["ScoreAdjustment"]] = relationship(
        "ScoreAdjustment",
        back_populates="performance_score",
        foreign_keys="ScoreAdjustment.score_id",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<PerformanceScore user={self.user_id} kpi={self.kpi_id} "
            f"cycle={self.review_cycle_id} score={self.final_score}>"
        )


class CompositeScore(Base):
    """
    Overall performance score for one employee in one review cycle.

    Aggregates all individual PerformanceScore rows into a single
    weighted average.  This is the number that appears on the employee's
    performance review form.
    """

    __tablename__ = "composite_scores"

    __table_args__ = (
        UniqueConstraint("user_id", "review_cycle_id", name="uq_composite_user_cycle"),
        Index("ix_composite_score_org_cycle", "organisation_id", "review_cycle_id"),
        Index("ix_composite_score_status", "status"),
    )

    id: Mapped[_uuid_mod.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid_mod.uuid4
    )
    user_id: Mapped[_uuid_mod.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    review_cycle_id: Mapped[_uuid_mod.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("review_cycles.id", ondelete="CASCADE"),
        nullable=False,
    )
    organisation_id: Mapped[_uuid_mod.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Score values
    weighted_average: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), nullable=False, default=Decimal("0.0000")
    )
    final_weighted_average: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), nullable=False, default=Decimal("0.0000")
    )
    rating: Mapped[RatingLabel] = mapped_column(
        SAEnum(RatingLabel, name="ratinglabel"),
        nullable=False,
        default=RatingLabel.NOT_RATED,
    )

    # Coverage stats
    kpi_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    kpis_with_actuals: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    status: Mapped[ScoreStatus] = mapped_column(
        SAEnum(ScoreStatus, name="scorestatus"),
        nullable=False,
        default=ScoreStatus.COMPUTED,
    )

    # Human-readable annotations
    manager_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    calibration_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    computed_at: Mapped[datetime] = mapped_column(
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
    user: Mapped["User"] = relationship(  # type: ignore[name-defined]
        "User", foreign_keys=[user_id]
    )
    review_cycle: Mapped["ReviewCycle"] = relationship(  # type: ignore[name-defined]
        "ReviewCycle", foreign_keys=[review_cycle_id]
    )
    organisation: Mapped["Organisation"] = relationship(  # type: ignore[name-defined]
        "Organisation", foreign_keys=[organisation_id]
    )
    adjustments: Mapped[list["ScoreAdjustment"]] = relationship(
        "ScoreAdjustment",
        back_populates="composite_score",
        foreign_keys="ScoreAdjustment.composite_score_id",
        cascade="all, delete-orphan",
    )
    kpi_scores: Mapped[list["PerformanceScore"]] = relationship(
        "PerformanceScore",
        primaryjoin=(
            "and_(CompositeScore.user_id == foreign(PerformanceScore.user_id), "
            "CompositeScore.review_cycle_id == foreign(PerformanceScore.review_cycle_id))"
        ),
        viewonly=True,
        overlaps="user,review_cycle",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<CompositeScore user={self.user_id} cycle={self.review_cycle_id} "
            f"avg={self.final_weighted_average} rating={self.rating}>"
        )


class ScoreAdjustment(Base):
    """
    Immutable audit trail for every manual change to a PerformanceScore
    or CompositeScore.

    Exactly one of `score_id` or `composite_score_id` must be set.
    `adjustment_type` distinguishes manager reviews from calibration changes.
    """

    __tablename__ = "score_adjustments"

    __table_args__ = (
        Index("ix_score_adj_score", "score_id"),
        Index("ix_score_adj_composite", "composite_score_id"),
    )

    id: Mapped[_uuid_mod.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid_mod.uuid4
    )
    score_id: Mapped[Optional[_uuid_mod.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("performance_scores.id", ondelete="CASCADE"),
        nullable=True,
    )
    composite_score_id: Mapped[Optional[_uuid_mod.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("composite_scores.id", ondelete="CASCADE"),
        nullable=True,
    )
    adjusted_by_id: Mapped[_uuid_mod.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    before_value: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    after_value: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    adjustment_type: Mapped[str] = mapped_column(String(50), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    performance_score: Mapped[Optional["PerformanceScore"]] = relationship(
        "PerformanceScore",
        back_populates="adjustments",
        foreign_keys=[score_id],
    )
    composite_score: Mapped[Optional["CompositeScore"]] = relationship(
        "CompositeScore",
        back_populates="adjustments",
        foreign_keys=[composite_score_id],
    )
    adjusted_by: Mapped["User"] = relationship(  # type: ignore[name-defined]
        "User", foreign_keys=[adjusted_by_id]
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<ScoreAdjustment type={self.adjustment_type} "
            f"by={self.adjusted_by_id} {self.before_value}→{self.after_value}>"
        )


class CalibrationSession(Base):
    """
    A facilitated group calibration exercise for a cohort of employees.

    HR admin creates a session, specifies which user IDs are in scope,
    then reviews/adjusts composite scores during the meeting.  Completing
    the session marks all adjusted scores as CALIBRATED.
    """

    __tablename__ = "calibration_sessions"

    __table_args__ = (
        Index("ix_calibration_session_cycle", "review_cycle_id"),
        Index("ix_calibration_session_org", "organisation_id"),
    )

    id: Mapped[_uuid_mod.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid_mod.uuid4
    )
    review_cycle_id: Mapped[_uuid_mod.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("review_cycles.id", ondelete="CASCADE"),
        nullable=False,
    )
    organisation_id: Mapped[_uuid_mod.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[CalibrationStatus] = mapped_column(
        SAEnum(CalibrationStatus, name="calibrationstatus"),
        nullable=False,
        default=CalibrationStatus.OPEN,
    )
    facilitator_id: Mapped[_uuid_mod.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # List of UUIDs — uses ARRAY(UUID) on PostgreSQL, JSON text on SQLite
    scope_user_ids: Mapped[list] = mapped_column(
        _UUIDListType(), nullable=False, default=list
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    review_cycle: Mapped["ReviewCycle"] = relationship(  # type: ignore[name-defined]
        "ReviewCycle", foreign_keys=[review_cycle_id]
    )
    organisation: Mapped["Organisation"] = relationship(  # type: ignore[name-defined]
        "Organisation", foreign_keys=[organisation_id]
    )
    facilitator: Mapped["User"] = relationship(  # type: ignore[name-defined]
        "User", foreign_keys=[facilitator_id]
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CalibrationSession name={self.name!r} status={self.status}>"
