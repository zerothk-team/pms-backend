"""Pydantic schemas for KPIVariable, VariableActual, and integration endpoints."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.integrations.enums import SyncStatus, VariableDataType, VariableSourceType
from app.kpis.enums import MeasurementFrequency


# ---------------------------------------------------------------------------
# KPIVariable — request schemas
# ---------------------------------------------------------------------------

class KPIVariableCreate(BaseModel):
    variable_name: str = Field(
        min_length=1,
        max_length=50,
        pattern=r"^[A-Z][A-Z0-9_]{0,49}$",
        description="Uppercase identifier used in formula. E.g. REVENUE",
    )
    display_label: str = Field(min_length=1, max_length=150)
    description: str | None = None
    data_type: VariableDataType = VariableDataType.NUMBER
    unit_label: str | None = Field(default=None, max_length=50)
    source_type: VariableSourceType = VariableSourceType.MANUAL
    source_config: dict | None = None
    is_required: bool = True
    default_value: Decimal | None = None
    auto_sync_enabled: bool = True
    sync_frequency: MeasurementFrequency | None = None
    display_order: int = 0


class KPIVariableUpdate(BaseModel):
    display_label: str | None = Field(default=None, min_length=1, max_length=150)
    description: str | None = None
    data_type: VariableDataType | None = None
    unit_label: str | None = None
    source_type: VariableSourceType | None = None
    source_config: dict | None = None
    is_required: bool | None = None
    default_value: Decimal | None = None
    auto_sync_enabled: bool | None = None
    sync_frequency: MeasurementFrequency | None = None
    display_order: int | None = None


class KPIVariableReorder(BaseModel):
    """PATCH /kpis/{kpi_id}/variables/reorder — update display_order for multiple vars."""
    variable_orders: list[dict[str, int]] = Field(
        description="List of {id: <uuid>, order: <int>} mappings"
    )


# ---------------------------------------------------------------------------
# KPIVariable — response schemas
# ---------------------------------------------------------------------------

class KPIVariableRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kpi_id: UUID
    variable_name: str
    display_label: str
    description: str | None
    data_type: VariableDataType
    unit_label: str | None
    source_type: VariableSourceType
    source_config: dict | None
    is_required: bool
    default_value: Decimal | None
    auto_sync_enabled: bool
    sync_frequency: MeasurementFrequency | None
    last_synced_at: datetime | None
    last_sync_status: SyncStatus
    last_sync_error: str | None
    display_order: int
    organisation_id: UUID
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime | None


class VariableWithCurrentValue(KPIVariableRead):
    """KPIVariableRead extended with the current period's resolved value."""
    current_value: Decimal | None = None
    current_period: str | None = None
    synced_minutes_ago: int | None = None
    needs_manual_entry: bool = False


# ---------------------------------------------------------------------------
# VariableActual — request/response schemas
# ---------------------------------------------------------------------------

class ManualVariableEntry(BaseModel):
    """POST /actuals/variables/ — submit a manual value for one variable."""
    variable_id: UUID
    kpi_id: UUID
    period_date: date
    raw_value: Decimal = Field(ge=0)
    notes: str | None = None


class BulkManualEntry(BaseModel):
    """POST multiple manual variable values at once."""
    entries: list[ManualVariableEntry]


class VariableActualRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    variable_id: UUID
    kpi_id: UUID
    period_date: date
    raw_value: Decimal
    source_type: VariableSourceType
    sync_metadata: dict | None
    submitted_by_id: UUID | None
    is_current: bool
    created_at: datetime


class BulkSyncResult(BaseModel):
    kpi_id: UUID
    period_date: date
    synced_count: int
    failed_count: int
    results: dict[str, str]
    """variable_name → 'synced' | 'failed: <reason>' | 'skipped'"""


# ---------------------------------------------------------------------------
# Variable status (for status endpoint)
# ---------------------------------------------------------------------------

class VariableStatusRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    variable_id: UUID
    variable_name: str
    source_type: VariableSourceType
    last_sync_status: SyncStatus
    last_synced_at: datetime | None
    has_value_for_period: bool


# ---------------------------------------------------------------------------
# Webhook push
# ---------------------------------------------------------------------------

class WebhookPushPayload(BaseModel):
    """POST /integrations/push/{endpoint_key}"""
    value: Decimal
    period: str = Field(
        description="Period in YYYY-MM format",
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
    )
    source: str | None = Field(default=None, max_length=100)
    metadata: dict | None = None

    @field_validator("period")
    @classmethod
    def parse_period(cls, v: str) -> str:
        return v  # Validated by pattern


# ---------------------------------------------------------------------------
# Formula validation
# ---------------------------------------------------------------------------

class FormulaValidationRequest(BaseModel):
    expression: str = Field(min_length=1)


class FormulaValidationResponse(BaseModel):
    valid: bool
    errors: list[str]
    referenced_variables: list[str]
    defined_variables: list[str]
    undefined_in_formula: list[str]


# ---------------------------------------------------------------------------
# Adapter test
# ---------------------------------------------------------------------------

class AdapterTestRequest(BaseModel):
    adapter_name: str
    source_config: dict
    period_date: date


class AdapterTestResult(BaseModel):
    success: bool
    value: Decimal | None = None
    error: str | None = None
    metadata: dict | None = None
    elapsed_ms: int | None = None
