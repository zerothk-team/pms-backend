from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.actuals.enums import ActualEntrySource, ActualEntryStatus
from app.kpis.enums import MeasurementUnit


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


class ActualEvidenceCreate(BaseModel):
    file_name: str = Field(min_length=1, max_length=255)
    file_url: str = Field(
        min_length=1,
        max_length=1000,
        description="Storage URL (e.g. S3 pre-signed URL or internal path)",
    )
    file_type: str = Field(min_length=1, max_length=50, description="MIME type")


class ActualEvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    file_name: str
    file_url: str
    file_type: str
    uploaded_by_id: UUID
    created_at: datetime


# ---------------------------------------------------------------------------
# KPIActual request schemas
# ---------------------------------------------------------------------------


class KPIActualCreate(BaseModel):
    target_id: UUID
    period_date: date
    actual_value: Decimal
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_actual_value(self) -> "KPIActualCreate":
        # Allow zero and negative values (e.g. cost KPIs can decrease)
        return self


class KPIActualBulkCreate(BaseModel):
    """Submit multiple period actuals at once (catch-up entry)."""

    entries: list[KPIActualCreate] = Field(
        min_length=1,
        max_length=50,
        description="Maximum 50 entries per bulk submission",
    )


class KPIActualUpdate(BaseModel):
    actual_value: Decimal | None = None
    notes: str | None = Field(default=None, max_length=2000)


class KPIActualReview(BaseModel):
    action: Literal["approve", "reject"]
    rejection_reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def require_reason_for_reject(self) -> "KPIActualReview":
        if self.action == "reject" and not self.rejection_reason:
            raise ValueError("rejection_reason is required when rejecting an actual")
        return self


# ---------------------------------------------------------------------------
# KPIActual response schemas
# ---------------------------------------------------------------------------


class KPIActualRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    target_id: UUID
    kpi_id: UUID
    period_date: date
    period_label: str
    actual_value: Decimal
    entry_source: ActualEntrySource
    status: ActualEntryStatus
    notes: str | None
    submitted_by_id: Optional[UUID] = None
    reviewed_by_id: UUID | None
    reviewed_at: datetime | None
    rejection_reason: str | None
    evidence_attachments: list[ActualEvidenceRead]
    created_at: datetime

    # Computed fields populated by service
    achievement_percentage: Decimal | None = None
    vs_milestone: Decimal | None = None  # actual - milestone.expected_value


# ---------------------------------------------------------------------------
# Time series
# ---------------------------------------------------------------------------


class ActualTimeSeriesPoint(BaseModel):
    period_date: date
    period_label: str
    actual_value: Decimal | None           # None = no entry yet for this period
    target_value: Decimal
    milestone_value: Decimal | None        # Expected milestone value if one exists
    achievement_percentage: Decimal | None # None if no actual


class ActualTimeSeries(BaseModel):
    target_id: UUID
    kpi_id: UUID
    kpi_name: str
    kpi_unit: MeasurementUnit
    data_points: list[ActualTimeSeriesPoint]
    overall_achievement: Decimal           # % of annual target achieved to date
    periods_with_data: int
    total_periods: int
