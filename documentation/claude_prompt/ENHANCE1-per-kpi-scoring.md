# Copilot Prompt — Enhancement 1: Per-KPI Scoring Configuration
> **Model**: Claude Sonnet 4.6 | **Workspace**: @workspace (both frontend + backend open)
> **Depends on**: Backend Parts 1–5 and Frontend prompt completed

---

## Context & Business Problem

The current `ScoreConfig` table applies **one set of thresholds to every KPI in a review cycle**. This is wrong for real businesses:

- A **Safety Compliance** KPI must treat anything below 98% as failure — the same threshold that makes "Meets Expectations" for a Revenue Growth KPI would be dangerously lenient.
- A **Customer Retention** KPI in a SaaS company where 90% is the industry ceiling should treat 88% as "Exceptional", not "Partially Meets".
- An **Innovation Index** KPI that is inherently hard to quantify needs wider, more forgiving bands.

**This enhancement adds per-KPI, per-target scoring overrides** on top of the existing cycle-level defaults, without breaking the existing scoring engine.

---

## Part A — Backend Changes

### A1. New Enum: `ScoringPreset`

Add to `app/kpis/enums.py`:

```python
class ScoringPreset(str, Enum):
    """
    Named presets for common scoring patterns.
    Makes UI simpler — user picks a preset or chooses Custom.
    """
    STANDARD = "standard"           # 120/100/80/60/0  — default
    STRICT = "strict"               # 130/110/95/80/0  — compliance, safety
    LENIENT = "lenient"             # 110/90/70/50/0   — innovation, R&D
    BINARY = "binary"               # 100/100/90/0/0   — pass/fail KPIs
    SALES = "sales"                 # 120/100/85/70/0  — typical sales org
    CUSTOM = "custom"               # fully user-defined thresholds
```

---

### A2. New Table: `kpi_scoring_configs`

**Create new file: `app/scoring/kpi_scoring_model.py`**

This is a **separate, reusable** scoring config that can be attached to:
1. A **KPI definition** (applies whenever that KPI is used, as a default)
2. A **KPITarget** (overrides for a specific employee/cycle assignment)

```python
from sqlalchemy import Column, String, Numeric, Boolean, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import uuid
from app.database import Base
from app.scoring.enums import ScoringPreset  # add ScoringPreset to scoring enums


class KPIScoringConfig(Base):
    """
    Per-KPI or per-target scoring threshold configuration.

    Precedence (highest wins):
      target.scoring_config_id  >  kpi.scoring_config_id  >  cycle ScoreConfig

    Business rule: all _min values must be strictly descending:
      exceptional_min > exceeds_min > meets_min > partially_meets_min >= 0
    """
    __tablename__ = "kpi_scoring_configs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)           # e.g. "Safety Standard", "Sales Lenient"
    description = Column(String(500), nullable=True)
    preset = Column(SAEnum(ScoringPreset), nullable=False, default=ScoringPreset.CUSTOM)
    organisation_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=True)
    # nullable org_id = system-wide preset (read-only, seeded by system)

    # Threshold values — achievement % required to reach each rating
    exceptional_min   = Column(Numeric(6, 2), nullable=False, default=120.0)
    exceeds_min       = Column(Numeric(6, 2), nullable=False, default=100.0)
    meets_min         = Column(Numeric(6, 2), nullable=False, default=80.0)
    partially_meets_min = Column(Numeric(6, 2), nullable=False, default=60.0)
    does_not_meet_min = Column(Numeric(6, 2), nullable=False, default=0.0)  # always 0, but explicit

    # Cap: achievement % above this is capped before scoring (prevents gaming)
    achievement_cap   = Column(Numeric(6, 2), nullable=False, default=200.0)

    # Optional: require a written justification if score is manually adjusted beyond this %
    adjustment_justification_threshold = Column(Numeric(5, 2), nullable=True)

    is_system_preset  = Column(Boolean, default=False)  # True = seeded, not editable
    created_by_id     = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at        = Column(...)   # UTC DateTime
    updated_at        = Column(...)   # UTC DateTime

    # Relationships
    organisation      = relationship("Organisation")
    created_by        = relationship("User")
```

---

### A3. Modify Existing Tables

**`app/kpis/models.py` — add to `KPI` model:**

```python
# Add column to KPI model
scoring_config_id = Column(
    UUID(as_uuid=True),
    ForeignKey("kpi_scoring_configs.id"),
    nullable=True,
    comment="Default scoring config for this KPI. Overridden by target-level config."
)
scoring_config = relationship("KPIScoringConfig", foreign_keys=[scoring_config_id])
```

**`app/targets/models.py` — add to `KPITarget` model:**

```python
# Add these columns to KPITarget
scoring_config_id = Column(
    UUID(as_uuid=True),
    ForeignKey("kpi_scoring_configs.id"),
    nullable=True,
    comment="Target-level override. Highest precedence. If null, falls back to KPI's config, then cycle config."
)
scoring_config = relationship("KPIScoringConfig", foreign_keys=[scoring_config_id])
```

---

### A4. New Schemas — `app/scoring/kpi_scoring_schemas.py`

```python
from pydantic import BaseModel, Field, model_validator
from decimal import Decimal
from uuid import UUID
from typing import Optional
from app.scoring.enums import ScoringPreset


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
    def validate_threshold_order(self):
        """
        Thresholds MUST be strictly descending.
        Business rule: a higher achievement % must always map to a better rating.
        """
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
        PRESET_VALUES = {
            ScoringPreset.STANDARD: (120, 100, 80,  60,  0),
            ScoringPreset.STRICT:   (130, 110, 95,  80,  0),
            ScoringPreset.LENIENT:  (110, 90,  70,  50,  0),
            ScoringPreset.BINARY:   (100, 100, 90,  0,   0),
            ScoringPreset.SALES:    (120, 100, 85,  70,  0),
        }
        exc, excd, meets, partial, dne = PRESET_VALUES[preset]
        return cls(
            name=name, preset=preset,
            exceptional_min=exc, exceeds_min=excd,
            meets_min=meets, partially_meets_min=partial,
            does_not_meet_min=dne,
        )


class KPIScoringConfigUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    exceptional_min: Optional[Decimal] = None
    exceeds_min: Optional[Decimal] = None
    meets_min: Optional[Decimal] = None
    partially_meets_min: Optional[Decimal] = None
    achievement_cap: Optional[Decimal] = None
    adjustment_justification_threshold: Optional[Decimal] = None

    # Re-run validation if any threshold changed
    @model_validator(mode="after")
    def validate_if_all_present(self):
        all_set = all(v is not None for v in [
            self.exceptional_min, self.exceeds_min,
            self.meets_min, self.partially_meets_min,
        ])
        if all_set:
            thresholds = [self.exceptional_min, self.exceeds_min, self.meets_min, self.partially_meets_min]
            for i in range(len(thresholds) - 1):
                if thresholds[i] <= thresholds[i + 1]:
                    raise ValueError("Thresholds must be strictly descending")
        return self


class KPIScoringConfigRead(BaseModel):
    model_config = {"from_attributes": True}
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
    # Computed display field
    summary: str = ""  # populated by service: "A:120% | B:100% | C:80% | D:60% | F:0%"

    @model_validator(mode="after")
    def build_summary(self):
        self.summary = (
            f"Exceptional:≥{self.exceptional_min}% | "
            f"Exceeds:≥{self.exceeds_min}% | "
            f"Meets:≥{self.meets_min}% | "
            f"Partial:≥{self.partially_meets_min}% | "
            f"DNM:<{self.partially_meets_min}%"
        )
        return self


class AssignScoringConfigRequest(BaseModel):
    """Assign a scoring config to a KPI or a KPITarget."""
    scoring_config_id: Optional[UUID] = Field(
        default=None,
        description="Set to null to remove override and fall back to higher-level config"
    )
```

---

### A5. Update the Scoring Calculator — `app/scoring/calculator.py`

**Replace / extend `determine_rating()` with config-aware version:**

```python
from app.scoring.kpi_scoring_model import KPIScoringConfig
from app.scoring.models import ScoreConfig  # existing cycle-level config
from app.targets.models import KPITarget
from app.kpis.models import KPI


def resolve_scoring_config(
    target: KPITarget,
    cycle_config: ScoreConfig,
) -> dict:
    """
    Resolve the effective scoring thresholds for a KPITarget.

    Precedence (highest to lowest):
      1. target.scoring_config      (target-level override)
      2. target.kpi.scoring_config  (KPI-level default)
      3. cycle_config               (cycle-wide fallback)

    Returns a dict with keys:
      exceptional_min, exceeds_min, meets_min, partially_meets_min,
      does_not_meet_min, achievement_cap
    """
    # Try target-level override first
    if target.scoring_config_id and target.scoring_config:
        cfg = target.scoring_config
        return {
            "exceptional_min":    float(cfg.exceptional_min),
            "exceeds_min":        float(cfg.exceeds_min),
            "meets_min":          float(cfg.meets_min),
            "partially_meets_min": float(cfg.partially_meets_min),
            "does_not_meet_min":  float(cfg.does_not_meet_min),
            "achievement_cap":    float(cfg.achievement_cap),
            "source":             f"target_override:{cfg.name}",
        }

    # Try KPI-level default
    if target.kpi and target.kpi.scoring_config_id and target.kpi.scoring_config:
        cfg = target.kpi.scoring_config
        return {
            "exceptional_min":    float(cfg.exceptional_min),
            "exceeds_min":        float(cfg.exceeds_min),
            "meets_min":          float(cfg.meets_min),
            "partially_meets_min": float(cfg.partially_meets_min),
            "does_not_meet_min":  float(cfg.does_not_meet_min),
            "achievement_cap":    float(cfg.achievement_cap),
            "source":             f"kpi_default:{cfg.name}",
        }

    # Fall back to cycle-level config
    return {
        "exceptional_min":    float(cycle_config.exceptional_min),
        "exceeds_min":        float(cycle_config.exceeds_min),
        "meets_min":          float(cycle_config.meets_min),
        "partially_meets_min": float(cycle_config.partially_meets_min),
        "does_not_meet_min":  0.0,
        "achievement_cap":    200.0,
        "source":             "cycle_default",
    }


def determine_rating_with_config(
    achievement_pct: Decimal,
    scoring_config: dict,
) -> tuple[RatingLabel, str]:
    """
    Map an achievement percentage to a RatingLabel using resolved config.

    Args:
        achievement_pct: Raw achievement percentage (before cap)
        scoring_config:  Result of resolve_scoring_config()

    Returns:
        (RatingLabel, source_description)

    Examples:
        (95.0, standard_config)  -> (MEETS_EXPECTATIONS, "cycle_default")
        (95.0, strict_config)    -> (PARTIALLY_MEETS, "kpi_default:Safety Standard")
        (125.0, standard_config) -> (EXCEPTIONAL, "cycle_default")
    """
    if achievement_pct is None:
        return RatingLabel.NOT_RATED, scoring_config["source"]

    # Apply achievement cap
    capped = min(float(achievement_pct), scoring_config["achievement_cap"])

    if capped >= scoring_config["exceptional_min"]:
        return RatingLabel.EXCEPTIONAL, scoring_config["source"]
    elif capped >= scoring_config["exceeds_min"]:
        return RatingLabel.EXCEEDS_EXPECTATIONS, scoring_config["source"]
    elif capped >= scoring_config["meets_min"]:
        return RatingLabel.MEETS_EXPECTATIONS, scoring_config["source"]
    elif capped >= scoring_config["partially_meets_min"]:
        return RatingLabel.PARTIALLY_MEETS, scoring_config["source"]
    else:
        return RatingLabel.DOES_NOT_MEET, scoring_config["source"]


def compute_achievement_percentage(
    actual_value: Decimal,
    target_value: Decimal,
    scoring_direction: ScoringDirection,
    minimum_value: Optional[Decimal] = None,
    achievement_cap: Decimal = Decimal("200.0"),
) -> Decimal:
    """
    Compute raw achievement percentage.

    Higher-is-better: (actual / target) * 100
    Lower-is-better:  (target / actual) * 100   ← inverted

    Edge cases handled:
      - target_value == 0       → return 0 (avoid division by zero)
      - actual < minimum_value  → return 0 (hard floor)
      - result > achievement_cap → capped
    """
    if target_value == 0:
        return Decimal("0.0")

    if minimum_value is not None and actual_value < minimum_value:
        return Decimal("0.0")

    if scoring_direction == ScoringDirection.HIGHER_IS_BETTER:
        pct = (actual_value / target_value) * 100
    else:
        # Lower is better: perfect score when actual = target, improves as actual goes lower
        if actual_value == 0:
            return achievement_cap  # actual of 0 on lower-is-better = perfect
        pct = (target_value / actual_value) * 100

    return min(Decimal(str(round(pct, 4))), achievement_cap)
```

---

### A6. Update ScoringEngine — `app/scoring/service.py`

**Update `compute_scores_for_cycle` to use per-KPI config:**

```python
async def _score_single_target(
    self,
    db: AsyncSession,
    target: KPITarget,
    actual_value: Optional[Decimal],
    cycle_config: ScoreConfig,
) -> PerformanceScore:
    """
    Score a single target. Handles all config precedence logic.
    Called from compute_scores_for_cycle() for each target.
    """
    # Step 1: Resolve effective scoring config (3-level precedence)
    effective_config = resolve_scoring_config(target, cycle_config)

    # Step 2: Compute achievement %
    if actual_value is None:
        achievement_pct = None
        rating = RatingLabel.NOT_RATED
        rating_source = "no_actual"
    else:
        achievement_pct = compute_achievement_percentage(
            actual_value=actual_value,
            target_value=target.target_value,
            scoring_direction=target.kpi.scoring_direction,
            minimum_value=target.minimum_value,
            achievement_cap=Decimal(str(effective_config["achievement_cap"])),
        )
        rating, rating_source = determine_rating_with_config(achievement_pct, effective_config)

    # Step 3: Compute weighted score
    weighted_score = compute_weighted_score(achievement_pct or Decimal("0"), target.weight)

    # Step 4: Persist PerformanceScore
    score = PerformanceScore(
        target_id=target.id,
        user_id=target.assignee_user_id,
        kpi_id=target.kpi_id,
        review_cycle_id=target.review_cycle_id,
        achievement_percentage=achievement_pct,
        weighted_score=weighted_score,
        rating=rating,
        computed_score=achievement_pct or Decimal("0"),
        final_score=achievement_pct or Decimal("0"),
        status=ScoreStatus.COMPUTED,
        scoring_config_snapshot=effective_config,  # IMPORTANT: snapshot for audit
        computed_at=datetime.now(timezone.utc),
    )
    db.add(score)
    return score
```

**Add `scoring_config_snapshot` column to `PerformanceScore` model:**

```python
# In app/scoring/models.py — add to PerformanceScore
scoring_config_snapshot = Column(
    JSON,
    nullable=True,
    comment="Snapshot of the effective scoring config at time of computation. Audit trail."
)
rating_config_source = Column(
    String(100),
    nullable=True,
    comment="Which config level was used: 'target_override:X', 'kpi_default:X', or 'cycle_default'"
)
```

---

### A7. New Service — `app/scoring/kpi_scoring_service.py`

```python
class KPIScoringConfigService:

    # ── System presets (seeded at startup) ──────────────────────────────

    SYSTEM_PRESETS = [
        {"name": "Standard",   "preset": ScoringPreset.STANDARD, "exceptional_min": 120, "exceeds_min": 100, "meets_min": 80,  "partially_meets_min": 60},
        {"name": "Strict",     "preset": ScoringPreset.STRICT,   "exceptional_min": 130, "exceeds_min": 110, "meets_min": 95,  "partially_meets_min": 80},
        {"name": "Lenient",    "preset": ScoringPreset.LENIENT,  "exceptional_min": 110, "exceeds_min": 90,  "meets_min": 70,  "partially_meets_min": 50},
        {"name": "Binary",     "preset": ScoringPreset.BINARY,   "exceptional_min": 100, "exceeds_min": 100, "meets_min": 90,  "partially_meets_min": 0},
        {"name": "Sales Org",  "preset": ScoringPreset.SALES,    "exceptional_min": 120, "exceeds_min": 100, "meets_min": 85,  "partially_meets_min": 70},
    ]

    async def seed_system_presets(self, db: AsyncSession) -> None:
        """Call on startup. Idempotent — only inserts if not already present."""
        for preset_data in self.SYSTEM_PRESETS:
            existing = await db.execute(
                select(KPIScoringConfig).where(
                    KPIScoringConfig.is_system_preset == True,
                    KPIScoringConfig.name == preset_data["name"]
                )
            )
            if not existing.scalar_one_or_none():
                db.add(KPIScoringConfig(**preset_data, is_system_preset=True, does_not_meet_min=0, achievement_cap=200))
        await db.commit()

    # ── CRUD ────────────────────────────────────────────────────────────

    async def create(self, db: AsyncSession, org_id: UUID, user_id: UUID, data: KPIScoringConfigCreate) -> KPIScoringConfig:
        """
        Create a custom scoring config for an org.
        Validates threshold order before saving.
        """
        config = KPIScoringConfig(
            **data.model_dump(),
            organisation_id=org_id,
            created_by_id=user_id,
            is_system_preset=False,
        )
        db.add(config)
        await db.commit()
        await db.refresh(config)
        return config

    async def list_for_org(self, db: AsyncSession, org_id: UUID) -> list[KPIScoringConfig]:
        """Returns org's custom configs + all system presets."""
        result = await db.execute(
            select(KPIScoringConfig).where(
                or_(
                    KPIScoringConfig.organisation_id == org_id,
                    KPIScoringConfig.is_system_preset == True,
                )
            ).order_by(KPIScoringConfig.is_system_preset.desc(), KPIScoringConfig.name)
        )
        return result.scalars().all()

    async def assign_to_kpi(
        self, db: AsyncSession, kpi_id: UUID, org_id: UUID, scoring_config_id: Optional[UUID]
    ) -> KPI:
        """
        Assign (or remove) a scoring config from a KPI definition.
        Setting scoring_config_id=None removes the override.
        """
        kpi = await self._get_kpi(db, kpi_id, org_id)
        if scoring_config_id:
            await self._validate_config_accessible(db, scoring_config_id, org_id)
        kpi.scoring_config_id = scoring_config_id
        kpi.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(kpi)
        return kpi

    async def assign_to_target(
        self, db: AsyncSession, target_id: UUID, org_id: UUID, scoring_config_id: Optional[UUID]
    ) -> KPITarget:
        """
        Assign (or remove) a scoring config from a specific KPITarget.
        This is the highest-precedence override.
        Cannot be changed after target is LOCKED.
        """
        target = await self._get_target(db, target_id, org_id)
        if target.status == TargetStatus.LOCKED:
            raise ForbiddenException("Cannot change scoring config on a locked target")
        if scoring_config_id:
            await self._validate_config_accessible(db, scoring_config_id, org_id)
        target.scoring_config_id = scoring_config_id
        await db.commit()
        await db.refresh(target)
        return target

    async def preview_scoring(
        self,
        db: AsyncSession,
        scoring_config_id: UUID,
        org_id: UUID,
        test_values: list[float],
    ) -> list[dict]:
        """
        Preview what ratings a set of achievement % values would produce.
        Used by the UI to show a live preview of a scoring config.

        Example:
          test_values=[50, 60, 75, 85, 95, 100, 110, 120, 130]
          Returns: [
            {"achievement_pct": 50,  "rating": "does_not_meet",        "label": "Does Not Meet"},
            {"achievement_pct": 60,  "rating": "partially_meets",      "label": "Partially Meets"},
            ...
          ]
        """
        config = await self._get_config(db, scoring_config_id, org_id)
        effective = {
            "exceptional_min": float(config.exceptional_min),
            "exceeds_min": float(config.exceeds_min),
            "meets_min": float(config.meets_min),
            "partially_meets_min": float(config.partially_meets_min),
            "achievement_cap": float(config.achievement_cap),
            "source": config.name,
        }
        return [
            {
                "achievement_pct": v,
                "rating": determine_rating_with_config(Decimal(str(v)), effective)[0],
                "label": RATING_DISPLAY_LABELS[determine_rating_with_config(Decimal(str(v)), effective)[0]],
            }
            for v in test_values
        ]
```

---

### A8. New Router — `app/scoring/kpi_scoring_router.py`

```
GET    /scoring/configs/                         → list all configs (org + system presets)
POST   /scoring/configs/                         → create custom config (hr_admin)
GET    /scoring/configs/{config_id}             → get single config
PUT    /scoring/configs/{config_id}             → update custom config (hr_admin, not system)
DELETE /scoring/configs/{config_id}             → delete (only if not in use)
POST   /scoring/configs/from-preset             → create config from named preset
GET    /scoring/configs/{config_id}/preview     → preview ratings for test % values

PATCH  /kpis/{kpi_id}/scoring-config            → assign config to KPI (hr_admin)
PATCH  /targets/{target_id}/scoring-config      → assign config to target (manager, hr_admin)
GET    /targets/{target_id}/scoring-config      → get effective config + source for target
```

---

### A9. Alembic Migration

```bash
alembic revision --autogenerate -m "add_kpi_scoring_configs_and_overrides"
```

Migration must include:
- New `kpi_scoring_configs` table
- `scoring_config_id` FK column on `kpis`
- `scoring_config_id` FK column on `kpi_targets`
- `scoring_config_snapshot` JSON column on `performance_scores`
- `rating_config_source` String column on `performance_scores`
- `ScoringPreset` enum type in PostgreSQL

---

## Part B — Frontend Changes

### B1. New TypeScript Types — `src/types/scoring-config.types.ts`

```typescript
export const ScoringPreset = {
  STANDARD: 'standard',
  STRICT:   'strict',
  LENIENT:  'lenient',
  BINARY:   'binary',
  SALES:    'sales',
  CUSTOM:   'custom',
} as const;
export type ScoringPreset = typeof ScoringPreset[keyof typeof ScoringPreset];

export interface KPIScoringConfig {
  id: string;
  name: string;
  description: string | null;
  preset: ScoringPreset;
  exceptional_min: number;
  exceeds_min: number;
  meets_min: number;
  partially_meets_min: number;
  does_not_meet_min: number;
  achievement_cap: number;
  adjustment_justification_threshold: number | null;
  is_system_preset: boolean;
  organisation_id: string | null;
  summary: string;         // "Exceptional:≥120% | Exceeds:≥100% | ..."
  created_at: string;
}

export interface ScoringConfigPreviewResult {
  achievement_pct: number;
  rating: RatingLabel;
  label: string;
}

export interface EffectiveScoringConfig extends KPIScoringConfig {
  source: 'target_override' | 'kpi_default' | 'cycle_default';
  source_name: string;    // name of the config being used
}
```

---

### B2. RTK Query Endpoints — `src/services/endpoints/scoringConfigEndpoints.ts`

```typescript
// Add these endpoints to the existing apiService

listScoringConfigs: build.query<KPIScoringConfig[], void>({
  queryFn: async () => {
    const data = await mockFetch(() => scoringConfigsMock);
    return { data };
  },
  providesTags: ['ScoringConfig'],
}),

createScoringConfig: build.mutation<KPIScoringConfig, KPIScoringConfigCreate>({
  queryFn: async (body) => {
    // Client-side validation: thresholds must be descending
    const thresholds = [body.exceptional_min, body.exceeds_min, body.meets_min, body.partially_meets_min];
    for (let i = 0; i < thresholds.length - 1; i++) {
      if (thresholds[i] <= thresholds[i + 1]) {
        return { error: { status: 422, error: `Threshold order invalid at position ${i}` } };
      }
    }
    const data = await mockMutate(() => ({ ...body, id: crypto.randomUUID(), is_system_preset: false, created_at: new Date().toISOString() }));
    return { data };
  },
  invalidatesTags: ['ScoringConfig'],
}),

previewScoringConfig: build.query<ScoringConfigPreviewResult[], { configId: string; testValues: number[] }>({
  queryFn: async ({ configId, testValues }) => {
    const config = scoringConfigsMock.find(c => c.id === configId);
    if (!config) return { error: { status: 404, error: 'Not found' } };
    const data = testValues.map(v => ({
      achievement_pct: v,
      rating: computeRatingClient(v, config),
      label: RATING_LABELS[computeRatingClient(v, config)],
    }));
    return { data };
  },
}),

assignScoringConfigToKPI: build.mutation<KPI, { kpiId: string; scoringConfigId: string | null }>({...}),
assignScoringConfigToTarget: build.mutation<KPITarget, { targetId: string; scoringConfigId: string | null }>({...}),
getEffectiveScoringConfig: build.query<EffectiveScoringConfig, string>({...}), // targetId
```

---

### B3. New Component — `src/features/scoring/components/ScoringConfigManager.tsx`

Build this component with three tabs:

**Tab 1 — Config List:**
- Table of all org configs + system presets
- System presets shown with a lock icon (read-only)
- Each row: name, preset badge, threshold summary, "Assign to KPI" button, edit/delete

**Tab 2 — Config Builder Form:**
```
┌─────────────────────────────────────────────────────────────────┐
│  Scoring Configuration Builder                                   │
│                                                                  │
│  Name: [Safety Compliance Standard          ]                    │
│  Start from preset: [Strict ▾]                                  │
│                                                                  │
│  Thresholds (achievement % required for each rating):            │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  ⭐ Exceptional    ≥ [130] %  ████████████████████████   │   │
│  │  ✅ Exceeds Exp.   ≥ [110] %  ████████████████████       │   │
│  │  ✓  Meets Exp.     ≥ [ 95] %  ███████████████            │   │
│  │  ⚠️  Partially M.  ≥ [ 80] %  ████████████               │   │
│  │  ❌ Does Not Meet  <  [ 80] %  (auto-calculated)          │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  Achievement cap: [200] %    (max score counted)                 │
│                                                                  │
│  Live Preview ↓                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Tab 3 — Live Preview:**
- Slider from 0% to 150% — user drags to any value
- System shows what rating that achievement % would produce under the current config
- Colour-coded output: Red (DNM) → Orange → Amber → Green → Emerald
- Also shows a comparison table: same value under Standard vs this config

```
Achievement: 88% ←───────────────────────── [slider]

Under "Safety Compliance":   ⚠️ PARTIALLY MEETS  (needs ≥95% to Meet)
Under "Standard":            ✓  MEETS EXPECTATIONS

Threshold comparison:
  Rating            This Config    Standard
  Exceptional       ≥ 130%         ≥ 120%
  Exceeds           ≥ 110%         ≥ 100%
  Meets             ≥  95%         ≥  80%   ← difference!
  Partially Meets   ≥  80%         ≥  60%
```

---

### B4. Update KPI Builder Form — Step 4 (Scoring)

Add a new section to Step 4 of `KPIBuilderForm.tsx`:

```
STEP 4 — SCORING
──────────────────────────────────────────────────
Scoring direction: [Higher is Better ▾]

KPI-level scoring config (optional):
  [Use cycle default ▾]
  Options:
    • Use cycle default (Standard: 120/100/80/60)
    • ⭐ Standard (system preset)
    • 🔒 Strict (system preset)
    • 📈 Sales Org (system preset)
    • + My Custom Config
    • + Create new config...

  ← if non-default selected, show threshold summary badge:
  "Exceptional:≥130% | Exceeds:≥110% | Meets:≥95%"
──────────────────────────────────────────────────
```

---

### B5. Update Target Assignment — Show Effective Config

In `TargetSetPage.tsx`, after assigning a KPI to a target, show:

```
┌────────────────────────────────────────────────┐
│  Revenue Growth                    Weight: 40% │
│  Target: 15%                                   │
│                                                │
│  Scoring: [Cycle Default ▾]                   │
│  ℹ️ Effective: Standard (120/100/80/60)        │
│     source: cycle_default                     │
│                                                │
│  Override for this employee:                  │
│  [Use cycle default ▾]                        │
└────────────────────────────────────────────────┘
```

---

### B6. Update Scorecard Table

In `KPIScorecardTable.tsx`, add a tooltip on the Rating column:

```
Achievement: 92%   Rating: ✓ Meets Expectations  ℹ️
                                                   │
                                          ┌────────▼───────┐
                                          │ Config: Strict  │
                                          │ source: KPI     │
                                          │ Meets: ≥95%     │
                                          │ (cycle: ≥80%)   │
                                          └────────────────┘
```

This makes it clear to both manager and employee WHY a score produced a specific rating, even if it looks surprising.

---

## Part C — Tests

### Backend Tests — `tests/test_kpi_scoring_config.py`

```python
test_threshold_order_validation_strict()          # 100 > 80 is ok
test_threshold_order_validation_equal_fails()     # 80 >= 80 raises 422
test_threshold_order_validation_reversed_fails()  # 60 > 80 raises 422
test_create_config_from_preset_standard()
test_create_config_from_preset_strict()
test_assign_config_to_kpi()
test_assign_config_to_target()
test_assign_to_locked_target_fails()              # 403
test_resolve_config_target_level_wins()           # target override beats kpi default
test_resolve_config_kpi_level_wins()              # kpi default beats cycle
test_resolve_config_cycle_fallback()              # no overrides → cycle config
test_scoring_with_strict_config()
  # Achievement 88% + strict config (meets≥95%) → PARTIALLY_MEETS
  # Achievement 88% + standard config (meets≥80%) → MEETS_EXPECTATIONS
test_scoring_config_snapshot_stored()             # verify JSON snapshot in performance_scores
test_preview_scoring_endpoint()
test_seed_system_presets_idempotent()             # calling twice doesn't duplicate
```

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                SCORING CONFIG PRECEDENCE                         │
│                                                                  │
│  kpi_scoring_configs table                                       │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────┐│
│  │ System Presets  │  │ Org Custom      │  │ Cycle ScoreConfig ││
│  │ (read-only)     │  │ Configs         │  │ (existing)        ││
│  │ Standard        │  │ Safety Rules    │  │ exceptional: 120  ││
│  │ Strict          │  │ Sales Target    │  │ exceeds:    100   ││
│  │ Lenient         │  │ Innovation      │  │ meets:       80   ││
│  │ Binary          │  │                 │  │ partial:     60   ││
│  └────────┬────────┘  └────────┬────────┘  └──────────┬───────┘│
│           │                    │                       │         │
│           └──────────┬─────────┘                       │         │
│                      │ assigned to                      │ fallback│
│             ┌────────▼────────┐                        │         │
│             │   KPI Definition│◄───────────────────────┘         │
│             │ scoring_config  │  kpi.scoring_config_id            │
│             │ (optional)      │                                   │
│             └────────┬────────┘                                   │
│                      │ further overridden by                      │
│             ┌────────▼────────┐                                   │
│             │   KPI Target    │                                   │
│             │ scoring_config  │  target.scoring_config_id         │
│             │ (optional)      │  ← HIGHEST PRECEDENCE            │
│             └────────┬────────┘                                   │
│                      │                                            │
│             ┌────────▼────────┐                                   │
│             │ resolve_scoring │◄──────────────────────────────────┘
│             │ _config()       │  returns effective thresholds
│             └────────┬────────┘
│                      │
│             ┌────────▼────────┐
│             │ determine_rating│
│             │ _with_config()  │
│             └─────────────────┘
└─────────────────────────────────────────────────────────────────┘
```