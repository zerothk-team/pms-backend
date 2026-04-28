> ⛔ DEPRECATED — This file is superseded by `MASTER_USER_GUIDE.md` at the repo root.
> Do not update this file. It is kept for historical reference only.
> Last active version: see git history.

# Copilot Prompt — Part 4: Scoring Engine, Calibration & Dashboard Endpoints
> **Model**: Claude Sonnet 4.6 | **Depends on**: Parts 1, 2 & 3 complete

---

## Context

Parts 1–3 are complete. KPI definitions, targets, and actuals are all working. Now build the **scoring engine** that calculates performance scores at period-end, the **calibration workflow**, and all **dashboard/reporting API endpoints** that the React frontend will consume.

---

## What to Build in This Part

```
app/
├── scoring/
│   ├── __init__.py
│   ├── models.py        ← PerformanceScore, ScoreAdjustment, CalibrationSession
│   ├── schemas.py
│   ├── service.py       ← ScoringEngine (core logic)
│   ├── router.py
│   └── calculator.py    ← Pure calculation functions (no DB calls)
│
└── dashboards/
    ├── __init__.py
    ├── schemas.py        ← Response schemas for dashboard views
    ├── service.py        ← Aggregation queries
    └── router.py         ← Dashboard endpoints
```

---

## Module A: Scoring

### Enums — `app/scoring/enums.py`

```python
class ScoreStatus(str, Enum):
    COMPUTED = "computed"             # auto-calculated, not yet reviewed
    MANAGER_REVIEWED = "manager_reviewed"   # manager has seen it
    ADJUSTED = "adjusted"             # manager applied qualitative adjustment
    CALIBRATED = "calibrated"         # went through calibration session
    FINAL = "final"                   # locked, no further changes
    APPEALED = "appealed"             # employee disputes the score (stub)

class RatingLabel(str, Enum):
    EXCEPTIONAL = "exceptional"       # e.g. 5 stars
    EXCEEDS_EXPECTATIONS = "exceeds_expectations"
    MEETS_EXPECTATIONS = "meets_expectations"
    PARTIALLY_MEETS = "partially_meets"
    DOES_NOT_MEET = "does_not_meet"
    NOT_RATED = "not_rated"           # no actuals submitted

class CalibrationStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    LOCKED = "locked"
```

### Model: `ScoreConfig`

Configures how scores map to ratings (one per org per cycle).

```
Table: score_configs
```

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `organisation_id` | UUID FK | unique per org |
| `review_cycle_id` | UUID FK → review_cycles.id | |
| `exceptional_min` | Numeric(6,2) | default 120.0 — achievement % threshold |
| `exceeds_min` | Numeric(6,2) | default 100.0 |
| `meets_min` | Numeric(6,2) | default 80.0 |
| `partially_meets_min` | Numeric(6,2) | default 60.0 |
| `does_not_meet_min` | Numeric(6,2) | default 0.0 |
| `allow_manager_adjustment` | Boolean | default True |
| `max_adjustment_points` | Numeric(5,2) | default 10.0 — cap on manager bump/cut |
| `requires_calibration` | Boolean | default False |
| `created_at` | DateTime UTC | |
| `updated_at` | DateTime UTC | |

---

### Model: `PerformanceScore`

One row per employee per KPI per review cycle (individual KPI score).

```
Table: performance_scores
```

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `target_id` | UUID FK → kpi_targets.id | not null |
| `user_id` | UUID FK → users.id | not null (denorm) |
| `kpi_id` | UUID FK → kpis.id | not null (denorm) |
| `review_cycle_id` | UUID FK → review_cycles.id | not null |
| `achievement_percentage` | Numeric(8,4) | (actual / target) * 100 |
| `weighted_score` | Numeric(8,4) | achievement_percentage * (weight / 100) |
| `rating` | Enum(RatingLabel) | derived from score_config thresholds |
| `computed_score` | Numeric(8,4) | raw computed score (0–100+ scale) |
| `adjusted_score` | Numeric(8,4) | nullable — after manager adjustment |
| `final_score` | Numeric(8,4) | adjusted_score ?? computed_score |
| `status` | Enum(ScoreStatus) | default COMPUTED |
| `computed_at` | DateTime UTC | |
| `updated_at` | DateTime UTC | |

---

### Model: `CompositeScore`

One row per employee per cycle (overall performance score).

```
Table: composite_scores
```

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK → users.id | not null |
| `review_cycle_id` | UUID FK → review_cycles.id | not null |
| `organisation_id` | UUID FK → organisations.id | not null |
| `weighted_average` | Numeric(8,4) | weighted average of all KPI scores |
| `rating` | Enum(RatingLabel) | overall rating |
| `kpi_count` | Integer | number of KPIs scored |
| `kpis_with_actuals` | Integer | KPIs that had at least one actual |
| `status` | Enum(ScoreStatus) | default COMPUTED |
| `manager_comment` | Text | nullable |
| `calibration_note` | Text | nullable |
| `final_weighted_average` | Numeric(8,4) | after all adjustments |
| `computed_at` | DateTime UTC | |
| `updated_at` | DateTime UTC | |

**Unique constraint:** `(user_id, review_cycle_id)`

---

### Model: `ScoreAdjustment`

Audit trail for every manual adjustment.

```
Table: score_adjustments
```

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `score_id` | UUID FK → performance_scores.id | nullable |
| `composite_score_id` | UUID FK → composite_scores.id | nullable |
| `adjusted_by_id` | UUID FK → users.id | |
| `before_value` | Numeric(8,4) | |
| `after_value` | Numeric(8,4) | |
| `reason` | Text | not null |
| `adjustment_type` | String(50) | "manager_review" | "calibration" |
| `created_at` | DateTime UTC | |

---

### Model: `CalibrationSession`

```
Table: calibration_sessions
```

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `review_cycle_id` | UUID FK → review_cycles.id | |
| `organisation_id` | UUID FK | |
| `name` | String(255) | e.g. "Engineering Team Q3 Calibration" |
| `status` | Enum(CalibrationStatus) | default OPEN |
| `facilitator_id` | UUID FK → users.id | hr_admin |
| `scope_user_ids` | ARRAY(UUID) | employees included in this session |
| `notes` | Text | nullable |
| `completed_at` | DateTime UTC | nullable |
| `created_at` | DateTime UTC | |

---

### `app/scoring/calculator.py` — Pure Functions (No DB)

These must be **pure functions** with no side effects. Easy to unit test.

```python
def compute_achievement_percentage(
    actual_value: Decimal,
    target_value: Decimal,
    scoring_direction: ScoringDirection,
    minimum_value: Decimal | None = None,
) -> Decimal:
    """
    Higher-is-better: (actual / target) * 100
    Lower-is-better: (target / actual) * 100 (inverted)
    If minimum_value set and actual < minimum → return 0.0
    Handle division by zero → return 0.0
    Cap return at 200.0 (stretch target ceiling)
    """
    ...

def compute_weighted_score(achievement_pct: Decimal, weight: Decimal) -> Decimal:
    """weighted_score = achievement_pct * (weight / 100)"""
    ...

def compute_composite_score(scores: list[dict]) -> Decimal:
    """
    scores: [{"weighted_score": Decimal, "weight": Decimal}, ...]
    Returns: sum(weighted_scores) / sum(weights) * 100
    Handles case where not all KPIs have actuals (exclude from denominator or treat as 0 — configurable)
    """
    ...

def determine_rating(score: Decimal, config: ScoreConfig) -> RatingLabel:
    """Map a numeric score to a RatingLabel using ScoreConfig thresholds."""
    ...

def validate_adjustment(
    original: Decimal,
    adjusted: Decimal,
    max_adjustment: Decimal,
) -> bool:
    """Return True if abs(adjusted - original) <= max_adjustment_points."""
    ...

def compute_score_distribution(scores: list[Decimal]) -> dict:
    """
    Returns {
        "mean": Decimal,
        "median": Decimal,
        "std_dev": Decimal,
        "percentiles": {"p25": Decimal, "p50": Decimal, "p75": Decimal, "p90": Decimal},
        "rating_counts": {RatingLabel: int},
        "rating_percentages": {RatingLabel: Decimal},
    }
    """
    ...
```

---

### `app/scoring/service.py` — ScoringEngine

```python
class ScoringEngine:

    async def compute_scores_for_cycle(
        self, db, cycle_id: UUID, org_id: UUID, user_ids: list[UUID] | None = None
    ) -> list[CompositeScore]:
        """
        Main scoring run. Called when cycle is CLOSED.
        For each user (or filtered subset):
          1. Load all LOCKED targets for the user in this cycle
          2. Load latest APPROVED actual for each target
          3. For FORMULA KPIs: trigger formula evaluation if no actual exists
          4. Compute achievement_percentage per target via calculator
          5. Compute weighted_score per target
          6. Insert/update PerformanceScore rows
          7. Compute composite score via compute_composite_score()
          8. Determine overall rating via determine_rating()
          9. Insert/update CompositeScore row
        Returns list of CompositeScore objects.
        """
        ...

    async def recompute_score_for_user(
        self, db, user_id: UUID, cycle_id: UUID, org_id: UUID
    ) -> CompositeScore:
        """Recompute a single user's scores (after an actual is corrected, etc.)"""
        ...

    async def apply_manager_adjustment(
        self,
        db,
        score_id: UUID,
        manager_id: UUID,
        org_id: UUID,
        new_score: Decimal,
        reason: str,
    ) -> PerformanceScore:
        """
        Manager adjusts an individual KPI score.
        Validate against max_adjustment_points.
        Record ScoreAdjustment.
        Recompute composite score.
        """
        ...

    async def apply_composite_adjustment(
        self,
        db,
        composite_score_id: UUID,
        adjusted_by: UUID,
        org_id: UUID,
        new_weighted_average: Decimal,
        reason: str,
        adjustment_type: str,
    ) -> CompositeScore:
        """Direct adjustment to composite score (used in calibration)."""
        ...

    async def finalise_scores(
        self, db, cycle_id: UUID, org_id: UUID
    ) -> int:
        """
        Lock all composite scores → status=FINAL.
        Returns count of finalised scores.
        After this, scores cannot be changed.
        """
        ...

    async def get_score_for_user(
        self, db, user_id: UUID, cycle_id: UUID, org_id: UUID
    ) -> dict:
        """
        Returns:
        {
          "composite": CompositeScore,
          "kpi_scores": list[PerformanceScore with KPI + target nested],
          "adjustment_history": list[ScoreAdjustment],
        }
        """
        ...

    async def get_team_scores(
        self, db, manager_id: UUID, cycle_id: UUID, org_id: UUID
    ) -> list[dict]:
        """Returns scores for all direct reports of the manager."""
        ...

    async def get_org_distribution(
        self, db, cycle_id: UUID, org_id: UUID, department: DepartmentCategory | None
    ) -> dict:
        """Calls compute_score_distribution() on all composite scores. Used for heatmap."""
        ...


class CalibrationService:

    async def create_session(db, org_id, user_id, data) -> CalibrationSession
    async def get_session(db, session_id, org_id) -> CalibrationSession
    async def list_sessions(db, cycle_id, org_id) -> list[CalibrationSession]

    async def get_session_data(db, session_id, org_id) -> dict:
        """
        Returns all composite scores for users in scope, sorted by score desc.
        Includes distribution stats. Used to drive the calibration UI.
        """
        ...

    async def update_score_in_session(
        db, session_id, composite_score_id, org_id, facilitator_id,
        new_score: Decimal, note: str
    ) -> CompositeScore:
        """Apply calibration adjustment. Records adjustment as type="calibration"."""
        ...

    async def complete_session(db, session_id, org_id, facilitator_id) -> CalibrationSession:
        """Mark session COMPLETED. All adjusted scores get status=CALIBRATED."""
        ...
```

---

### Per-KPI Scoring Configuration (Enhancement 1)

The scoring engine now supports 3-level precedence for thresholds:
1. **Target-level override** — highest precedence, set per employee assignment
2. **KPI-level default** — applies whenever the KPI is used
3. **Cycle-level default** — org-wide fallback (existing ScoreConfig)

See `app/scoring/kpi_scoring_model.py` and `app/scoring/calculator.py`.

Built-in presets:
| Preset   | Exceptional | Exceeds | Meets | Partial |
|----------|------------|---------|-------|----------|
| Standard | ≥120%      | ≥100%   | ≥80%  | ≥60%     |
| Strict   | ≥130%      | ≥110%   | ≥95%  | ≥80%     |
| Lenient  | ≥110%      | ≥90%    | ≥70%  | ≥50%     |
| Binary   | ≥100%      | ≥100%   | ≥90%  | ≥0%      |
| Sales    | ≥120%      | ≥100%   | ≥85%  | ≥70%     |

---

### Router — `app/scoring/router.py`

```
POST   /scoring/compute/{cycle_id}            → run scoring engine for cycle (hr_admin)
POST   /scoring/recompute/{user_id}/{cycle_id} → recompute single user (hr_admin, manager)
GET    /scoring/users/{user_id}/{cycle_id}    → get full score breakdown
GET    /scoring/team/{cycle_id}               → manager: get team scores
GET    /scoring/org/{cycle_id}                → org distribution (executive, hr_admin)
PATCH  /scoring/kpi-score/{score_id}/adjust  → manager adjusts a KPI score
PATCH  /scoring/composite/{id}/adjust        → direct composite adjustment
POST   /scoring/finalise/{cycle_id}          → lock all scores (hr_admin)

POST   /scoring/calibration/                 → create calibration session
GET    /scoring/calibration/                 → list sessions
GET    /scoring/calibration/{session_id}     → session + all scores
PATCH  /scoring/calibration/{session_id}/scores/{composite_id}  → adjust in session
POST   /scoring/calibration/{session_id}/complete               → complete session

GET    /scoring/config/                      → get score config
POST   /scoring/config/                      → create score config (hr_admin)
PUT    /scoring/config/{id}                  → update thresholds
```

---

## Module B: Dashboards

These are **read-only aggregation endpoints** optimised for the React dashboard screens. Use SQL aggregations, not Python loops. Use `select` with joins, `func.count`, `func.avg`, `func.sum`.

### `app/dashboards/schemas.py`

```python
class EmployeeDashboard(BaseModel):
    """Everything one employee needs to render their personal dashboard."""
    user: UserRead
    active_cycle: ReviewCycleRead | None
    kpi_summary: list[KPISummaryCard]
    overall_score: Decimal | None
    overall_rating: RatingLabel | None
    score_status: ScoreStatus | None
    at_risk_count: int
    pending_actuals_count: int   # periods with no entry yet

class KPISummaryCard(BaseModel):
    target_id: UUID
    kpi_id: UUID
    kpi_name: str
    kpi_code: str
    kpi_unit: MeasurementUnit
    target_value: Decimal
    latest_actual: Decimal | None
    achievement_percentage: Decimal | None
    rating: RatingLabel | None
    weight: Decimal
    is_at_risk: bool
    trend: Literal["improving", "declining", "stable", "no_data"]
    next_period_date: date | None    # next expected entry date

class ManagerDashboard(BaseModel):
    manager: UserRead
    active_cycle: ReviewCycleRead | None
    team_size: int
    team_overview: list[TeamMemberSummary]
    at_risk_count: int
    pending_approvals_count: int
    team_average_score: Decimal | None
    team_distribution: dict[RatingLabel, int]

class TeamMemberSummary(BaseModel):
    user: UserRead
    kpi_count: int
    actuals_submitted: int
    overall_achievement: Decimal | None
    overall_rating: RatingLabel | None
    at_risk_kpis: int
    pending_actuals: int
    score_status: ScoreStatus | None

class OrgDashboard(BaseModel):
    active_cycle: ReviewCycleRead | None
    total_employees: int
    employees_with_targets: int
    employees_with_actuals: int
    avg_achievement: Decimal | None
    department_breakdown: list[DepartmentSummary]
    top_kpis_at_risk: list[KPIAtRiskSummary]
    score_distribution: dict          # from compute_score_distribution()
    period_progress: Decimal           # % of cycle elapsed

class DepartmentSummary(BaseModel):
    department: DepartmentCategory
    employee_count: int
    avg_achievement: Decimal | None
    avg_rating: RatingLabel | None
    at_risk_count: int

class KPIAtRiskSummary(BaseModel):
    kpi_id: UUID
    kpi_name: str
    affected_users: int
    avg_achievement: Decimal

class KPIProgressReport(BaseModel):
    """Detailed report for a single KPI across all users."""
    kpi: KPIRead
    cycle: ReviewCycleRead
    total_assigned: int
    submitted_actuals: int
    avg_achievement: Decimal | None
    user_progress: list[UserKPIProgress]

class UserKPIProgress(BaseModel):
    user: UserRead
    target_value: Decimal
    latest_actual: Decimal | None
    achievement_percentage: Decimal | None
    rating: RatingLabel | None
    data_points: list[ActualTimeSeriesPoint]
```

---

### `app/dashboards/service.py`

```python
async def get_employee_dashboard(db, user_id, org_id) -> EmployeeDashboard:
    """
    Single query joins: targets → actuals (latest per period) → kpis → scores
    Compute at_risk flag per target: achievement < 60% at mid-point of cycle
    Compute trend: compare last 3 actuals (slope positive/negative/flat)
    """
    ...

async def get_manager_dashboard(db, manager_id, org_id) -> ManagerDashboard:
    """
    Load direct reports from User.direct_reports
    For each report: load target summary + latest scores
    Aggregate counts
    """
    ...

async def get_org_dashboard(db, org_id, cycle_id: UUID | None = None) -> OrgDashboard:
    """
    Use active cycle if cycle_id not provided
    Department breakdown via GROUP BY users.department (or org hierarchy)
    Top-at-risk KPIs: KPIs with most users below 60% achievement
    """
    ...

async def get_kpi_progress_report(db, kpi_id, cycle_id, org_id) -> KPIProgressReport:
    """Full progress report for a single KPI — all assigned users."""
    ...

async def get_leaderboard(
    db, cycle_id, org_id,
    department: str | None,
    limit: int = 10
) -> list[dict]:
    """
    Top performers by composite score.
    Only visible to hr_admin, executive. Managers see own team only.
    """
    ...
```

---

### Router — `app/dashboards/router.py`

```
GET /dashboards/me/                          → employee personal dashboard
GET /dashboards/team/                        → manager team dashboard
GET /dashboards/org/                         → org overview (executive, hr_admin)
GET /dashboards/org/{cycle_id}              → org dashboard for specific past cycle
GET /dashboards/kpi/{kpi_id}/progress       → KPI progress across org
GET /dashboards/kpi/{kpi_id}/progress/{cycle_id}
GET /dashboards/leaderboard/{cycle_id}      → top performers
GET /dashboards/export/{cycle_id}           → download CSV of all scores (hr_admin)
```

### CSV Export Endpoint

`GET /dashboards/export/{cycle_id}` — streams a CSV with columns:
`employee_name, email, department, manager_name, kpi_code, kpi_name, target_value, final_actual, achievement_pct, weighted_score, composite_score, rating, score_status`

Use `StreamingResponse` with `io.StringIO` and `csv.writer`. Set `Content-Disposition: attachment; filename="scores_{cycle_id}_{date}.csv"`.

---

## Tests — `tests/test_scoring.py` + `tests/test_dashboards.py`

```python
# Calculator (pure functions — no DB needed)
test_compute_achievement_higher_is_better()
test_compute_achievement_lower_is_better_inverted()
test_compute_achievement_below_minimum_returns_zero()
test_compute_composite_score_weighted_average()
test_determine_rating_thresholds()
test_validate_adjustment_exceeds_cap_returns_false()
test_compute_score_distribution()

# Scoring Engine
test_compute_scores_for_cycle()
test_recompute_after_actual_change()
test_manager_adjustment_within_cap()
test_manager_adjustment_exceeds_cap_fails()
test_finalise_locks_all_scores()
test_finalised_score_cannot_be_adjusted()

# Calibration
test_create_calibration_session()
test_adjust_score_in_session()
test_complete_session_marks_calibrated()

# Dashboards
test_employee_dashboard_structure()
test_employee_dashboard_at_risk_flag()
test_manager_dashboard_team_count()
test_org_dashboard_department_breakdown()
test_export_csv_headers_and_rows()
```

---

## What to Build Next (Do NOT build yet)

- Part 5: Notifications (at-risk alerts, update reminders, period-end reminders, achievement alerts) + background task scheduling with APScheduler or Celery
- React Frontend (separate prompt series)