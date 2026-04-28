"""
SQLAlchemy models for KPI formula variables and their audit trail.
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base
from app.integrations.enums import SyncStatus, VariableDataType, VariableSourceType
from app.kpis.enums import MeasurementFrequency


class KPIVariable(Base):
    """
    A named, typed slot in a KPI formula.

    Example: formula "(REVENUE - EXPENSES) / REVENUE * 100" has variables:
      - REVENUE   (source: rest_api → ERP endpoint)
      - EXPENSES  (source: manual  → employee enters)

    The formula_expression in the KPI references these by variable_name.
    """

    __tablename__ = "kpi_variables"

    __table_args__ = (
        UniqueConstraint("kpi_id", "variable_name", name="uq_kpi_variable_name"),
        # NOTE: PostgreSQL-only regex CHECK constraint is enforced via Alembic migration
        # and Pydantic field validation (pattern=r"^[A-Z][A-Z0-9_]{0,49}$").
        # Omitted here to keep model SQLite-compatible for tests.
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    kpi_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("kpis.id", ondelete="CASCADE"),
        nullable=False,
    )
    variable_name: Mapped[str] = mapped_column(
        String(50), nullable=False
    )
    # ^ MUST match what appears in the formula: uppercase, no spaces, e.g. "REVENUE"

    display_label: Mapped[str] = mapped_column(String(150), nullable=False)
    # ^ Human-readable: "Total Monthly Revenue (MYR)"

    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    data_type: Mapped[VariableDataType] = mapped_column(
        SAEnum(VariableDataType, name="variabledatatype"),
        nullable=False,
        default=VariableDataType.NUMBER,
    )
    unit_label: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # ^ e.g. "MYR", "units", "hours"

    source_type: Mapped[VariableSourceType] = mapped_column(
        SAEnum(VariableSourceType, name="variablesourcetype"),
        nullable=False,
        default=VariableSourceType.MANUAL,
    )
    source_config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # ^ Adapter-specific configuration. MUST NOT contain raw credentials.

    is_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # ^ If True: formula eval fails if this variable has no value for the period
    # ^ If False: formula uses default_value when variable is missing

    default_value: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(18, 4), nullable=True
    )
    # ^ Used when is_required=False and no value is available

    auto_sync_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # ^ For non-manual sources: whether to auto-pull on scheduled job

    sync_frequency: Mapped[Optional[MeasurementFrequency]] = mapped_column(
        SAEnum(MeasurementFrequency, name="measurementfrequency"),
        nullable=True,
    )
    # ^ How often to sync. If null: syncs when formula eval is triggered

    last_synced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_sync_status: Mapped[SyncStatus] = mapped_column(
        SAEnum(SyncStatus, name="syncstatus"),
        default=SyncStatus.NEVER_SYNCED,
        nullable=False,
    )
    last_sync_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # ^ Order variables appear in the manual entry UI

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        onupdate=func.now(),
        nullable=True,
    )

    # Relationships
    kpi: Mapped["KPI"] = relationship(  # type: ignore[name-defined]
        "KPI", back_populates="variables"
    )
    actuals: Mapped[list["VariableActual"]] = relationship(
        "VariableActual",
        back_populates="variable",
        order_by="VariableActual.period_date",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<KPIVariable {self.variable_name} kpi={self.kpi_id} source={self.source_type}>"


class VariableActual(Base):
    """
    A raw data value for one variable for one period.

    Every value that goes into a formula computation is stored here.
    This provides a complete audit trail — you can always see exactly
    which numbers were used to compute any KPI actual.
    """

    __tablename__ = "variable_actuals"

    __table_args__ = (
        Index("ix_variable_actuals_var_period", "variable_id", "period_date"),
        Index("ix_variable_actuals_kpi_period", "kpi_id", "period_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    variable_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("kpi_variables.id", ondelete="CASCADE"),
        nullable=False,
    )
    kpi_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("kpis.id", ondelete="CASCADE"),
        nullable=False,
    )
    # ^ Denormalised for faster queries

    period_date: Mapped[date] = mapped_column(Date, nullable=False)
    raw_value: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    source_type: Mapped[VariableSourceType] = mapped_column(
        SAEnum(VariableSourceType, name="variablesourcetype"),
        nullable=False,
    )
    sync_metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # ^ Audit info: {"adapter": "rest_api", "url": "...", "response_time_ms": 342, ...}

    submitted_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # ^ null for auto-synced values

    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # ^ False when superseded by a re-sync or correction for same period

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    variable: Mapped["KPIVariable"] = relationship(
        "KPIVariable", back_populates="actuals"
    )

    def __repr__(self) -> str:
        return (
            f"<VariableActual variable={self.variable_id} "
            f"period={self.period_date} value={self.raw_value}>"
        )
