import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.kpis.enums import (
    DataSourceType,
    DepartmentCategory,
    KPIStatus,
    MeasurementFrequency,
    MeasurementUnit,
    ScoringDirection,
)


# ---------------------------------------------------------------------------
# Association tables
# ---------------------------------------------------------------------------

kpi_tag_association = Table(
    "kpi_tag_association",
    Base.metadata,
    Column("kpi_id", UUID(as_uuid=True), ForeignKey("kpis.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", UUID(as_uuid=True), ForeignKey("kpi_tags.id", ondelete="CASCADE"), primary_key=True),
)

kpi_formula_dependency = Table(
    "kpi_formula_dependency",
    Base.metadata,
    Column("parent_kpi_id", UUID(as_uuid=True), ForeignKey("kpis.id", ondelete="CASCADE"), primary_key=True),
    Column("dependency_kpi_id", UUID(as_uuid=True), ForeignKey("kpis.id", ondelete="CASCADE"), primary_key=True),
)


# ---------------------------------------------------------------------------
# KPICategory
# ---------------------------------------------------------------------------

class KPICategory(Base):
    __tablename__ = "kpi_categories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    department: Mapped[DepartmentCategory] = mapped_column(SAEnum(DepartmentCategory, name="departmentcategory"), nullable=False)
    colour_hex: Mapped[str] = mapped_column(String(7), nullable=False, default="#888780")
    organisation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="SET NULL"), nullable=True
    )
    created_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    kpis: Mapped[list["KPI"]] = relationship("KPI", back_populates="category")

    def __repr__(self) -> str:
        return f"<KPICategory id={self.id} name={self.name}>"


# ---------------------------------------------------------------------------
# KPITag
# ---------------------------------------------------------------------------

class KPITag(Base):
    __tablename__ = "kpi_tags"

    __table_args__ = (
        UniqueConstraint("name", "organisation_id", name="uq_kpi_tag_name_org"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    # Relationships
    kpis: Mapped[list["KPI"]] = relationship("KPI", secondary=kpi_tag_association, back_populates="tags")

    def __repr__(self) -> str:
        return f"<KPITag id={self.id} name={self.name}>"


# ---------------------------------------------------------------------------
# KPI
# ---------------------------------------------------------------------------

class KPI(Base):
    __tablename__ = "kpis"

    __table_args__ = (
        UniqueConstraint("organisation_id", "code", name="uq_kpi_org_code"),
        Index("ix_kpi_org_status", "organisation_id", "status"),
        Index("ix_kpi_category", "category_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    unit: Mapped[MeasurementUnit] = mapped_column(SAEnum(MeasurementUnit, name="measurementunit"), nullable=False)
    unit_label: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    currency_code: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    frequency: Mapped[MeasurementFrequency] = mapped_column(SAEnum(MeasurementFrequency, name="measurementfrequency"), nullable=False)
    data_source: Mapped[DataSourceType] = mapped_column(
        SAEnum(DataSourceType, name="datasourcetype"), nullable=False, default=DataSourceType.MANUAL
    )
    formula_expression: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scoring_direction: Mapped[ScoringDirection] = mapped_column(
        SAEnum(ScoringDirection, name="scoringdirection"), nullable=False, default=ScoringDirection.HIGHER_IS_BETTER
    )
    min_value: Mapped[Optional[float]] = mapped_column(Numeric(18, 4), nullable=True)
    max_value: Mapped[Optional[float]] = mapped_column(Numeric(18, 4), nullable=True)
    decimal_places: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    status: Mapped[KPIStatus] = mapped_column(
        SAEnum(KPIStatus, name="kpistatus"), nullable=False, default=KPIStatus.DRAFT
    )
    is_template: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_organisation_wide: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # FKs
    category_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kpi_categories.id", ondelete="SET NULL"), nullable=True
    )
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    approved_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    deprecated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Optional per-KPI scoring config (overrides cycle-level config)
    scoring_config_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("kpi_scoring_configs.id", ondelete="SET NULL"),
        nullable=True,
        comment="Default scoring config for this KPI. Overridden by target-level config.",
    )

    # Relationships
    category: Mapped[Optional["KPICategory"]] = relationship("KPICategory", back_populates="kpis")
    tags: Mapped[list["KPITag"]] = relationship(
        "KPITag", secondary=kpi_tag_association, back_populates="kpis"
    )
    organisation: Mapped["Organisation"] = relationship(  # type: ignore[name-defined]
        "Organisation", foreign_keys=[organisation_id]
    )
    scoring_config: Mapped[Optional["KPIScoringConfig"]] = relationship(  # type: ignore[name-defined]
        "KPIScoringConfig", foreign_keys=[scoring_config_id]
    )
    created_by: Mapped["User"] = relationship(  # type: ignore[name-defined]
        "User", foreign_keys=[created_by_id]
    )
    approved_by: Mapped[Optional["User"]] = relationship(  # type: ignore[name-defined]
        "User", foreign_keys=[approved_by_id]
    )
    formula_dependencies: Mapped[list["KPI"]] = relationship(
        "KPI",
        secondary=kpi_formula_dependency,
        primaryjoin="KPI.id == kpi_formula_dependency.c.parent_kpi_id",
        secondaryjoin="KPI.id == kpi_formula_dependency.c.dependency_kpi_id",
    )
    variables: Mapped[list["KPIVariable"]] = relationship(  # type: ignore[name-defined]
        "KPIVariable",
        back_populates="kpi",
        order_by="KPIVariable.display_order",
        cascade="all, delete-orphan",
    )
    history: Mapped[list["KPIHistory"]] = relationship(
        "KPIHistory", back_populates="kpi", order_by="KPIHistory.version"
    )

    def __repr__(self) -> str:
        return f"<KPI id={self.id} code={self.code}>"


# ---------------------------------------------------------------------------
# KPIHistory
# ---------------------------------------------------------------------------

class KPIHistory(Base):
    __tablename__ = "kpi_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kpi_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kpis.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    change_summary: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    changed_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    # Relationships
    kpi: Mapped["KPI"] = relationship("KPI", back_populates="history")

    def __repr__(self) -> str:
        return f"<KPIHistory id={self.id} kpi_id={self.kpi_id} version={self.version}>"


# ---------------------------------------------------------------------------
# KPITemplate
# ---------------------------------------------------------------------------

class KPITemplate(Base):
    __tablename__ = "kpi_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    department: Mapped[DepartmentCategory] = mapped_column(SAEnum(DepartmentCategory, name="departmentcategory"), nullable=False)
    unit: Mapped[MeasurementUnit] = mapped_column(SAEnum(MeasurementUnit, name="measurementunit"), nullable=False)
    frequency: Mapped[MeasurementFrequency] = mapped_column(SAEnum(MeasurementFrequency, name="measurementfrequency"), nullable=False)
    scoring_direction: Mapped[ScoringDirection] = mapped_column(SAEnum(ScoringDirection, name="scoringdirection"), nullable=False)
    suggested_formula: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # JSON list of tag name strings — compatible with both PostgreSQL and SQLite
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    def __repr__(self) -> str:
        return f"<KPITemplate id={self.id} name={self.name}>"
