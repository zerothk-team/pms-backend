"""
Pydantic v2 schemas for KPI-level scoring configuration.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.scoring.enums import ScoringPreset


# ---------------------------------------------------------------------------
# Create / Update / Read
# ---------------------------------------------------------------------------


class KPIScoringConfigCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
    preset: ScoringPreset = ScoringPreset.CUSTOM
    exceptional_min: Decimal = Field(default=Decimal("120.0"), ge=0, le=500)
    exceeds_min: Decimal = Field(default=Decimal("100.0"), ge=0, le=500)
    meets_min: Decimal = Field(default=Decimal("80.0"), ge=0, le=500)
    partially_meets_min: Decimal = Field(default=Decimal("60.0"), ge=0, le=500)
    does_not_meet_min: Decimal = Field(default=Decimal("0.0"), ge=0)
    achievement_cap: Decimal = Field(default=Decimal("200.0"), ge=100, le=1000)
    adjustment_justification_threshold: Optional[Decimal] = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def validate_threshold_order(self) -> "KPIScoringConfigCreate":
        """Thresholds MUST be strictly descending."""
        thresholds = [
            ("exceptional_min", self.exceptional_min),
            ("exceeds_min", self.exceeds_min),
            ("meets_min", self.meets_min),
            ("partially_meets_min", self.partially_meets_min),
        ]
        for i in range(len(thresholds) - 1):
            name_hi, val_hi = thresholds[i]
            name_lo, val_lo = thresholds[i + 1]
            if val_hi <= val_lo:
                raise ValueError(
                    f"{name_hi} ({val_hi}) must be strictly greater than "
                    f"{name_lo} ({val_lo})"
                )
        if self.exceeds_min > self.achievement_cap:
            raise ValueError("achievement_cap must be >= exceeds_min")
        return self

    @classmethod
    def from_preset(cls, preset: ScoringPreset, name: str) -> "KPIScoringConfigCreate":
        """Factory: create a config from a named preset."""
        _PRESET_VALUES: dict[ScoringPreset, tuple[int, int, int, int, int]] = {
            ScoringPreset.STANDARD: (120, 100, 80, 60, 0),
            ScoringPreset.STRICT:   (130, 110, 95, 80, 0),
            ScoringPreset.LENIENT:  (110, 90,  70, 50, 0),
            ScoringPreset.BINARY:   (100, 100, 90,  0, 0),
            ScoringPreset.SALES:    (120, 100, 85, 70, 0),
        }
        exc, excd, meets, partial, dne = _PRESET_VALUES[preset]
        return cls(
            name=name,
            preset=preset,
            exceptional_min=Decimal(str(exc)),
            exceeds_min=Decimal(str(excd)),
            meets_min=Decimal(str(meets)),
            partially_meets_min=Decimal(str(partial)),
            does_not_meet_min=Decimal(str(dne)),
        )


class KPIScoringConfigUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
    exceptional_min: Optional[Decimal] = Field(default=None, ge=0, le=500)
    exceeds_min: Optional[Decimal] = Field(default=None, ge=0, le=500)
    meets_min: Optional[Decimal] = Field(default=None, ge=0, le=500)
    partially_meets_min: Optional[Decimal] = Field(default=None, ge=0, le=500)
    achievement_cap: Optional[Decimal] = Field(default=None, ge=100, le=1000)
    adjustment_justification_threshold: Optional[Decimal] = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def validate_if_all_present(self) -> "KPIScoringConfigUpdate":
        all_set = all(
            v is not None
            for v in [
                self.exceptional_min,
                self.exceeds_min,
                self.meets_min,
                self.partially_meets_min,
            ]
        )
        if all_set:
            vals = [
                self.exceptional_min,
                self.exceeds_min,
                self.meets_min,
                self.partially_meets_min,
            ]
            for i in range(len(vals) - 1):
                if vals[i] <= vals[i + 1]:  # type: ignore[operator]
                    raise ValueError("Thresholds must be strictly descending")
        return self


class KPIScoringConfigRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: Optional[str]
    preset: ScoringPreset
    exceptional_min: Decimal
    exceeds_min: Decimal
    meets_min: Decimal
    partially_meets_min: Decimal
    does_not_meet_min: Decimal
    achievement_cap: Decimal
    adjustment_justification_threshold: Optional[Decimal]
    is_system_preset: bool
    organisation_id: Optional[UUID]
    created_at: datetime
    summary: str = ""

    @model_validator(mode="after")
    def build_summary(self) -> "KPIScoringConfigRead":
        self.summary = (
            f"Exceptional:\u2265{self.exceptional_min}% | "
            f"Exceeds:\u2265{self.exceeds_min}% | "
            f"Meets:\u2265{self.meets_min}% | "
            f"Partial:\u2265{self.partially_meets_min}% | "
            f"DNM:<{self.partially_meets_min}%"
        )
        return self


# ---------------------------------------------------------------------------
# Assign requests
# ---------------------------------------------------------------------------


class AssignScoringConfigRequest(BaseModel):
    """Assign (or remove) a scoring config from a KPI or KPITarget."""

    scoring_config_id: Optional[UUID] = Field(
        default=None,
        description="Set to null to remove override and fall back to higher-level config",
    )


class FromPresetRequest(BaseModel):
    """Create a KPIScoringConfig from a named preset."""

    preset: ScoringPreset
    name: str = Field(min_length=2, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


class ScoringPreviewRequest(BaseModel):
    test_values: list[float] = Field(
        description="List of achievement % values to preview ratings for",
        min_length=1,
        max_length=50,
    )


class ScoringPreviewResult(BaseModel):
    achievement_pct: float
    rating: str
    label: str


# ---------------------------------------------------------------------------
# Effective config (returned for a target's resolved thresholds)
# ---------------------------------------------------------------------------


class EffectiveScoringConfigRead(KPIScoringConfigRead):
    source: str = ""   # 'target_override:X', 'kpi_default:X', or 'cycle_default'
