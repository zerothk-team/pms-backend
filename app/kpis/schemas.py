from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.kpis.enums import (
    DataSourceType,
    DepartmentCategory,
    KPIStatus,
    MeasurementFrequency,
    MeasurementUnit,
    ScoringDirection,
)


# ---------------------------------------------------------------------------
# KPICategory
# ---------------------------------------------------------------------------

class KPICategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    department: DepartmentCategory
    colour_hex: str = Field(default="#888780", pattern=r"^#[0-9A-Fa-f]{6}$")


class KPICategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    colour_hex: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")


class KPICategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    department: DepartmentCategory
    colour_hex: str
    organisation_id: UUID | None
    created_at: datetime


# ---------------------------------------------------------------------------
# KPITag
# ---------------------------------------------------------------------------

class KPITagRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str


# ---------------------------------------------------------------------------
# KPI – Request schemas
# ---------------------------------------------------------------------------

class KPICreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    code: str = Field(min_length=2, max_length=50, pattern=r"^[A-Z0-9_]+$")
    description: str | None = None
    unit: MeasurementUnit
    unit_label: str | None = None
    currency_code: str | None = Field(default=None, min_length=3, max_length=3)
    frequency: MeasurementFrequency
    data_source: DataSourceType = DataSourceType.MANUAL
    formula_expression: str | None = None
    scoring_direction: ScoringDirection = ScoringDirection.HIGHER_IS_BETTER
    min_value: Decimal | None = None
    max_value: Decimal | None = None
    decimal_places: int = Field(default=2, ge=0, le=6)
    category_id: UUID | None = None
    tag_ids: list[UUID] = Field(default_factory=list)
    is_organisation_wide: bool = False

    @model_validator(mode="after")
    def validate_formula_fields(self) -> "KPICreate":
        if self.data_source == DataSourceType.FORMULA and not self.formula_expression:
            raise ValueError("formula_expression is required when data_source is FORMULA")
        if self.data_source != DataSourceType.FORMULA and self.formula_expression:
            raise ValueError("formula_expression must be null when data_source is not FORMULA")
        return self


class KPIUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    formula_expression: str | None = None
    scoring_direction: ScoringDirection | None = None
    min_value: Decimal | None = None
    max_value: Decimal | None = None
    decimal_places: int | None = Field(default=None, ge=0, le=6)
    category_id: UUID | None = None
    tag_ids: list[UUID] | None = None
    change_summary: str | None = Field(
        default=None,
        max_length=500,
        description="Required when modifying formula_expression",
    )


class KPIStatusUpdate(BaseModel):
    status: KPIStatus
    reason: str | None = Field(default=None, max_length=500)


class KPICloneFromTemplate(BaseModel):
    template_id: UUID
    name: str | None = None
    code: str = Field(pattern=r"^[A-Z0-9_]+$")
    category_id: UUID | None = None


# ---------------------------------------------------------------------------
# KPI – Response schemas
# ---------------------------------------------------------------------------

class KPIRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    code: str
    description: str | None
    unit: MeasurementUnit
    unit_label: str | None
    currency_code: str | None
    frequency: MeasurementFrequency
    data_source: DataSourceType
    formula_expression: str | None
    scoring_direction: ScoringDirection
    min_value: Decimal | None
    max_value: Decimal | None
    decimal_places: int
    status: KPIStatus
    is_template: bool
    is_organisation_wide: bool
    version: int
    category: KPICategoryRead | None
    tags: list[KPITagRead]
    organisation_id: UUID
    created_by_id: UUID
    approved_by_id: UUID | None
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class KPIReadWithDependencies(KPIRead):
    formula_dependencies: list[KPIRead] = Field(default_factory=list)


class KPIHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    version: int
    change_summary: str | None
    snapshot: dict
    changed_by_id: UUID
    changed_at: datetime


class KPITemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    department: DepartmentCategory
    unit: MeasurementUnit
    frequency: MeasurementFrequency
    scoring_direction: ScoringDirection
    suggested_formula: str | None
    tags: list[str]
    usage_count: int


class PaginatedKPIs(BaseModel):
    items: list[KPIRead]
    total: int
    page: int
    size: int
    pages: int


# ---------------------------------------------------------------------------
# Formula validation response
# ---------------------------------------------------------------------------

class FormulaValidationResponse(BaseModel):
    valid: bool
    referenced_codes: list[str]
    errors: list[str]


class FormulaValidationRequest(BaseModel):
    expression: str = Field(min_length=1)
