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

from app.actuals.enums import ActualEntrySource, ActualEntryStatus
from app.database import Base


class KPIActual(Base):
    __tablename__ = "kpi_actuals"

    __table_args__ = (
        # One active (non-superseded) actual per target per period enforced
        # at the service layer. A partial unique index is also added in the
        # Alembic migration for PostgreSQL:
        #   UNIQUE (target_id, period_date) WHERE status != 'superseded'
        Index("ix_kpi_actual_target_period", "target_id", "period_date"),
        Index("ix_kpi_actual_kpi", "kpi_id"),
        Index("ix_kpi_actual_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("kpi_targets.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Denormalised for query performance — avoids joining through kpi_targets
    kpi_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kpis.id", ondelete="RESTRICT"), nullable=False
    )

    period_date: Mapped[date] = mapped_column(Date, nullable=False)
    period_label: Mapped[str] = mapped_column(String(50), nullable=False)
    actual_value: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)

    entry_source: Mapped[ActualEntrySource] = mapped_column(
        SAEnum(ActualEntrySource, name="actualentrysource"),
        nullable=False,
        default=ActualEntrySource.MANUAL,
    )
    status: Mapped[ActualEntryStatus] = mapped_column(
        SAEnum(ActualEntryStatus, name="actualentrystatus"),
        nullable=False,
        default=ActualEntryStatus.APPROVED,
    )

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    submitted_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

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
    target: Mapped["KPITarget"] = relationship(  # type: ignore[name-defined]
        "KPITarget", back_populates="actuals"
    )
    kpi: Mapped["KPI"] = relationship(  # type: ignore[name-defined]
        "KPI", foreign_keys=[kpi_id]
    )
    submitted_by: Mapped[Optional["User"]] = relationship(  # type: ignore[name-defined]
        "User", foreign_keys=[submitted_by_id]
    )
    reviewed_by: Mapped[Optional["User"]] = relationship(  # type: ignore[name-defined]
        "User", foreign_keys=[reviewed_by_id]
    )
    evidence_attachments: Mapped[list["ActualEvidence"]] = relationship(
        "ActualEvidence",
        back_populates="actual",
        cascade="all, delete-orphan",
        order_by="ActualEvidence.created_at",
    )

    def __repr__(self) -> str:
        return (
            f"<KPIActual id={self.id} target={self.target_id} "
            f"period={self.period_date} status={self.status}>"
        )


class ActualEvidence(Base):
    """File evidence attached to an actual submission."""

    __tablename__ = "actual_evidence"

    __table_args__ = (
        Index("ix_actual_evidence_actual", "actual_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    actual_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("kpi_actuals.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)
    uploaded_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    actual: Mapped["KPIActual"] = relationship(
        "KPIActual", back_populates="evidence_attachments"
    )
    uploaded_by: Mapped["User"] = relationship(  # type: ignore[name-defined]
        "User", foreign_keys=[uploaded_by_id]
    )

    def __repr__(self) -> str:
        return f"<ActualEvidence id={self.id} actual_id={self.actual_id} file={self.file_name}>"
