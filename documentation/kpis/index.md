# KPI Module — Documentation Index

> **Version**: Part 2 | **Backend**: FastAPI + SQLAlchemy 2.x async + PostgreSQL
> **Base URL**: `http://localhost:8000/api/v1`

This is the root navigation page for all documentation covering the **KPI (Key Performance Indicator) Module** of the Performance Management System.

---

## Table of Contents

| # | Document | What it covers |
|---|----------|----------------|
| 1 | [Module Overview](01-overview.md) | Purpose, architecture, module boundaries, file structure, dependencies |
| 2 | [Data Models & Database Schema](02-data-models.md) | All tables, columns, relationships, constraints, indexes, enum types |
| 3 | [Formula Engine](03-formula-engine.md) | Safe formula parser, AST whitelist, dependency resolution, cycle detection, evaluator |
| 4 | [API Reference](04-api-reference.md) | All 15 endpoints: method, path, roles, request body, query params, response shapes, error codes |
| 5 | [Status Workflow & Business Rules](05-workflows.md) | KPI lifecycle state machine, approval process, role-based transition rules, side-effects |
| 6 | [Step-by-Step Tutorials](06-tutorials.md) | Six end-to-end worked examples with real `curl` commands and full JSON request/response pairs |
| 7 | [Process & Data Flow Diagrams](07-process-flow-diagrams.md) | Mermaid diagrams: system architecture, request lifecycle, formula validation flow, status machine, data model ER, audit trail |

---

## Quick Navigation by Task

### "I want to..."

| Task | Go to |
|------|-------|
| Understand what the KPI module does and how it fits the system | [01 — Overview](01-overview.md) |
| Understand the database tables and their relationships | [02 — Data Models](02-data-models.md) |
| Learn how formula KPIs work and how to write safe formulas | [03 — Formula Engine](03-formula-engine.md) |
| Find the exact request/response shape for a specific endpoint | [04 — API Reference](04-api-reference.md) |
| Understand the KPI approval workflow and valid transitions | [05 — Workflows](05-workflows.md) |
| Follow a practical tutorial to create and manage KPIs | [06 — Tutorials](06-tutorials.md) |
| See a visual diagram of the full data flow | [07 — Diagrams](07-process-flow-diagrams.md) |

---

## Roles Referenced Throughout

| Role | Value | Capabilities |
|------|-------|--------------|
| HR Admin | `hr_admin` | Full access: create, update, delete, approve, deprecate, promote templates |
| Manager | `manager` | Create and update KPIs; cannot approve, deprecate, or delete |
| Executive | `executive` | Read-only on all KPIs |
| Employee | `employee` | Read-only on KPIs assigned to them |

---

## Base API Prefix

All KPI endpoints are served under:

```
/api/v1/kpis/
```

Interactive documentation is available at:

```
http://localhost:8000/api/v1/docs
```

---

## Related Modules

- **Organisations** — Every KPI belongs to exactly one organisation (`organisation_id`)
- **Users** — KPIs track `created_by_id` and `approved_by_id`
- **Targets** *(Part 3)* — KPIs are assigned targets per user/period
- **Actuals** *(Part 3)* — Actual values are recorded against KPIs and used to evaluate formulas
- **Scoring** *(Part 4)* — KPIs feed into performance scores

---

*Last updated: April 2026*
