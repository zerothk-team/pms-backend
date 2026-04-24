# Scoring & Dashboards Module — Documentation Index

> **Version**: Part 4 | **Backend**: FastAPI + SQLAlchemy 2.x async + PostgreSQL
> **Base URLs**: `http://localhost:8000/api/v1/scoring/` and `http://localhost:8000/api/v1/dashboards/`

This is the root navigation page for all documentation covering the **Scoring Engine** and **Dashboards** modules of the Performance Management System.

---

## Table of Contents

| # | Document | What it covers |
|---|----------|----------------|
| 1 | [Module Overview](01-overview.md) | Purpose, architecture, module boundaries, file structure, dependencies |
| 2 | [Data Models & Database Schema](02-data-models.md) | All tables, columns, relationships, constraints, indexes, enum types |
| 3 | [Scoring Engine Algorithm](03-scoring-engine.md) | Formula details, achievement calculation, composite scoring, adjustment rules, finalisation |
| 4 | [API Reference — Scoring](04-api-reference-scoring.md) | All 14 scoring endpoints: method, path, roles, request/response shapes, error codes |
| 5 | [API Reference — Dashboards](05-api-reference-dashboards.md) | All 8 dashboard endpoints: method, path, roles, request/response shapes |
| 6 | [Workflows & Business Rules](06-workflows.md) | Score lifecycle state machine, calibration flow, finalisation rules |
| 7 | [Step-by-Step Tutorials](07-tutorials.md) | Five end-to-end worked examples with real `curl` commands and full JSON |
| 8 | [Process & Data Flow Diagrams](08-process-flow-diagrams.md) | Mermaid diagrams: system architecture, scoring pipeline, calibration flow, data model ER |

---

## Quick Navigation by Task

### "I want to…"

| Task | Go to |
|------|-------|
| Understand what the scoring engine does and how it fits the system | [01 — Overview](01-overview.md) |
| Understand the database tables and their relationships | [02 — Data Models](02-data-models.md) |
| Understand exactly how scores are calculated mathematically | [03 — Scoring Engine](03-scoring-engine.md) |
| Find the request/response shape for a specific scoring endpoint | [04 — API Reference (Scoring)](04-api-reference-scoring.md) |
| Find the request/response shape for a specific dashboard endpoint | [05 — API Reference (Dashboards)](05-api-reference-dashboards.md) |
| Understand the score status lifecycle and valid transitions | [06 — Workflows](06-workflows.md) |
| Follow a practical tutorial to run scoring end-to-end | [07 — Tutorials](07-tutorials.md) |
| See a visual diagram of the scoring pipeline | [08 — Diagrams](08-process-flow-diagrams.md) |

---

## Roles Referenced Throughout

| Role | Value | Capabilities |
|------|-------|--------------|
| HR Admin | `hr_admin` | Full access: run scoring, adjust scores, manage calibration, finalise, view all dashboards |
| Executive | `executive` | Read-only on all scores and dashboards |
| Manager | `manager` | Apply KPI-level adjustments for direct reports; view team scores and dashboard |
| Employee | `employee` | View own scores and personal dashboard only |

---

## Base API Prefixes

| Module | Prefix |
|--------|--------|
| Scoring | `/api/v1/scoring/` |
| Dashboards | `/api/v1/dashboards/` |

Interactive documentation: `http://localhost:8000/docs`
