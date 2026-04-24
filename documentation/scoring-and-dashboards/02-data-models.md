# 02 — Data Models & Database Schema

← [Back to Index](index.md)

---

## Overview

The scoring module introduces **5 tables** and **3 PostgreSQL enum types** via migration `c3d4e5f6a7b8`.

```
score_configs
performance_scores
composite_scores
score_adjustments
calibration_sessions
```

---

## Enum Types

### `ratinglabel`

Used in `performance_scores.rating` and `composite_scores.rating`.

| Value | Meaning |
|-------|---------|
| `not_rated` | No approved actuals — cannot assign a meaningful rating |
| `does_not_meet` | Achievement < `partially_meets_min` threshold |
| `partially_meets` | Achievement ≥ `partially_meets_min` but < `meets_min` |
| `meets_expectations` | Achievement ≥ `meets_min` but < `exceeds_min` |
| `exceeds_expectations` | Achievement ≥ `exceeds_min` but < `exceptional_min` |
| `exceptional` | Achievement ≥ `exceptional_min` |

### `scorestatus`

Used in `performance_scores.status` and `composite_scores.status`.

| Value | Meaning |
|-------|---------|
| `computed` | Calculated by the engine — no manual changes yet |
| `adjusted` | A manager or HR admin has applied a manual adjustment |
| `calibrated` | Adjusted during a completed calibration session |
| `final` | Locked — no further changes allowed |

### `calibrationstatus`

Used in `calibration_sessions.status`.

| Value | Meaning |
|-------|---------|
| `open` | Session created, no scores adjusted yet |
| `in_progress` | At least one score adjustment has been made |
| `completed` | Facilitator has marked the session as done |

---

## Table: `score_configs`

One row per `(organisation, review_cycle)` pair. Controls scoring thresholds and policy.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | No | `gen_random_uuid()` | Primary key |
| `organisation_id` | UUID FK→organisations | No | — | Owning organisation |
| `review_cycle_id` | UUID FK→review_cycles | No | — | Which cycle this config applies to |
| `exceptional_min` | NUMERIC(6,2) | No | 120.00 | Minimum achievement % for Exceptional |
| `exceeds_min` | NUMERIC(6,2) | No | 100.00 | Minimum for Exceeds Expectations |
| `meets_min` | NUMERIC(6,2) | No | 80.00 | Minimum for Meets Expectations |
| `partially_meets_min` | NUMERIC(6,2) | No | 60.00 | Minimum for Partially Meets |
| `does_not_meet_min` | NUMERIC(6,2) | No | 0.00 | Floor (always 0) |
| `allow_manager_adjustment` | BOOLEAN | No | true | Whether managers can apply adjustments |
| `max_adjustment_points` | NUMERIC(5,2) | No | 10.00 | Cap on how much a manager can adjust ± |
| `requires_calibration` | BOOLEAN | No | false | Must complete a calibration session before finalising |
| `created_at` | TIMESTAMPTZ | No | `now()` | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | No | `now()` | Last-updated timestamp |

**Constraints**:
- `UNIQUE (organisation_id, review_cycle_id)` — one config per cycle per org.
- Thresholds must be strictly descending: `exceptional_min > exceeds_min > meets_min > partially_meets_min ≥ 0`. This is enforced in `ScoreConfigService.create()`.

---

## Table: `performance_scores`

One row per `(target, review_cycle)` pair. Tracks an individual KPI score.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | No | `gen_random_uuid()` | Primary key |
| `user_id` | UUID FK→users | No | — | Employee this score belongs to |
| `kpi_id` | UUID FK→kpis | No | — | The KPI being scored |
| `target_id` | UUID FK→kpi_targets | No | — | The specific target (links to weight and target_value) |
| `review_cycle_id` | UUID FK→review_cycles | No | — | The review cycle |
| `organisation_id` | UUID FK→organisations | No | — | Owning organisation |
| `achievement_pct` | NUMERIC(8,4) | No | — | `(actual / target) × 100`, capped at 200 |
| `weighted_score` | NUMERIC(8,4) | No | — | `achievement_pct × (weight / 100)` |
| `final_score` | NUMERIC(8,4) | Yes | NULL | Post-adjustment score (set by manager or calibration) |
| `rating` | ratinglabel | No | — | Rating label assigned from thresholds |
| `status` | scorestatus | No | `computed` | Lifecycle status |
| `adjustment_reason` | TEXT | Yes | NULL | Free-text reason if manually adjusted |
| `computed_at` | TIMESTAMPTZ | No | — | When this score was last computed |
| `updated_at` | TIMESTAMPTZ | No | — | Last-updated timestamp |

**Constraints**:
- `UNIQUE (target_id, review_cycle_id)` — one score per target per cycle.
- Index on `(user_id, review_cycle_id)` for fast team lookups.
- Index on `(review_cycle_id, organisation_id)` for org-wide queries.

---

## Table: `composite_scores`

One row per `(user, review_cycle)` pair. The overall performance score.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | No | `gen_random_uuid()` | Primary key |
| `user_id` | UUID FK→users | No | — | Employee |
| `review_cycle_id` | UUID FK→review_cycles | No | — | The review cycle |
| `organisation_id` | UUID FK→organisations | No | — | Owning organisation |
| `weighted_average` | NUMERIC(8,4) | No | — | Raw computed weighted average |
| `final_weighted_average` | NUMERIC(8,4) | No | — | Post-adjustment weighted average |
| `rating` | ratinglabel | No | — | Rating label based on `final_weighted_average` |
| `kpi_count` | INTEGER | No | — | Total number of KPI targets for this user |
| `kpis_with_actuals` | INTEGER | No | — | KPIs that have at least one approved actual |
| `status` | scorestatus | No | `computed` | Lifecycle status |
| `manager_comment` | TEXT | Yes | NULL | Optional overall comment from manager |
| `calibration_note` | TEXT | Yes | NULL | Note from calibration session facilitator |
| `computed_at` | TIMESTAMPTZ | No | — | When the engine last ran for this user |
| `updated_at` | TIMESTAMPTZ | No | — | Last-updated timestamp |

**Constraints**:
- `UNIQUE (user_id, review_cycle_id)` — one composite per user per cycle.
- Index on `(review_cycle_id, organisation_id)` for cycle-wide queries.

---

## Table: `score_adjustments`

Immutable audit log of every score change. Never updated — only inserted.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | No | `gen_random_uuid()` | Primary key |
| `performance_score_id` | UUID FK→performance_scores | Yes | NULL | Linked KPI score (if KPI-level adjustment) |
| `composite_score_id` | UUID FK→composite_scores | Yes | NULL | Linked composite score |
| `adjusted_by` | UUID FK→users | No | — | Who made the change |
| `adjustment_type` | VARCHAR(50) | No | — | `manager_kpi`, `manager_composite`, `calibration`, `system` |
| `previous_score` | NUMERIC(8,4) | No | — | Score before adjustment |
| `new_score` | NUMERIC(8,4) | No | — | Score after adjustment |
| `reason` | TEXT | No | — | Mandatory justification text |
| `created_at` | TIMESTAMPTZ | No | `now()` | When the adjustment was made |

**Notes**:
- `performance_score_id` and `composite_score_id` are both nullable; at least one will be set.
- Index on `(composite_score_id, created_at)` for fast adjustment history lookups.

---

## Table: `calibration_sessions`

Groups composite scores for a facilitated review discussion.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | No | `gen_random_uuid()` | Primary key |
| `review_cycle_id` | UUID FK→review_cycles | No | — | The review cycle being calibrated |
| `organisation_id` | UUID FK→organisations | No | — | Owning organisation |
| `name` | VARCHAR(255) | No | — | Human-readable session name |
| `status` | calibrationstatus | No | `open` | Session lifecycle status |
| `facilitator_id` | UUID FK→users | No | — | HR admin who created the session |
| `scope_user_ids` | ARRAY(UUID) / JSON | No | `[]` | In-scope employee UUIDs |
| `notes` | TEXT | Yes | NULL | Session-level notes |
| `completed_at` | TIMESTAMPTZ | Yes | NULL | When the session was completed |
| `created_at` | TIMESTAMPTZ | No | `now()` | Creation timestamp |

**Notes**:
- `scope_user_ids` is stored as PostgreSQL `ARRAY(UUID)` in production and as a JSON text string in SQLite (for test environments). The `_UUIDListType` TypeDecorator handles this transparently.

---

## Entity-Relationship Summary

```
organisations ──< score_configs >── review_cycles
organisations ──< performance_scores >── review_cycles
organisations ──< composite_scores >── review_cycles
                  performance_scores ──> kpi_targets ──> kpis
                  performance_scores ──> users
                  composite_scores ──> users
                  score_adjustments ──> performance_scores (optional)
                  score_adjustments ──> composite_scores (optional)
                  score_adjustments ──> users (adjusted_by)
                  calibration_sessions ──> review_cycles
                  calibration_sessions ──> organisations
                  calibration_sessions ──> users (facilitator_id)
```

---

## Migration

All scoring tables are created by migration `c3d4e5f6a7b8_create_scoring_tables.py`.

To apply:
```bash
cd pms-backend
.venv/bin/python -m alembic upgrade head
```

To roll back:
```bash
.venv/bin/python -m alembic downgrade c3d4e5f6a7b8-1
```
