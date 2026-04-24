# Copilot Prompt — Part 3: Target Setting, Cascading & Actuals Entry
> **Model**: Claude Sonnet 4.6 | **Depends on**: Parts 1 & 2 complete

---

## Context

Parts 1 and 2 are complete — project is scaffolded, auth/users work, and KPI definitions are fully built. Now build the **target setting system** and **actuals (data entry) system**. These two modules are closely linked:

- **Targets** define what an employee/team must achieve for a KPI in a given review period
- **Actuals** are the real values entered against those targets over time
- Together they enable the progress tracking and eventual scoring in Part 4

---

## What to Build in This Part

```
app/
├── review_cycles/
│   ├── __init__.py
│   ├── models.py
│   ├── schemas.py
│   ├── service.py
│   └── router.py
│
├── targets/
│   ├── __init__.py
│   ├── models.py
│   ├── schemas.py
│   ├── service.py
│   └── router.py
│
├── actuals/
│   ├── __init__.py
│   ├── models.py
│   ├── schemas.py
│   ├── service.py
│   └── router.py
│
└── kpis/
    └── formula.py     ← extend: add evaluate_formula_for_period()
```

---

## Module A: Review Cycles

### Enums — add to `app/review_cycles/enums.py`

```python
class CycleStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"           # targets can be set; actuals can be entered
    CLOSED = "closed"           # period ended; actuals locked; scoring runs
    ARCHIVED = "archived"

class CycleType(str, Enum):
    ANNUAL = "annual"
    SEMI_ANNUAL = "semi_annual"
    QUARTERLY = "quarterly"
    CUSTOM = "custom"
```

### Model: `ReviewCycle`

```
Table: review_cycles
```

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `name` | String(255) | e.g. "Q3 2025 Performance Review" |
| `cycle_type` | Enum(CycleType) | |
| `status` | Enum(CycleStatus) | default DRAFT |
| `start_date` | Date | not null |
| `end_date` | Date | not null |
| `target_setting_deadline` | Date | nullable — last date to set targets |
| `actual_entry_deadline` | Date | nullable — last date to enter actuals |
| `scoring_start_date` | Date | nullable — when scoring period begins |
| `organisation_id` | UUID FK → organisations.id | not null |
| `created_by_id` | UUID FK → users.id | |
| `created_at` | DateTime UTC | |
| `updated_at` | DateTime UTC | |

**Constraints:** `end_date > start_date`, no overlapping cycles per org.

### Schemas — `app/review_cycles/schemas.py`

```python
class ReviewCycleCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    cycle_type: CycleType
    start_date: date
    end_date: date
    target_setting_deadline: date | None = None
    actual_entry_deadline: date | None = None
    scoring_start_date: date | None = None

    @model_validator(mode="after")
    def validate_dates(self):
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        return self

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
    created_at: datetime

class ReviewCycleStatusUpdate(BaseModel):
    status: CycleStatus
    reason: str | None = None
```

### Service: `ReviewCycleService`

```python
async def create_cycle(db, org_id, user_id, data) -> ReviewCycle
async def get_by_id(db, cycle_id, org_id) -> ReviewCycle
async def list_cycles(db, org_id, status: CycleStatus | None) -> list[ReviewCycle]
async def get_active_cycle(db, org_id) -> ReviewCycle | None   # cycle where today is in range
async def update_status(db, cycle_id, org_id, data) -> ReviewCycle:
    # ACTIVE → CLOSED: trigger period-close notifications (stub)
    # DRAFT → ACTIVE: validate no overlap with other ACTIVE cycle
    ...
async def get_current_measurement_periods(cycle: ReviewCycle, kpi_frequency: MeasurementFrequency) -> list[date]:
    # Return list of period start dates within the cycle based on KPI frequency
    # e.g. monthly KPI in Q1 cycle → [2025-01-01, 2025-02-01, 2025-03-01]
    ...
```

### Router: `GET/POST /review-cycles/`, `GET/PUT /review-cycles/{id}`, `PATCH /review-cycles/{id}/status`

---

## Module B: Targets

### Enums — `app/targets/enums.py`

```python
class TargetLevel(str, Enum):
    ORGANISATION = "organisation"
    DEPARTMENT = "department"
    TEAM = "team"
    INDIVIDUAL = "individual"

class TargetStatus(str, Enum):
    DRAFT = "draft"
    PENDING_ACKNOWLEDGEMENT = "pending_acknowledgement"   # waiting for employee to confirm
    ACKNOWLEDGED = "acknowledged"
    APPROVED = "approved"
    LOCKED = "locked"        # period started, no changes allowed
```

### Model: `KPITarget`

```
Table: kpi_targets
```

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `kpi_id` | UUID FK → kpis.id | not null |
| `review_cycle_id` | UUID FK → review_cycles.id | not null |
| `assignee_type` | Enum(TargetLevel) | not null |
| `assignee_user_id` | UUID FK → users.id | nullable — set when assignee_type=INDIVIDUAL |
| `assignee_team_id` | UUID FK (future) | nullable |
| `assignee_org_id` | UUID FK → organisations.id | nullable |
| `target_value` | Numeric(18,4) | not null — the main target |
| `stretch_target_value` | Numeric(18,4) | nullable — exceeds 100% achievement |
| `minimum_value` | Numeric(18,4) | nullable — below this = 0% score |
| `weight` | Numeric(5,2) | default 100.00 — percentage weight for composite score |
| `status` | Enum(TargetStatus) | default DRAFT |
| `cascade_parent_id` | UUID FK → kpi_targets.id | nullable — tracks cascade lineage |
| `notes` | Text | nullable |
| `set_by_id` | UUID FK → users.id | who created this target |
| `acknowledged_by_id` | UUID FK → users.id | nullable |
| `acknowledged_at` | DateTime UTC | nullable |
| `locked_at` | DateTime UTC | nullable |
| `created_at` | DateTime UTC | |
| `updated_at` | DateTime UTC | |

**Unique constraint:** `(kpi_id, review_cycle_id, assignee_user_id)` — one target per employee per KPI per cycle.

**Relationships:**
- `kpi` → KPI
- `review_cycle` → ReviewCycle
- `assignee_user` → User
- `cascade_parent` → KPITarget (self-ref)
- `cascade_children` → list[KPITarget]
- `milestones` → list[TargetMilestone]
- `actuals` → list[KPIActual]

---

### Model: `TargetMilestone`

Interim checkpoints within a target.

```
Table: target_milestones
```

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `target_id` | UUID FK → kpi_targets.id | not null |
| `milestone_date` | Date | not null — the checkpoint date |
| `expected_value` | Numeric(18,4) | not null — target value at this checkpoint |
| `label` | String(100) | nullable — e.g. "End of Q1" |
| `created_at` | DateTime UTC | |

---

### Schemas — `app/targets/schemas.py`

```python
class MilestoneCreate(BaseModel):
    milestone_date: date
    expected_value: Decimal = Field(ge=0)
    label: str | None = Field(default=None, max_length=100)

class KPITargetCreate(BaseModel):
    kpi_id: UUID
    review_cycle_id: UUID
    assignee_type: TargetLevel
    assignee_user_id: UUID | None = None
    target_value: Decimal = Field(gt=0)
    stretch_target_value: Decimal | None = None
    minimum_value: Decimal | None = None
    weight: Decimal = Field(default=Decimal("100.00"), ge=0, le=100)
    notes: str | None = None
    milestones: list[MilestoneCreate] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_values(self):
        if self.stretch_target_value and self.stretch_target_value <= self.target_value:
            raise ValueError("stretch_target_value must be greater than target_value")
        if self.minimum_value and self.minimum_value >= self.target_value:
            raise ValueError("minimum_value must be less than target_value")
        return self

class KPITargetBulkCreate(BaseModel):
    """Assign same KPI target to multiple users at once (manager assigns to team)."""
    kpi_id: UUID
    review_cycle_id: UUID
    user_targets: list[dict]   # [{user_id, target_value, weight, stretch_target_value?}]

class CascadeTargetRequest(BaseModel):
    """Cascade an org/department target down to individuals."""
    parent_target_id: UUID
    distribution: list[dict]  # [{user_id, target_value, weight}]
    strategy: Literal["proportional", "equal", "manual"] = "manual"
    total_check: bool = True   # if True, validate sum of children ≈ parent

class KPITargetUpdate(BaseModel):
    target_value: Decimal | None = None
    stretch_target_value: Decimal | None = None
    minimum_value: Decimal | None = None
    weight: Decimal | None = None
    notes: str | None = None
    milestones: list[MilestoneCreate] | None = None  # replaces all milestones

class KPITargetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    kpi_id: UUID
    kpi: KPIRead     # nested KPI detail
    review_cycle_id: UUID
    assignee_type: TargetLevel
    assignee_user_id: UUID | None
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
    # Computed fields (populated by service):
    current_actual_value: Decimal | None = None
    achievement_percentage: Decimal | None = None
    is_at_risk: bool = False
```

---

### Service: `TargetService` — `app/targets/service.py`

```python
async def create_target(db, org_id, user_id, data: KPITargetCreate) -> KPITarget:
    # 1. Verify KPI exists and is ACTIVE
    # 2. Verify review_cycle exists and is ACTIVE
    # 3. Check user has permission to set target for assignee
    # 4. Check no duplicate target for this KPI+cycle+user
    # 5. Create target + milestones
    # 6. If review cycle has started → status = LOCKED immediately
    ...

async def bulk_create_targets(db, org_id, user_id, data: KPITargetBulkCreate) -> list[KPITarget]:
    # Create multiple targets in a single transaction
    ...

async def cascade_target(db, org_id, user_id, data: CascadeTargetRequest) -> list[KPITarget]:
    # Distribute parent target to individuals
    # If strategy="proportional": target_value = (user_weight / sum_weights) * parent.target_value
    # If strategy="equal": target_value = parent.target_value / num_users
    # If strategy="manual": use provided values directly
    # Validate total if total_check=True
    # Set cascade_parent_id on each child target
    ...

async def get_target_by_id(db, target_id, org_id) -> KPITarget
async def get_user_targets_for_cycle(db, user_id, cycle_id, org_id) -> list[KPITarget]
async def get_team_targets_for_cycle(db, manager_id, cycle_id, org_id) -> list[KPITarget]

async def update_target(db, target_id, org_id, user_id, data: KPITargetUpdate) -> KPITarget:
    # Raise ForbiddenException if target is LOCKED

async def acknowledge_target(db, target_id, user_id) -> KPITarget:
    # Only the assignee can acknowledge their own target
    # Sets acknowledged_by_id, acknowledged_at, status=ACKNOWLEDGED

async def lock_all_targets_for_cycle(db, cycle_id, org_id) -> int:
    # Called when review cycle status changes to ACTIVE
    # Bulk-update all APPROVED/ACKNOWLEDGED targets → LOCKED
    # Returns count of locked targets

async def get_target_with_progress(db, target_id, org_id) -> dict:
    # Returns target + computed progress metrics:
    # - latest_actual: most recent KPIActual entry
    # - total_actual_to_date: sum or latest (depends on KPI aggregation type)
    # - achievement_percentage: (actual / target) * 100
    # - milestone_status: for each milestone, actual vs expected
    # - is_at_risk: True if achievement_percentage < 60% at mid-period
    # - trend: "improving" | "declining" | "stable" (based on last 3 actuals)
    ...

async def validate_weights_for_user_cycle(db, user_id, cycle_id) -> dict:
    # Returns {"total_weight": float, "is_valid": bool, "warning": str | None}
    # Warn if total weight != 100.0
    ...
```

### Router — `app/targets/router.py`

```
POST   /targets/                           → create single target
POST   /targets/bulk/                      → bulk create for team
POST   /targets/cascade/                   → cascade parent target to users
GET    /targets/                           → list targets (filter by cycle, user, kpi)
GET    /targets/me/                        → current user's own targets in active cycle
GET    /targets/{target_id}               → single target with progress data
PUT    /targets/{target_id}               → update target (blocked if locked)
PATCH  /targets/{target_id}/acknowledge  → employee acknowledges their target
GET    /targets/weights-check/            → validate weight sum for user+cycle
GET    /targets/{target_id}/cascade-tree → show parent → children cascade tree
```

Query params for `GET /targets/`:
```python
cycle_id: UUID | None
user_id: UUID | None
kpi_id: UUID | None
assignee_type: TargetLevel | None
status: TargetStatus | None
at_risk_only: bool = False
page: int = 1
size: int = Query(20, le=100)
```

---

## Module C: Actuals (Data Entry)

### Enums — `app/actuals/enums.py`

```python
class ActualEntrySource(str, Enum):
    MANUAL = "manual"               # human entered
    AUTO_FORMULA = "auto_formula"   # computed by formula engine
    AUTO_INTEGRATION = "auto_integration"  # synced from external system

class ActualEntryStatus(str, Enum):
    PENDING_APPROVAL = "pending_approval"  # awaiting manager sign-off
    APPROVED = "approved"
    REJECTED = "rejected"          # manager sent back for correction
    SUPERSEDED = "superseded"      # replaced by a newer entry for same period
```

### Model: `KPIActual`

```
Table: kpi_actuals
```

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `target_id` | UUID FK → kpi_targets.id | not null |
| `kpi_id` | UUID FK → kpis.id | not null (denormalised for query speed) |
| `period_date` | Date | not null — start of the measurement period |
| `period_label` | String(50) | e.g. "Jan 2025", "Week 3", auto-generated |
| `actual_value` | Numeric(18,4) | not null |
| `entry_source` | Enum(ActualEntrySource) | default MANUAL |
| `status` | Enum(ActualEntryStatus) | default APPROVED (manual skips approval by default) |
| `notes` | Text | nullable |
| `submitted_by_id` | UUID FK → users.id | not null |
| `reviewed_by_id` | UUID FK → users.id | nullable |
| `reviewed_at` | DateTime UTC | nullable |
| `rejection_reason` | Text | nullable |
| `created_at` | DateTime UTC | |
| `updated_at` | DateTime UTC | |

**Unique constraint:** `(target_id, period_date)` — only one active actual per period per target. When re-submitting: mark old as SUPERSEDED, insert new.

**Relationships:**
- `target` → KPITarget
- `kpi` → KPI
- `evidence_attachments` → list[ActualEvidence]

---

### Model: `ActualEvidence`

```
Table: actual_evidence
```

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `actual_id` | UUID FK → kpi_actuals.id | not null |
| `file_name` | String(255) | |
| `file_url` | String(1000) | S3/storage URL |
| `file_type` | String(50) | MIME type |
| `uploaded_by_id` | UUID FK → users.id | |
| `created_at` | DateTime UTC | |

---

### Schemas — `app/actuals/schemas.py`

```python
class KPIActualCreate(BaseModel):
    target_id: UUID
    period_date: date
    actual_value: Decimal
    notes: str | None = None
    # evidence uploaded separately via /actuals/{id}/evidence

class KPIActualBulkCreate(BaseModel):
    """Submit multiple periods at once (e.g. catch-up entry)."""
    entries: list[KPIActualCreate] = Field(min_length=1, max_length=50)

class KPIActualUpdate(BaseModel):
    actual_value: Decimal | None = None
    notes: str | None = None

class KPIActualReview(BaseModel):
    action: Literal["approve", "reject"]
    rejection_reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def require_reason_for_reject(self):
        if self.action == "reject" and not self.rejection_reason:
            raise ValueError("rejection_reason is required when rejecting an actual")
        return self

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
    submitted_by_id: UUID
    reviewed_by_id: UUID | None
    reviewed_at: datetime | None
    rejection_reason: str | None
    evidence_attachments: list[ActualEvidenceRead]
    created_at: datetime
    # Computed:
    achievement_percentage: Decimal | None = None   # (actual / target) * 100
    vs_milestone: Decimal | None = None             # actual - milestone.expected_value

class ActualEvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    file_name: str
    file_url: str
    file_type: str
    uploaded_by_id: UUID
    created_at: datetime

class ActualTimeSeriesPoint(BaseModel):
    period_date: date
    period_label: str
    actual_value: Decimal
    target_value: Decimal
    milestone_value: Decimal | None
    achievement_percentage: Decimal

class ActualTimeSeries(BaseModel):
    target_id: UUID
    kpi_id: UUID
    kpi_name: str
    kpi_unit: MeasurementUnit
    data_points: list[ActualTimeSeriesPoint]
    overall_achievement: Decimal   # % of annual target achieved to date
```

---

### Service: `ActualService` — `app/actuals/service.py`

```python
async def submit_actual(db, org_id, user_id, data: KPIActualCreate) -> KPIActual:
    # 1. Verify target exists, is LOCKED (cycle is ACTIVE)
    # 2. Check user has permission (own target, or manager for team target)
    # 3. Validate period_date falls within cycle + matches KPI frequency
    # 4. Check for existing actual for this period:
    #    - If exists and APPROVED: mark old as SUPERSEDED, create new (keeps history)
    #    - If exists and PENDING: update in-place
    # 5. Generate period_label from period_date + frequency
    # 6. If KPI requires manager approval: set status=PENDING_APPROVAL, trigger notification (stub)
    # 7. Recalculate at-risk status on the parent target
    ...

async def submit_bulk_actuals(db, org_id, user_id, data: KPIActualBulkCreate) -> list[KPIActual]:
    # Submit multiple periods in one transaction
    ...

async def review_actual(db, actual_id, org_id, manager_id, data: KPIActualReview) -> KPIActual:
    # Manager approves/rejects a pending actual
    # On reject: trigger notification to employee (stub)
    ...

async def get_actual_by_id(db, actual_id, org_id) -> KPIActual

async def list_actuals_for_target(db, target_id, org_id, include_superseded=False) -> list[KPIActual]

async def get_time_series(db, target_id, org_id) -> ActualTimeSeries:
    # Build full time series from cycle start to today
    # Fill missing periods with None (no entry yet)
    # Compute achievement_percentage per period
    ...

async def get_pending_approvals_for_manager(db, manager_id, org_id) -> list[KPIActual]:
    # All PENDING_APPROVAL actuals from the manager's direct reports
    ...

async def compute_formula_actuals(db, cycle_id, org_id, period_date: date) -> list[KPIActual]:
    # For all FORMULA KPIs in the cycle: resolve dependencies, evaluate, auto-insert actual
    # Called as a scheduled job or triggered manually
    ...

async def add_evidence(db, actual_id, org_id, user_id, file_name, file_url, file_type) -> ActualEvidence
async def delete_evidence(db, evidence_id, org_id, user_id) -> None
```

---

### Router — `app/actuals/router.py`

```
POST   /actuals/                          → submit actual value
POST   /actuals/bulk/                     → bulk submit multiple periods
GET    /actuals/                          → list actuals (filter by target, kpi, period, status)
GET    /actuals/pending-review/           → manager: list pending approval actuals
GET    /actuals/{actual_id}              → single actual
PUT    /actuals/{actual_id}              → edit own actual (if still PENDING)
PATCH  /actuals/{actual_id}/review      → manager approve/reject
GET    /actuals/time-series/{target_id} → time series data for chart
POST   /actuals/{actual_id}/evidence    → upload evidence attachment
DELETE /actuals/{actual_id}/evidence/{evidence_id} → remove evidence
POST   /actuals/compute-formulas/       → trigger formula recalculation (hr_admin)
```

---

## Helper: Period Label Generator

Add `generate_period_label(period_date: date, frequency: MeasurementFrequency) -> str`:

```python
# Examples:
# daily:     "01 Jan 2025"
# weekly:    "Week 1, Jan 2025"
# monthly:   "January 2025"
# quarterly: "Q1 2025"
# yearly:    "2025"
```

Add `get_period_start_dates(start: date, end: date, frequency: MeasurementFrequency) -> list[date]` — used to generate expected periods for a cycle and validate that submitted `period_date` values are aligned.

---

## Alembic Migration

```bash
alembic revision --autogenerate -m "create_targets_actuals_tables"
```

Verify the migration includes: `review_cycles`, `kpi_targets`, `target_milestones`, `kpi_actuals`, `actual_evidence` tables with all constraints and indexes.

---

## Tests — `tests/test_targets.py` + `tests/test_actuals.py`

```python
# Targets
test_create_target_success()
test_create_duplicate_target_fails()                # 409
test_cascade_target_proportional()
test_cascade_target_total_check_fails()             # 422
test_bulk_create_targets()
test_acknowledge_target()
test_update_locked_target_fails()                   # 403
test_weights_check_warn_not_100()

# Actuals
test_submit_actual_success()
test_submit_actual_wrong_period_fails()             # 422 — period outside cycle
test_resubmit_supersedes_old()
test_bulk_submit_actuals()
test_manager_approve_actual()
test_manager_reject_actual_requires_reason()
test_get_time_series_fills_missing_periods()
test_formula_kpi_auto_actual()
```

---

## What to Build Next (Do NOT build yet)

- Part 4: Scoring engine, composite scores, period-end lock, calibration
- Part 5: Notifications (alerts, reminders), dashboard & reporting endpoints