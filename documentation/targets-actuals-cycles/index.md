# Targets, Actuals & Review Cycles — Documentation Index

> **Version**: Part 3 | **Backend**: FastAPI + SQLAlchemy 2.x async + PostgreSQL  
> **Base URL**: `http://localhost:8000/api/v1`

This is the root navigation page for all documentation covering the **Targets, Actuals, and Review Cycles** module of the Performance Management System. This module is the operational heart of PMS — it governs *when* performance is measured (review cycles), *what* is expected (targets), and *what actually happened* (actuals).

---

## Table of Contents

| # | Document | What it covers |
|---|----------|----------------|
| 1 | [Module Overview](01-overview.md) | Purpose, architecture, module boundaries, file structure, inter-module dependencies |
| 2 | [Data Models & Database Schema](02-data-models.md) | All 5 tables, columns, data types, constraints, indexes, enum types, FK relationships |
| 3 | [Review Cycles](03-review-cycles.md) | Cycle lifecycle, state machine, activation side-effects, overlap enforcement |
| 4 | [Targets](04-targets.md) | Target setting, locking, cascade strategies, acknowledgment workflow, progress metrics |
| 5 | [Actuals](05-actuals.md) | Actual submission, superseding, approval workflow, time series, evidence attachments |
| 6 | [API Reference](06-api-reference.md) | All 30+ endpoints: method, path, roles, request body, query params, response, error codes |
| 7 | [End-to-End Workflows](07-workflows.md) | Four complete business workflows traced from API call through DB to response |
| 8 | [Process & Data Flow Diagrams](08-process-flow-diagrams.md) | Mermaid diagrams: state machines, ER diagram, request lifecycle, cascade tree |

---

## Quick Navigation by Task

### "I want to..."

| Task | Go to |
|------|-------|
| Understand what this module does and how it fits the system | [01 — Overview](01-overview.md) |
| Understand the database tables and relationships | [02 — Data Models](02-data-models.md) |
| Learn how review cycles work and their valid state transitions | [03 — Review Cycles](03-review-cycles.md) |
| Understand target setting, cascade, and the acknowledgment flow | [04 — Targets](04-targets.md) |
| Understand how actual values are submitted and approved | [05 — Actuals](05-actuals.md) |
| Find the exact request/response shape for a specific endpoint | [06 — API Reference](06-api-reference.md) |
| Trace a complete end-to-end business scenario | [07 — Workflows](07-workflows.md) |
| See visual diagrams of the state machines and data flow | [08 — Diagrams](08-process-flow-diagrams.md) |

---

## Module at a Glance

### Three Modules, One Cohesive Flow

```
Review Cycle (the when)
    └── KPI Targets (the what — expected values)
            └── KPI Actuals (the reality — measured values)
```

1. An **HR Admin** creates a **Review Cycle** (e.g., "FY 2025 Annual Review").
2. **Managers** set **KPI Targets** for their team members during the DRAFT stage.
3. The cycle is **activated** — all outstanding targets are automatically **locked**.
4. **Employees** submit **KPI Actuals** for each measurement period.
5. For team/org targets, a **manager reviews and approves** the submitted actuals.
6. The cycle is **closed** and scores are computed in **Part 4 (Scoring)**.

---

## Roles Referenced Throughout

| Role | Value | Capabilities |
|------|-------|--------------|
| HR Admin | `hr_admin` | Full access to all operations; can create/activate/close cycles; set targets for anyone |
| Manager | `manager` | Set targets for their team; review and approve actuals; read all data in their scope |
| Executive | `executive` | Read-only plus target-setting capability; treated like hr_admin for most write operations |
| Employee | `employee` | Submit actuals for their own individual targets; acknowledge their own targets; read-only otherwise |

---

## Base API Prefixes

| Module | Prefix |
|--------|--------|
| Review Cycles | `/api/v1/review-cycles/` |
| Targets | `/api/v1/targets/` |
| Actuals | `/api/v1/actuals/` |

Interactive documentation: `http://localhost:8000/docs`
