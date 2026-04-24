from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.kpis.schemas import KPIRead
from app.targets.enums import TargetLevel, TargetStatus


# ---------------------------------------------------------------------------
# Milestone schemas
# ---------------------------------------------------------------------------


class MilestoneCreate(BaseModel):
    milestone_date: date
    expected_value: Decimal = Field(ge=0)
    label: str | None = Field(default=None, max_length=100)


class MilestoneRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    milestone_date: date
    expected_value: Decimal
    label: str | None
    created_at: datetime


# ---------------------------------------------------------------------------
# KPITarget request schemas
# ---------------------------------------------------------------------------


class KPITargetCreate(BaseModel):
    kpi_id: UUID
    review_cycle_id: UUID
    assignee_type: TargetLevel
    assignee_user_id: UUID | None = None
    assignee_org_id: UUID | None = None
    target_value: Decimal = Field(gt=0)
    stretch_target_value: Decimal | None = None
    minimum_value: Decimal | None = None
    weight: Decimal = Field(default=Decimal("100.00"), ge=0, le=100)
    notes: str | None = None
    milestones: list[MilestoneCreate] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_values(self) -> "KPITargetCreate":
        if (
            self.stretch_target_value is not None
            and self.stretch_target_value <= self.target_value
        ):
            raise ValueError("stretch_target_value must be greater than target_value")
        if (
            self.minimum_value is not None
            and self.minimum_value >= self.target_value
        ):
            raise ValueError("minimum_value must be less than target_value")
        if self.assignee_type == TargetLevel.INDIVIDUAL and not self.assignee_user_id:
            raise ValueError(
                "assignee_user_id is required when assignee_type is INDIVIDUAL"
            )
        return self


class KPITargetBulkCreate(BaseModel):
    """Assign the same KPI to multiple users at once (manager assigns to team)."""

    kpi_id: UUID
    review_cycle_id: UUID
    user_targets: list[dict] = Field(
        min_length=1,
        description=(
            "List of {user_id, target_value, weight, "
            "stretch_target_value?, minimum_value?, notes?}"
        ),
    )


class CascadeTargetRequest(BaseModel):
    """Cascade an org/department target down to individual users."""

    parent_target_id: UUID
    distribution: list[dict] = Field(
        min_length=1,
        description="List of {user_id, target_value, weight}",
    )
    strategy: Literal["proportional", "equal", "manual"] = "manual"
    total_check: bool = Field(
        default=True,
        description=(
            "When True, validate that the sum of cascaded values "
            "does not exceed the parent target value."
        ),
    )


class KPITargetUpdate(BaseModel):
    target_value: Decimal | None = Field(default=None, gt=0)
    stretch_target_value: Decimal | None = None
    minimum_value: Decimal | None = None
    weight: Decimal | None = Field(default=None, ge=0, le=100)
    notes: str | None = None
    milestones: list[MilestoneCreate] | None = None  # replaces all milestones

    @model_validator(mode="after")
    def validate_values(self) -> "KPITargetUpdate":
        if (
            self.target_value is not None
            and self.stretch_target_value is not None
            and self.stretch_target_value <= self.target_value
        ):
            raise ValueError("stretch_target_value must be greater than target_value")
        if (
            self.target_value is not None
            and self.minimum_value is not None
            and self.minimum_value >= self.target_value
        ):
            raise ValueError("minimum_value must be less than target_value")
        return self


class KPITargetStatusUpdate(BaseModel):
    status: TargetStatus
    reason: str | None = None


# ---------------------------------------------------------------------------
# KPITarget response schemas
# ---------------------------------------------------------------------------


class KPITargetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kpi_id: UUID
    kpi: KPIRead
    review_cycle_id: UUID
    assignee_type: TargetLevel
    assignee_user_id: UUID | None
    assignee_org_id: UUID | None
    target_value: Decimal
    stretch_target_value: Decimal | None
    minimum_value: Decimal | None
    weight: Decimal
    status: TargetStatus
    cascade_parent_id: UUID | None
    notes: str | None
    milestones: list[MilestoneRead]
    set_by_id: UUID
    acknowledged_at: datetime | None
    locked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class KPITargetProgressRead(KPITargetRead):
    """KPITargetRead enriched with live progress metrics (computed by service)."""

    # Latest approved actual value
    latest_actual_value: Decimal | None = None
    # Total actual to date (sum or latest depending on KPI aggregation)
    total_actual_to_date: Decimal | None = None
    # (actual / target) * 100 adjusted for scoring_direction
    achievement_percentage: Decimal | None = None
    # True if past 50% of period and achievement < 60%
    is_at_risk: bool = False
    # "improving" | "declining" | "stable" based on last 3 actuals
    trend: str | None = None


class WeightsCheckResponse(BaseModel):
    user_id: UUID
    cycle_id: UUID
    total_weight: Decimal
    is_valid: bool
    warning: str | None


class CascadeTreeNode(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    assignee_type: TargetLevel
    assignee_user_id: UUID | None
    target_value: Decimal
    weight: Decimal
    status: TargetStatus
    children: list["CascadeTreeNode"] = Field(default_factory=list)


CascadeTreeNode.model_rebuild()
