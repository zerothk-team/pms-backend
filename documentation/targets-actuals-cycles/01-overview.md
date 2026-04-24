# 01 — Module Overview

> **Part**: 3 — Targets, Actuals & Review Cycles  
> **Depends on**: Part 1 (Users, Organisations), Part 2 (KPIs)

---

## 1. Purpose

This module implements the **operational performance measurement layer** of the Performance Management System. While Part 2 defined *which KPIs exist and how they are measured*, Part 3 defines:

- **When** performance is evaluated — via **Review Cycles**
- **What is expected** — via **Targets** (numeric goals per KPI per person)
- **What actually happened** — via **Actuals** (recorded measured values per period)

Together these three sub-modules create a fully auditable, time-bounded performance data pipeline that feeds directly into Part 4 (Scoring & Calibration).

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Part 3 Module Boundary                       │
│                                                                     │
│   ┌──────────────────┐      ┌──────────────────┐                   │
│   │   review_cycles  │──┐   │     targets      │                   │
│   │                  │  │   │                  │                   │
│   │  ReviewCycle     │  └──▶│  KPITarget       │                   │
│   │  (DRAFT→ACTIVE   │      │  TargetMilestone │                   │
│   │   →CLOSED→ARCH.) │      │                  │                   │
│   └──────────────────┘      └────────┬─────────┘                   │
│                                      │                             │
│                              ┌───────▼──────────┐                  │
│                              │     actuals      │                  │
│                              │                  │                  │
│                              │  KPIActual       │                  │
│                              │  ActualEvidence  │                  │
│                              └──────────────────┘                  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
              │                         │
    ┌─────────▼──────┐        ┌─────────▼──────┐
    │  Part 1        │        │  Part 2        │
    │  Users / Orgs  │        │  KPIs          │
    └────────────────┘        └────────────────┘
```

### Data flow

```
[HR Admin creates ReviewCycle]
         │
         ▼
[Manager creates KPITargets for team members]  ← references KPI + ReviewCycle
         │
         ▼
[HR Admin activates ReviewCycle]  → all targets auto-locked
         │
         ▼
[Employee submits KPIActuals per period]  ← references KPITarget
         │
         ▼
[Manager approves actuals (if team/org target)]
         │
         ▼
[HR Admin closes ReviewCycle]  → triggers Part 4 scoring
```

---

## 3. Sub-module Breakdown

### 3.1 Review Cycles (`app/review_cycles/`)

| File | Responsibility |
|------|---------------|
| `models.py` | `ReviewCycle` SQLAlchemy ORM model |
| `schemas.py` | Pydantic request/response schemas |
| `service.py` | Business logic: CRUD, status transitions, overlap enforcement |
| `router.py` | FastAPI route handlers |
| `enums.py` | `CycleType`, `CycleStatus` enums |

**Key concept**: A cycle defines the date boundaries for a performance evaluation period. Only one cycle may be ACTIVE per organisation at a time.

### 3.2 Targets (`app/targets/`)

| File | Responsibility |
|------|---------------|
| `models.py` | `KPITarget`, `TargetMilestone` ORM models |
| `schemas.py` | Pydantic schemas: create, update, bulk, cascade, progress |
| `service.py` | Business logic: creation, cascade, acknowledgment, weight validation, progress computation |
| `router.py` | FastAPI route handlers |
| `enums.py` | `TargetLevel`, `TargetStatus` enums |

**Key concept**: A target links a KPI to a cycle and an assignee (individual/team/org). Targets are mutable during DRAFT and locked when the cycle activates.

### 3.3 Actuals (`app/actuals/`)

| File | Responsibility |
|------|---------------|
| `models.py` | `KPIActual`, `ActualEvidence` ORM models |
| `schemas.py` | Pydantic schemas: submit, review, update, time series, bulk |
| `service.py` | Business logic: submission, superseding, approval workflow, time series generation, formula auto-compute |
| `router.py` | FastAPI route handlers |
| `enums.py` | `ActualEntryStatus`, `ActualEntrySource` enums |

**Key concept**: Actuals record measured values period-by-period. They preserve a full audit trail — superseded records are kept. Formula-based KPIs generate actuals automatically.

---

## 4. Directory Structure

```
app/
├── review_cycles/
│   ├── __init__.py
│   ├── enums.py
│   ├── models.py
│   ├── router.py
│   ├── schemas.py
│   └── service.py
├── targets/
│   ├── __init__.py
│   ├── enums.py
│   ├── models.py
│   ├── router.py
│   ├── schemas.py
│   └── service.py
├── actuals/
│   ├── __init__.py
│   ├── enums.py
│   ├── models.py
│   ├── router.py
│   ├── schemas.py
│   └── service.py
└── utils.py        ← shared period-date helpers
```

Shared utility (`app/utils.py`):
- `get_period_start_dates(start, end, frequency)` — generates expected measurement dates for a KPI cycle
- `generate_period_label(date, frequency)` — returns human-readable label (e.g., "Jan 2025", "Q1 2025")

---

## 5. External Dependencies

| Dependency | Used by | Why |
|-----------|---------|-----|
| `app/users/models.py` | All three modules | FK to `users.id` for assignee, set_by, submitted_by, reviewed_by |
| `app/organisations/models.py` | Cycles, Targets | FK to `organisations.id` for org scoping |
| `app/kpis/models.py` | Targets, Actuals | FK to `kpis.id`; KPI frequency, unit, scoring_direction drive business rules |
| `app/kpis/formula.py` | Actuals | Formula evaluation for AUTO_FORMULA actuals |
| `app/utils.py` | All three | Measurement period generation |

---

## 6. Enum Reference

### CycleType (review_cycles/enums.py)
| Value | Meaning |
|-------|---------|
| `annual` | Full-year evaluation cycle |
| `semi_annual` | 6-month cycle |
| `quarterly` | 3-month cycle |
| `monthly` | Monthly cycle |
| `custom` | User-defined date range |

### CycleStatus (review_cycles/enums.py)
| Value | Meaning |
|-------|---------|
| `draft` | Being set up; targets can be created/edited |
| `active` | Live — targets locked, actuals can be submitted |
| `closed` | Performance period ended; triggers scoring |
| `archived` | Historical record; read-only |

### TargetLevel (targets/enums.py)
| Value | Meaning |
|-------|---------|
| `individual` | Assigned to a single user |
| `team` | Assigned to a team/department |
| `organisation` | Assigned to the whole org |

### TargetStatus (targets/enums.py)
| Value | Meaning |
|-------|---------|
| `draft` | Initial state; editable |
| `pending_acknowledgement` | Sent to employee for sign-off |
| `acknowledged` | Employee has accepted the target |
| `approved` | Manager/HR has formally approved |
| `locked` | Cycle is active; no modifications allowed |

### ActualEntryStatus (actuals/enums.py)
| Value | Meaning |
|-------|---------|
| `pending_approval` | Submitted; awaiting manager review |
| `approved` | Confirmed as the valid measurement for this period |
| `rejected` | Reviewer rejected; employee must resubmit |
| `superseded` | A newer record replaced this one; kept for audit trail |

### ActualEntrySource (actuals/enums.py)
| Value | Meaning |
|-------|---------|
| `manual` | Entered by a human via the API |
| `auto_formula` | Auto-computed from a formula KPI's dependencies |
| `import` | Bulk-imported from an external system |

---

## 7. Security Model

- All endpoints require a valid active user session (`get_current_active_user`).
- Role gates are enforced via `require_roles(*roles)` dependency factory.
- All queries are **organisation-scoped**: every query includes `organisation_id = current_user.organisation_id` so one organisation cannot read or modify another's data.
- Employees can only submit actuals for their own individual targets.
- Managers can only see pending actuals from their direct reports (unless hr_admin/executive).
- Target and actual mutations are blocked once the review cycle is ACTIVE (targets) or the record is in a terminal state (actuals).

---

## 8. Testing

Tests live in:
- `tests/test_targets.py` — 18 tests covering all target scenarios
- `tests/test_actuals.py` — 16 tests covering all actuals scenarios (2 intentionally skipped)

Run with:
```bash
.venv/bin/python -m pytest tests/test_targets.py tests/test_actuals.py -v
```

All tests use an in-memory SQLite database and mock no business logic.
