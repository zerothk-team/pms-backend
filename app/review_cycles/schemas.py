from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.review_cycles.enums import CycleStatus, CycleType


class ReviewCycleCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    cycle_type: CycleType
    start_date: date
    end_date: date
    target_setting_deadline: date | None = None
    actual_entry_deadline: date | None = None
    scoring_start_date: date | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> "ReviewCycleCreate":
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        if (
            self.target_setting_deadline
            and self.target_setting_deadline > self.end_date
        ):
            raise ValueError("target_setting_deadline must be on or before end_date")
        if (
            self.actual_entry_deadline
            and self.actual_entry_deadline > self.end_date
        ):
            raise ValueError("actual_entry_deadline must be on or before end_date")
        if self.scoring_start_date and self.scoring_start_date < self.start_date:
            raise ValueError("scoring_start_date must be on or after start_date")
        return self


class ReviewCycleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    target_setting_deadline: date | None = None
    actual_entry_deadline: date | None = None
    scoring_start_date: date | None = None


class ReviewCycleStatusUpdate(BaseModel):
    status: CycleStatus
    reason: str | None = None


class ReviewCycleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    cycle_type: CycleType
    status: CycleStatus
    start_date: date
    end_date: date
    target_setting_deadline: date | None
    actual_entry_deadline: date | None
    scoring_start_date: date | None
    organisation_id: UUID
    created_by_id: UUID | None
    created_at: datetime
    updated_at: datetime


class PaginatedReviewCycles(BaseModel):
    items: list[ReviewCycleRead]
    total: int
    page: int
    size: int
    pages: int
