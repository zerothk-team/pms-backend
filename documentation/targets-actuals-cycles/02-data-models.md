# 02 — Data Models & Database Schema

> This document describes all five database tables introduced in Part 3, their columns, data types, constraints, indexes, and relationships.

---

## 1. Entity Relationship Overview

```
organisations ──┬──< review_cycles >──< kpi_targets >──< kpi_actuals >──< actual_evidence
                │           │                │                │
users ──────────┴───────────┘        ┌───────┘        ┌──────┘
                                      │                │
kpis ─────────────────────────────────┘                │
                                                       │
kpi_targets ──< target_milestones                      │
                                                       │
users ─────────────────────────────────────────────────┘
```

---

## 2. Table: `review_cycles`

### Purpose
Time-bounded performance evaluation period. All targets and actuals are scoped to a cycle.

### Columns

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | NOT NULL | uuid4 | Primary key |
| `name` | VARCHAR(255) | NOT NULL | — | Human-readable name, e.g. "FY 2025 Annual Review" |
| `cycle_type` | Enum(`cycletype`) | NOT NULL | — | `annual`, `semi_annual`, `quarterly`, `monthly`, `custom` |
| `status` | Enum(`cyclestatus`) | NOT NULL | `draft` | `draft`, `active`, `closed`, `archived` |
| `start_date` | DATE | NOT NULL | — | First day of the performance period |
| `end_date` | DATE | NOT NULL | — | Last day of the performance period (must be > start_date) |
| `target_setting_deadline` | DATE | NULL | — | Optional: last date targets may be set/edited |
| `actual_entry_deadline` | DATE | NULL | — | Optional: last date actuals may be submitted |
| `scoring_start_date` | DATE | NULL | — | Optional: date scoring computation may begin |
| `organisation_id` | UUID | NOT NULL | — | FK → `organisations.id` (CASCADE DELETE) |
| `created_by_id` | UUID | NULL | — | FK → `users.id` (SET NULL on user delete) |
| `created_at` | TIMESTAMPTZ | NOT NULL | now() | Record creation timestamp |
| `updated_at` | TIMESTAMPTZ | NOT NULL | now() | Last modification timestamp |

### Indexes

| Index Name | Columns | Purpose |
|-----------|---------|---------|
| `ix_review_cycle_org_status` | `organisation_id`, `status` | Fast org-filtered status queries |
| `ix_review_cycle_dates` | `start_date`, `end_date` | Overlap detection queries |

### Constraints
- `end_date > start_date` — validated at application layer (Pydantic)
- `target_setting_deadline ≤ end_date` — validated at application layer
- `actual_entry_deadline ≤ end_date` — validated at application layer
- `scoring_start_date ≥ start_date` — validated at application layer
- Only one ACTIVE cycle per organisation at a time — enforced in `service.py`

### Relationships
- `organisation`: many-to-one → `organisations`
- `created_by`: many-to-one → `users`
- `targets`: one-to-many → `kpi_targets` (cascade delete)

---

## 3. Table: `kpi_targets`

### Purpose
Defines what a specific user, team, or organisation is expected to achieve for a KPI within a review cycle.

### Columns

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | NOT NULL | uuid4 | Primary key |
| `kpi_id` | UUID | NOT NULL | — | FK → `kpis.id` (RESTRICT delete) |
| `review_cycle_id` | UUID | NOT NULL | — | FK → `review_cycles.id` (CASCADE delete) |
| `assignee_type` | Enum(`targetlevel`) | NOT NULL | — | `individual`, `team`, `organisation` |
| `assignee_user_id` | UUID | NULL | — | FK → `users.id` (CASCADE); set when `assignee_type = individual` |
| `assignee_org_id` | UUID | NULL | — | FK → `organisations.id` (CASCADE); can hold org or dept ID |
| `target_value` | NUMERIC(18,4) | NOT NULL | — | The expected achievement value (must be > 0) |
| `stretch_target_value` | NUMERIC(18,4) | NULL | — | Aspirational target (must be > target_value if set) |
| `minimum_value` | NUMERIC(18,4) | NULL | — | Minimum acceptable threshold (must be < target_value if set) |
| `weight` | NUMERIC(5,2) | NOT NULL | 100.00 | Weight of this KPI in the overall score (0–100) |
| `status` | Enum(`targetstatus`) | NOT NULL | `draft` | `draft`, `pending_acknowledgement`, `acknowledged`, `approved`, `locked` |
| `cascade_parent_id` | UUID | NULL | — | Self-FK → `kpi_targets.id` (SET NULL); set on cascaded child targets |
| `notes` | TEXT | NULL | — | Free-form notes from the target setter |
| `set_by_id` | UUID | NOT NULL | — | FK → `users.id` (RESTRICT); who created the target |
| `acknowledged_by_id` | UUID | NULL | — | FK → `users.id` (SET NULL) |
| `acknowledged_at` | TIMESTAMPTZ | NULL | — | When the assignee acknowledged the target |
| `locked_at` | TIMESTAMPTZ | NULL | — | When the target was locked (cycle activation time) |
| `created_at` | TIMESTAMPTZ | NOT NULL | now() | Record creation timestamp |
| `updated_at` | TIMESTAMPTZ | NOT NULL | now() | Last modification timestamp |

### Indexes

| Index Name | Columns | Purpose |
|-----------|---------|---------|
| `ix_kpi_target_review_cycle` | `review_cycle_id` | Fast cycle lookups |
| `ix_kpi_target_assignee_user` | `assignee_user_id` | Fast user-filtered queries |
| `ix_kpi_target_kpi` | `kpi_id` | Fast KPI-filtered queries |
| `ix_kpi_target_status` | `status` | Status dashboard filters |

### Uniqueness
- One target per `(kpi_id, review_cycle_id, assignee_user_id)` for individual targets
- One target per `(kpi_id, review_cycle_id, assignee_type, assignee_org_id)` for org targets
- Enforced at application layer (service checks before insert)

### Relationships
- `kpi`: many-to-one → `kpis`
- `review_cycle`: many-to-one → `review_cycles`
- `assignee_user`, `set_by`, `acknowledged_by`: many-to-one → `users`
- `cascade_parent` / `cascade_children`: self-referential tree
- `milestones`: one-to-many → `target_milestones` (cascade delete)
- `actuals`: one-to-many → `kpi_actuals`

---

## 4. Table: `target_milestones`

### Purpose
Intermediate checkpoints within a target's timeline. Optional. Each milestone has a date and an expected value for progress tracking.

### Columns

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | NOT NULL | uuid4 | Primary key |
| `target_id` | UUID | NOT NULL | — | FK → `kpi_targets.id` (CASCADE delete) |
| `milestone_date` | DATE | NOT NULL | — | Date on which this milestone is evaluated |
| `expected_value` | NUMERIC(18,4) | NOT NULL | — | Expected cumulative or point-in-time value by this date (must be ≥ 0) |
| `label` | VARCHAR(100) | NULL | — | Optional friendly name, e.g. "Q1 checkpoint" |
| `created_at` | TIMESTAMPTZ | NOT NULL | now() | Record creation timestamp |

### Indexes

| Index Name | Columns | Purpose |
|-----------|---------|---------|
| `ix_target_milestone_target` | `target_id` | Fast target-scoped lookups |

### Relationships
- `target`: many-to-one → `kpi_targets`

---

## 5. Table: `kpi_actuals`

### Purpose
Records the real measured value for a KPI target in a specific measurement period. Maintains a full audit trail — superseded records are retained.

### Columns

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | NOT NULL | uuid4 | Primary key |
| `target_id` | UUID | NOT NULL | — | FK → `kpi_targets.id` (CASCADE delete) |
| `kpi_id` | UUID | NOT NULL | — | FK → `kpis.id` (RESTRICT); denormalized for query efficiency |
| `period_date` | DATE | NOT NULL | — | Start date of the measurement period (e.g. 2025-01-01 for January) |
| `period_label` | VARCHAR(50) | NOT NULL | — | Human-readable label (e.g. "Jan 2025", "Q1 2025") |
| `actual_value` | NUMERIC(18,4) | NOT NULL | — | The recorded measurement value |
| `entry_source` | Enum(`actualentrysource`) | NOT NULL | `manual` | `manual`, `auto_formula`, `import` |
| `status` | Enum(`actualentrystatus`) | NOT NULL | `pending_approval` | `pending_approval`, `approved`, `rejected`, `superseded` |
| `notes` | TEXT | NULL | — | Submitter's comments or context |
| `submitted_by_id` | UUID | NULL | — | FK → `users.id` (SET NULL); NULL for `auto_formula` actuals |
| `reviewed_by_id` | UUID | NULL | — | FK → `users.id` (SET NULL); set on approval/rejection |
| `reviewed_at` | TIMESTAMPTZ | NULL | — | Timestamp of approval or rejection |
| `rejection_reason` | TEXT | NULL | — | Required when status = `rejected` |
| `created_at` | TIMESTAMPTZ | NOT NULL | now() | Record creation timestamp |
| `updated_at` | TIMESTAMPTZ | NOT NULL | now() | Last modification timestamp |

### Indexes

| Index Name | Columns | Purpose |
|-----------|---------|---------|
| `ix_kpi_actual_target_period` | `target_id`, `period_date` | Core lookup: actuals for a target in a period |
| `ix_kpi_actual_kpi` | `kpi_id` | KPI-wide reporting queries |
| `ix_kpi_actual_status` | `status` | Pending approvals dashboard |
| `ix_kpi_actual_period_date` | `period_date` | Time-range filtering |

### Audit Trail Design
When a newer actual is submitted for the same `(target_id, period_date)`:
- If an **APPROVED** record exists → it is marked `SUPERSEDED`, and a new record is created.
- If a **PENDING_APPROVAL** record exists → it is updated in-place.
- If a **REJECTED** record exists → it is marked `SUPERSEDED`, and a new record is created.

This means the complete history of submissions per period is always preserved.

### Relationships
- `target`: many-to-one → `kpi_targets`
- `kpi`: many-to-one → `kpis`
- `submitted_by`, `reviewed_by`: many-to-one → `users`
- `evidence_attachments`: one-to-many → `actual_evidence` (cascade delete)

---

## 6. Table: `actual_evidence`

### Purpose
File/URL attachments that support a specific actual entry (e.g. invoice, screenshot, report).

### Columns

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | NOT NULL | uuid4 | Primary key |
| `actual_id` | UUID | NOT NULL | — | FK → `kpi_actuals.id` (CASCADE delete) |
| `file_name` | VARCHAR(255) | NOT NULL | — | Original filename or descriptive label |
| `file_url` | TEXT | NOT NULL | — | Storage URL or relative path |
| `uploaded_by_id` | UUID | NULL | — | FK → `users.id` (SET NULL) |
| `created_at` | TIMESTAMPTZ | NOT NULL | now() | Upload timestamp |

### Indexes

| Index Name | Columns | Purpose |
|-----------|---------|---------|
| `ix_actual_evidence_actual` | `actual_id` | Fast actual-scoped evidence lookups |

### Relationships
- `actual`: many-to-one → `kpi_actuals`
- `uploaded_by`: many-to-one → `users`

---

## 7. Full Schema Diagram (Text)

```
review_cycles
 ├─ id (PK)
 ├─ organisation_id (FK → organisations)
 ├─ created_by_id (FK → users, nullable)
 ├─ name, cycle_type, status
 ├─ start_date, end_date
 └─ target_setting_deadline, actual_entry_deadline, scoring_start_date

kpi_targets
 ├─ id (PK)
 ├─ review_cycle_id (FK → review_cycles CASCADE)
 ├─ kpi_id (FK → kpis RESTRICT)
 ├─ assignee_user_id (FK → users, nullable)
 ├─ assignee_org_id (FK → organisations, nullable)
 ├─ cascade_parent_id (FK → kpi_targets self-ref, nullable)
 ├─ set_by_id (FK → users RESTRICT)
 ├─ acknowledged_by_id (FK → users, nullable)
 ├─ target_value, stretch_target_value, minimum_value
 ├─ weight, status, notes
 └─ locked_at, acknowledged_at

target_milestones
 ├─ id (PK)
 ├─ target_id (FK → kpi_targets CASCADE)
 ├─ milestone_date, expected_value, label
 └─ created_at

kpi_actuals
 ├─ id (PK)
 ├─ target_id (FK → kpi_targets CASCADE)
 ├─ kpi_id (FK → kpis RESTRICT)
 ├─ submitted_by_id (FK → users, nullable)
 ├─ reviewed_by_id (FK → users, nullable)
 ├─ period_date, period_label
 ├─ actual_value, entry_source, status
 ├─ notes, rejection_reason
 └─ reviewed_at

actual_evidence
 ├─ id (PK)
 ├─ actual_id (FK → kpi_actuals CASCADE)
 ├─ uploaded_by_id (FK → users, nullable)
 ├─ file_name, file_url
 └─ created_at
```

---

## 8. Alembic Migration

The tables above were created in migration:

```
alembic/versions/8c420a93904d_create_targets_actuals_review_cycles_.py
```

To apply:
```bash
alembic upgrade head
```

To verify:
```bash
alembic current
```
