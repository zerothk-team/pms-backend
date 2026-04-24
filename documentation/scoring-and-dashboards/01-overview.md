# 01 — Scoring & Dashboards Module Overview

← [Back to Index](index.md)

---

## What is the Scoring & Dashboards Module?

The Scoring & Dashboards module (Part 4) is the **performance evaluation layer** of the system. It consumes KPI targets and actual submissions produced in Part 3, then:

1. **Calculates achievement percentages** for every KPI an employee has a target for.
2. **Computes a weighted composite score** that summarises overall performance in a single number.
3. **Assigns a rating label** (Does Not Meet → Exceptional) based on configurable thresholds.
4. **Supports manager adjustments and calibration** to account for qualitative context.
5. **Finalises (locks) scores** so they become permanent records.
6. **Exposes role-tailored dashboards** so employees, managers, and executives see the right data.

---

## Position in the System Architecture

```
┌──────────────────────────────────────────────────────────┐
│                Performance Management System              │
│                                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐  │
│  │   Auth   │  │  Users   │  │   Organisations      │  │
│  └──────────┘  └──────────┘  └──────────────────────┘  │
│                                                          │
│  ┌────────────────────────────────────────────────────┐ │
│  │                  KPI Module (Part 2)               │ │
│  │   Definitions · Categories · Tags · Lifecycle      │ │
│  └───────────────────────┬────────────────────────────┘ │
│                          │                               │
│  ┌────────────────────────────────────────────────────┐ │
│  │          Targets + Actuals Module (Part 3)         │ │
│  │   Targets · Actuals · Review Cycles                │ │
│  └───────────────────────┬────────────────────────────┘ │
│                          │                               │
│  ┌────────────────────────────────────────────────────┐ │
│  │       ★  Scoring + Dashboards (Part 4)  ★         │ │
│  │   Calculator · Scoring Engine · Calibration        │ │
│  │   Score Config · Adjustments · Finalisation        │ │
│  │   Employee / Manager / Org Dashboards              │ │
│  │   KPI Progress Reports · Leaderboard · CSV Export  │ │
│  └────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────┘
```

---

## File Structure

```
app/scoring/
├── __init__.py          # Package marker
├── enums.py             # RatingLabel, ScoreStatus, CalibrationStatus, AdjustmentType
├── models.py            # 5 SQLAlchemy ORM models
│                        #   ScoreConfig, PerformanceScore,
│                        #   CompositeScore, ScoreAdjustment, CalibrationSession
├── schemas.py           # Pydantic v2 request/response schemas
├── calculator.py        # Pure functions — no DB, no HTTP, unit-testable in isolation
│                        #   compute_achievement_percentage, compute_weighted_score,
│                        #   compute_composite_score, determine_rating,
│                        #   validate_adjustment, compute_score_distribution
├── service.py           # Three service classes:
│                        #   ScoreConfigService — CRUD for ScoreConfig
│                        #   ScoringEngine      — run/recompute/adjust/finalise
│                        #   CalibrationService — sessions and calibrated adjustments
└── router.py            # FastAPI router — 14 endpoints under /api/v1/scoring/

app/dashboards/
├── __init__.py
├── schemas.py           # Pydantic schemas for all five dashboard types
├── service.py           # DashboardService — all read-only aggregation queries
└── router.py            # FastAPI router — 8 endpoints under /api/v1/dashboards/

alembic/versions/
└── c3d4e5f6a7b8_create_scoring_tables.py   # Migration: 5 tables + 3 enum types
```

---

## Key Concepts

### ScoreConfig

A per-cycle, per-organisation configuration that controls:
- **Rating thresholds** — the achievement % cut-offs for each rating label.
- **Manager adjustment cap** — maximum points a manager can add or deduct.
- **Calibration requirement** — whether a completed calibration session is required before finalisation.

If no `ScoreConfig` has been created for a cycle, the system uses built-in defaults:

| Threshold | Default |
|-----------|---------|
| Exceptional ≥ | 120.00 % |
| Exceeds Expectations ≥ | 100.00 % |
| Meets Expectations ≥ | 80.00 % |
| Partially Meets ≥ | 60.00 % |
| Does Not Meet | < 60.00 % |
| Max adjustment | ± 10.00 points |
| Requires calibration | No |

### PerformanceScore (KPI Score)

One row per `(KPITarget, ReviewCycle)` pair. Captures:
- `achievement_pct` — raw achievement before weighting.
- `weighted_score` — achievement × (weight / 100).
- `final_score` — post-adjustment score used in composite calculation.
- `rating` — label assigned from thresholds.
- `status` — COMPUTED → ADJUSTED → FINAL.

### CompositeScore

One row per `(User, ReviewCycle)` pair. Captures:
- `weighted_average` — the raw computed composite.
- `final_weighted_average` — the post-adjustment composite.
- `rating` — the label on the final composite.
- `kpi_count / kpis_with_actuals` — coverage metrics.
- `status` — COMPUTED → ADJUSTED → CALIBRATED → FINAL.

### ScoreAdjustment (Audit Trail)

Every change to a score creates an immutable audit record. Fields include:
- `adjustment_type` — `manager_kpi`, `manager_composite`, `calibration`, or `system`.
- `previous_score / new_score` — before and after values.
- `reason` — mandatory free-text justification.
- `adjusted_by` — the user who made the change.

### CalibrationSession

A facilitated review session where HR brings composite scores for a group of employees into alignment. Each session:
- Has a list of in-scope users (`scope_user_ids`).
- Starts OPEN, moves to IN_PROGRESS when the first adjustment is made, and is COMPLETED manually.
- Records all adjustments as `ScoreAdjustment` rows with `adjustment_type=calibration`.

---

## Design Principles

| Principle | How it is applied |
|-----------|-------------------|
| **Precision** | All monetary/percentage values use `Decimal` (not `float`) to avoid rounding errors |
| **Audit trail** | Every score change creates an immutable `ScoreAdjustment` row |
| **Idempotent scoring** | Re-running `POST /scoring/compute/{cycle_id}` is safe — existing rows are updated in place |
| **Adjustment propagation** | KPI-level manager adjustments automatically cascade to recompute the composite score |
| **Hard lock** | Finalised scores (`FINAL` status) cannot be adjusted or recalculated |
| **Default config** | The system works without a `ScoreConfig` record — sensible defaults are applied automatically |
| **Separation of concerns** | `calculator.py` is pure Python with no imports from FastAPI or SQLAlchemy, making it trivially testable |
