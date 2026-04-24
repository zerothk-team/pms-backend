# 05 — Status Workflows & Lifecycle

← [Back to Index](index.md)

---

## Overview

Every KPI passes through a structured approval workflow before it can be used in targets, actuals, or scoring. The workflow enforces quality gates and creates accountability by tracking who approved what and when.

---

## State Machine

### Five Lifecycle Stages

| Status | Value | Meaning |
|--------|-------|---------|
| `draft` | `"draft"` | Being written; not yet reviewed |
| `pending_approval` | `"pending_approval"` | Submitted for review |
| `active` | `"active"` | Approved and ready for use |
| `deprecated` | `"deprecated"` | Being phased out; old data keeps it connected |
| `archived` | `"archived"` | Permanently retired; read-only |

### Valid Transitions Table

```
Current Status      │  Target Status      │  Who Can Do It
────────────────────┼─────────────────────┼───────────────────────────
draft               │  pending_approval   │  Any authenticated user
draft               │  active             │  hr_admin only (fast-track)
pending_approval    │  active             │  hr_admin only
pending_approval    │  draft              │  Any authenticated user
active              │  deprecated         │  Any authenticated user
deprecated          │  archived           │  Any authenticated user
<any>               │  draft              │  hr_admin only (override/reset)
────────────────────┼─────────────────────┼───────────────────────────
archived            │  (none)             │  Terminal — no transitions
```

> **hr_admin override**: An `hr_admin` can reset any non-archived KPI back to `draft`. This allows recovery from mistaken deprecation or a blocked approval queue.

---

## Transition Logic (Code)

The service layer encodes transitions in two constant structures:

```python
# All users can trigger these transitions
_TRANSITIONS: dict[KPIStatus, set[KPIStatus]] = {
    KPIStatus.DRAFT:              {KPIStatus.PENDING_APPROVAL, KPIStatus.ACTIVE},
    KPIStatus.PENDING_APPROVAL:   {KPIStatus.ACTIVE, KPIStatus.DRAFT},
    KPIStatus.ACTIVE:             {KPIStatus.DEPRECATED},
    KPIStatus.DEPRECATED:         {KPIStatus.ARCHIVED},
    KPIStatus.ARCHIVED:           set(),   # terminal
}

# hr_admin can additionally target
_HR_ADMIN_EXTRA: set[KPIStatus] = {KPIStatus.DRAFT}
```

On each `PATCH /kpis/{id}/status` call:

1. Load the KPI from the database
2. Compute `allowed = _TRANSITIONS[current_status]`
3. If caller is `hr_admin`, add `_HR_ADMIN_EXTRA` to `allowed`
4. If `target_status not in allowed` → raise `400 Bad Request`
5. Apply special handling for gated transitions (step 6)
6. For `PENDING_APPROVAL → ACTIVE`: check caller is `hr_admin`, else raise `400`
7. Set timestamp fields where applicable
8. Commit and return updated KPI

---

## Side Effects Per Transition

### `→ active`

```python
kpi.approved_by_id = user_id    # UUID of the hr_admin who approved
kpi.approved_at    = datetime.utcnow()
kpi.status         = KPIStatus.ACTIVE
```

**Business meaning**: The KPI is now published. It can be assigned as a target, have actuals logged against it, and contribute to scoring.

---

### `→ deprecated`

```python
kpi.deprecated_at = datetime.utcnow()
kpi.status        = KPIStatus.DEPRECATED
```

**Business meaning**: Existing historical data remains intact. The KPI cannot be assigned to new targets, but old targets still reference it. Managers should transition their teams off it before archiving.

---

### `→ archived`

```python
kpi.status = KPIStatus.ARCHIVED
# No additional fields set
```

**Business meaning**: Permanently read-only. Cannot be updated, cannot have new history recorded. Purely for audit preservation.

---

### `→ draft` (reset)

```python
kpi.status = KPIStatus.DRAFT
# approved_by_id / approved_at / deprecated_at are NOT cleared
# (preserves audit history of what occurred before the reset)
```

**Business meaning**: Returns the KPI to an editable, unpublished state. Used by `hr_admin` to unlock a KPI for revision.

---

## Standard Workflow: Manager Creates, Admin Approves

This is the most common real-world flow.

```
Manager (role: manager)          hr_admin (role: hr_admin)
        │                                │
        │  POST /kpis/                   │
        │  status: "draft" (automatic)   │
        │◄────────────────────────────── │
        │                                │
        │  Team reviews KPI definition   │
        │                                │
        │  PATCH /kpis/{id}/status       │
        │  { "status": "pending_approval"│
        │    "reason": "For Q3 targets" }│
        │───────────────────────────────►│
        │                                │  hr_admin reviews KPI
        │                                │
        │                                │  PATCH /kpis/{id}/status
        │                                │  { "status": "active" }
        │◄───────────────────────────────│
        │                                │
        │  KPI now has:                  │
        │    approved_by_id = hr_admin   │
        │    approved_at = <timestamp>   │
```

---

## Fast-Track Workflow: hr_admin Creates and Activates Directly

An `hr_admin` can skip the pending_approval stage entirely.

```
hr_admin
    │
    │  POST /kpis/
    │  status: "draft" (automatic)
    │
    │  PATCH /kpis/{id}/status
    │  { "status": "active" }     ← allowed: DRAFT → ACTIVE (hr_admin only)
    │
    │  KPI is now active immediately
```

---

## Deprecation and Archiving Workflow

When a KPI becomes outdated (e.g. a formula changes, business strategy shifts):

```
Currently: status = "active"

Step 1: Deprecate
    PATCH /kpis/{id}/status
    { "status": "deprecated", "reason": "Replacing with GROSS_MARGIN_V2" }
    → deprecated_at set, status = deprecated

Step 2: Migrate
    Assign NEW_KPI to existing targets
    Close out open actuals referencing the old KPI
    Wait for all scoring cycles to complete

Step 3: Archive
    PATCH /kpis/{id}/status
    { "status": "archived" }
    → status = archived (terminal)
```

---

## History Interaction

Every status change that goes through `update_kpi_status` does **not** create a new `KPIHistory` entry directly — history is created by `update_kpi` (definition changes). Status changes are visible in the KPI's `status` field and the `approved_at` / `deprecated_at` timestamps.

To trace who changed the status and when, inspect:
- `kpi.approved_by_id` + `kpi.approved_at` — who approved it
- `kpi.deprecated_at` — when it was deprecated
- `GET /kpis/{id}/history` — full definition change log (not status transitions)

---

## Error Messages Reference

| Scenario | HTTP Code | Message |
|----------|-----------|---------|
| Invalid transition (any user) | 400 | `"Invalid status transition from <from> to <to>"` |
| PENDING_APPROVAL → ACTIVE without hr_admin | 400 | `"Only hr_admin can approve a KPI from PENDING_APPROVAL to ACTIVE"` |
| DRAFT → ACTIVE without hr_admin | 400 | Caught by same transition check: not in `_TRANSITIONS[DRAFT]` for non-admin |
| Attempting to transition ARCHIVED | 400 | `"Invalid status transition from archived to <to>"` |

---

## KPI Lifecycle vs. Downstream Modules

| Status | Can be assigned to new targets? | Can have actuals logged? | Included in scoring? |
|--------|---------------------------------|--------------------------|---------------------|
| `draft` | No | No | No |
| `pending_approval` | No | No | No |
| `active` | Yes | Yes | Yes |
| `deprecated` | No | Existing only | Yes (historical) |
| `archived` | No | No | No |

> *These constraints are enforced by the targets, actuals, and scoring modules (not the KPI module itself). The KPI module only controls status transitions.*

---

← [Back to Index](index.md) | Previous: [04 — API Reference](04-api-reference.md) | Next: [06 — Tutorials →](06-tutorials.md)
