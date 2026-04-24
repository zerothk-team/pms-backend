# 01 — KPI Module Overview

← [Back to Index](index.md)

---

## What is the KPI Module?

The KPI module (`app/kpis/`) is the **core domain layer** of the Performance Management System. Every other module — Targets, Actuals, and Scoring — depends on KPI definitions as its source of truth.

A **KPI (Key Performance Indicator)** is a named, quantified measure of performance. In this system a KPI definition captures:

- **What** is being measured (name, description, code)
- **How** it is measured (unit, decimal precision, scoring direction)
- **When** it is measured (measurement frequency)
- **Where** the value comes from (manual entry, calculated formula, or external integration)
- **Who** can see and use it (organisation scope, category, tags)
- **What state** it is in (draft → active → deprecated lifecycle)

---

## Position in the System Architecture

```
┌─────────────────────────────────────────────────┐
│              Performance Management System       │
│                                                 │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐ │
│  │   Auth   │  │  Users   │  │ Organisations │ │
│  └──────────┘  └──────────┘  └───────────────┘ │
│                                                 │
│  ┌─────────────────────────────────────────────┐│
│  │         ★  KPI Module  (Part 2)  ★          ││
│  │   Definitions · Categories · Tags · History ││
│  │   Formula Engine · Templates · Lifecycle     ││
│  └───────────────────────┬─────────────────────┘│
│                          │ depends on            │
│  ┌───────────┐ ┌─────────▼──────┐ ┌──────────┐ │
│  │  Targets  │ │    Actuals     │ │ Scoring  │ │
│  │  (Part 3) │ │    (Part 3)    │ │ (Part 4) │ │
│  └───────────┘ └────────────────┘ └──────────┘ │
└─────────────────────────────────────────────────┘
```

---

## File Structure

```
app/kpis/
├── __init__.py          # Package marker
├── enums.py             # All KPI-specific Python Enum classes
├── models.py            # SQLAlchemy ORM models (5 models + 2 join tables)
├── schemas.py           # Pydantic v2 request/response schemas
├── service.py           # KPIService — all async business logic
├── router.py            # FastAPI router — 15 endpoints under /api/v1/kpis/
├── formula.py           # Safe formula parser, dependency resolver, evaluator
└── seeds.py             # 13 pre-built KPI template seed records
```

---

## Key Concepts

### KPI Code

Every KPI has a `code` — an uppercase, underscore-separated slug that uniquely identifies it within an organisation. Codes are used in formula expressions to reference other KPIs.

```
SALES_WIN_RATE
GROSS_PROFIT_MARGIN
EMPLOYEE_TURNOVER_RATE
```

Rules:
- Must match `^[A-Z0-9_]+$`
- Minimum 2 characters, maximum 50
- **Unique per organisation** (the same code can exist in different organisations)

### Data Source Types

A KPI value can come from three sources:

| Type | Meaning |
|------|---------|
| `manual` | A human enters the value directly. Most common type. |
| `formula` | The value is computed from other KPIs using a safe expression. |
| `integration` | The value is synced from an external system (stub — not yet implemented). |

### Measurement Units

| Unit | Use case |
|------|----------|
| `percentage` | Rates, growth, margins (0–100 or 0–∞) |
| `currency` | Monetary values tied to the org's currency |
| `count` | Integer counts (calls, tickets, units) |
| `score` | Arbitrary numeric scores (e.g., NPS, satisfaction 0–10) |
| `ratio` | Ratios such as 3.5:1 |
| `duration_hours` | Time-based measurements (hiring duration, resolution time) |
| `custom` | Free-form — use `unit_label` field to describe the unit |

### Scoring Direction

Tells the scoring engine whether a higher or lower value is better:

- `higher_is_better` — revenue, NPS, on-time delivery
- `lower_is_better` — defect rate, churn, cost, time-to-hire

### KPI Lifecycle (Status)

KPIs move through a formal approval lifecycle before they can be used:

```
DRAFT → PENDING_APPROVAL → ACTIVE → DEPRECATED → ARCHIVED
```

See [05 — Workflows](05-workflows.md) for the complete transition rules.

---

## Module Dependencies

| Depends on | Why |
|------------|-----|
| `app/database.py` | `Base` for ORM model inheritance, `AsyncSession` |
| `app/config.py` | `settings.DEBUG` to trigger seed on startup |
| `app/exceptions.py` | `NotFoundException`, `ConflictException`, `BadRequestException` |
| `app/dependencies.py` | `get_current_active_user`, `require_roles` for route guards |
| `app/users/models.py` | `User` model (FK references for created_by, approved_by) |
| `app/organisations/models.py` | `Organisation` model (FK reference for organisation_id) |

---

## Entry Points

### HTTP API

All endpoints are mounted in `app/main.py`:

```python
app.include_router(kpis_router, prefix=settings.API_V1_PREFIX)
```

This registers all routes under `/api/v1/kpis/`.

### Startup Seed

`app/main.py` runs the seed function during startup when `DEBUG=True`:

```python
if settings.DEBUG:
    async with AsyncSessionLocal() as db:
        await seed_kpi_templates(db)
```

This inserts 13 curated KPI templates into the `kpi_templates` table if it is empty. It is idempotent (checks count before inserting).

### Alembic Migration

The database schema is created by migration `1811d467c578_create_kpi_tables`. Run it with:

```bash
alembic upgrade head
```

---

## Summary of Capabilities

| Capability | Endpoint | Roles |
|------------|----------|-------|
| Browse KPI categories | `GET /kpis/categories/` | All |
| Create a category | `POST /kpis/categories/` | hr_admin, manager |
| Update a category | `PUT /kpis/categories/{id}` | hr_admin |
| Delete a category | `DELETE /kpis/categories/{id}` | hr_admin |
| Browse tags | `GET /kpis/tags/` | All |
| List KPIs (paginated + filtered) | `GET /kpis/` | All |
| Create a KPI | `POST /kpis/` | hr_admin, manager |
| Get KPI with dependencies | `GET /kpis/{id}` | All |
| Update KPI definition | `PUT /kpis/{id}` | hr_admin, manager |
| Update KPI status | `PATCH /kpis/{id}/status` | All (role-restricted transitions) |
| View version history | `GET /kpis/{id}/history` | All |
| Promote KPI to template | `POST /kpis/{id}/promote-template` | hr_admin |
| Browse system templates | `GET /kpis/templates/` | All |
| Clone template to KPI | `POST /kpis/templates/clone/` | hr_admin, manager |
| Validate formula expression | `POST /kpis/validate-formula` | All |

---

← [Back to Index](index.md) | Next: [Data Models →](02-data-models.md)
