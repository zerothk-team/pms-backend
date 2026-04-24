"""
Pydantic v2 schemas for the scoring and calibration module.
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.scoring.enums import CalibrationStatus, RatingLabel, ScoreStatus


# ---------------------------------------------------------------------------
# ScoreConfig
# ---------------------------------------------------------------------------


class ScoreConfigCreate(BaseModel):
    review_cycle_id: UUID

    exceptional_min: Decimal = Field(
        default=Decimal("120.00"),
        ge=0,
        le=500,
        description="Minimum achievement % for EXCEPTIONAL rating",
    )
    exceeds_min: Decimal = Field(
        default=Decimal("100.00"),
        ge=0,
        le=500,
        description="Minimum achievement % for EXCEEDS_EXPECTATIONS",
    )
    meets_min: Decimal = Field(
        default=Decimal("80.00"),
        ge=0,
        le=500,
        description="Minimum achievement % for MEETS_EXPECTATIONS",
    )
    partially_meets_min: Decimal = Field(
        default=Decimal("60.00"),
        ge=0,
        le=500,
        description="Minimum achievement % for PARTIALLY_MEETS",
    )
    does_not_meet_min: Decimal = Field(
        default=Decimal("0.00"),
        ge=0,
        description="Minimum achievement % for DOES_NOT_MEET (should normally be 0)",
    )
    allow_manager_adjustment: bool = True
    max_adjustment_points: Decimal = Field(
        default=Decimal("10.00"),
        ge=0,
        le=100,
        description="Maximum points a manager can add or subtract from a KPI score",
    )
    requires_calibration: bool = False


class ScoreConfigUpdate(BaseModel):
    exceptional_min: Decimal | None = Field(default=None, ge=0, le=500)
    exceeds_min: Decimal | None = Field(default=None, ge=0, le=500)
    meets_min: Decimal | None = Field(default=None, ge=0, le=500)
    partially_meets_min: Decimal | None = Field(default=None, ge=0, le=500)
    does_not_meet_min: Decimal | None = Field(default=None, ge=0)
    allow_manager_adjustment: bool | None = None
    max_adjustment_points: Decimal | None = Field(default=None, ge=0, le=100)
    requires_calibration: bool | None = None


class ScoreConfigRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organisation_id: UUID
    review_cycle_id: UUID
    exceptional_min: Decimal
    exceeds_min: Decimal
    meets_min: Decimal
    partially_meets_min: Decimal
    does_not_meet_min: Decimal
    allow_manager_adjustment: bool
    max_adjustment_points: Decimal
    requires_calibration: bool
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# PerformanceScore (individual KPI score)
# ---------------------------------------------------------------------------


class ScoreAdjustRequest(BaseModel):
    new_score: Decimal = Field(
        ge=0,
        le=200,
        description="The adjusted score value (0–200 scale, same as achievement %).",
    )
    reason: Annotated[str, Field(min_length=10, max_length=1000)] = Field(
        description="Mandatory justification for the adjustment."
    )


class CompositeAdjustRequest(BaseModel):
    new_weighted_average: Decimal = Field(
        ge=0,
        le=200,
        description="The adjusted composite score.",
    )
    reason: Annotated[str, Field(min_length=10, max_length=1000)] = Field(
        description="Mandatory justification for the adjustment."
    )
    manager_comment: str | None = Field(
        default=None,
        max_length=2000,
        description="Optional narrative comment stored on the composite score.",
    )


class ScoreAdjustmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    score_id: UUID | None
    composite_score_id: UUID | None
    adjusted_by_id: UUID
    before_value: Decimal
    after_value: Decimal
    reason: str
    adjustment_type: str
    created_at: datetime


class PerformanceScoreRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    target_id: UUID
    user_id: UUID
    kpi_id: UUID
    review_cycle_id: UUID
    achievement_percentage: Decimal
    weighted_score: Decimal
    computed_score: Decimal
    adjusted_score: Decimal | None
    final_score: Decimal
    rating: RatingLabel
    status: ScoreStatus
    computed_at: datetime
    updated_at: datetime


class PerformanceScoreDetail(PerformanceScoreRead):
    """Extended view including nested KPI and target info."""

    kpi_name: str = ""
    kpi_code: str = ""
    target_value: Decimal = Decimal("0")
    weight: Decimal = Decimal("0")
    adjustments: list[ScoreAdjustmentRead] = []


# ---------------------------------------------------------------------------
# CompositeScore (overall employee score)
# ---------------------------------------------------------------------------


class CompositeScoreRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    review_cycle_id: UUID
    organisation_id: UUID
    weighted_average: Decimal
    final_weighted_average: Decimal
    rating: RatingLabel
    kpi_count: int
    kpis_with_actuals: int
    status: ScoreStatus
    manager_comment: str | None
    calibration_note: str | None
    computed_at: datetime
    updated_at: datetime


class CompositeScoreDetail(CompositeScoreRead):
    """Full breakdown used for the score review page."""

    kpi_scores: list[PerformanceScoreDetail] = []
    adjustment_history: list[ScoreAdjustmentRead] = []


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------


class CalibrationSessionCreate(BaseModel):
    review_cycle_id: UUID
    name: Annotated[str, Field(min_length=2, max_length=255)]
    scope_user_ids: list[UUID] = Field(
        min_length=1,
        description="UUIDs of employees to include in the calibration session.",
    )
    notes: str | None = Field(default=None, max_length=2000)


class CalibrationScoreUpdate(BaseModel):
    new_score: Decimal = Field(
        ge=0,
        le=200,
        description="The calibrated composite score.",
    )
    note: Annotated[str, Field(min_length=5, max_length=1000)]


class CalibrationSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    review_cycle_id: UUID
    organisation_id: UUID
    name: str
    status: CalibrationStatus
    facilitator_id: UUID
    scope_user_ids: list[UUID]
    notes: str | None
    completed_at: datetime | None
    created_at: datetime


class CalibrationSessionDetail(CalibrationSessionRead):
    """Session + all composite scores for the in-scope employees."""

    composite_scores: list[CompositeScoreRead] = []
    distribution: dict = {}


# ---------------------------------------------------------------------------
# Bulk scoring response
# ---------------------------------------------------------------------------


class ScoringRunResult(BaseModel):
    cycle_id: UUID
    users_scored: int
    composite_scores: list[CompositeScoreRead]
    skipped_users: list[UUID] = []
    warnings: list[str] = []
