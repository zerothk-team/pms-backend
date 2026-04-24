# 03 — Review Cycles

> Review cycles are the time-bounded containers that govern when performance is evaluated. Every target and actual in the system belongs to exactly one review cycle.

---

## 1. What Is a Review Cycle?

A **review cycle** defines:
- The **date range** of a performance evaluation period (`start_date` → `end_date`)
- The **type** of cycle (`annual`, `quarterly`, etc.)
- Optional **operational deadlines** (target-setting cutoff, actuals entry cutoff, scoring start date)
- The **status** of the cycle, which gates what operations are allowed

A cycle passes through four lifecycle states. Each state transition has specific business rules and may trigger side-effects (such as auto-locking all targets).

---

## 2. Lifecycle State Machine

```
        ┌─────────┐
        │  DRAFT  │  ← Initial state on creation
        └────┬────┘
             │ activate (hr_admin)
             │ [validates no overlap with existing ACTIVE cycle]
             │ [side-effect: locks all outstanding targets]
             ▼
        ┌─────────┐
        │ ACTIVE  │  ← Targets locked; actuals can be submitted
        └────┬────┘
             │ close (hr_admin)
             │ [side-effect: stub for scoring trigger]
             ▼
        ┌─────────┐
        │ CLOSED  │  ← Period ended; actuals entry typically done
        └────┬────┘
             │ archive (hr_admin)
             ▼
        ┌──────────┐
        │ ARCHIVED │  ← Historical record; fully read-only
        └──────────┘
```

### HR Admin Reversal Transitions

HR admins have additional reversal transitions for corrections:

| From | To | Use case |
|------|----|----------|
| `active` | `draft` | Revert to allow target corrections before period begins |
| `closed` | `active` | Re-open a closed cycle for late actual submissions |

---

## 3. Business Rules

### Creation Rules
1. `end_date` must be strictly after `start_date`.
2. `target_setting_deadline`, if provided, must be ≤ `end_date`.
3. `actual_entry_deadline`, if provided, must be ≤ `end_date`.
4. `scoring_start_date`, if provided, must be ≥ `start_date`.
5. No ACTIVE cycle may overlap the proposed date range for the same organisation.

### Activation Rules (DRAFT → ACTIVE)
1. Must validate no other ACTIVE cycle overlaps the cycle's dates.
2. **Side-effect**: All `KPITarget` records belonging to this cycle that are in `draft`, `pending_acknowledgement`, `acknowledged`, or `approved` status are immediately transitioned to `locked`. Their `locked_at` timestamp is set.
3. This ensures that once the performance period begins, the agreed-upon targets cannot be modified.

### Edit Rules
- Only **DRAFT** cycles can have their metadata updated (name, deadline dates).
- Core dates (`start_date`, `end_date`) and `cycle_type` are immutable once set.
- ACTIVE, CLOSED, and ARCHIVED cycles are read-only (except status transitions by hr_admin).

### Uniqueness Constraint
- Only **one ACTIVE cycle** may exist per organisation at any time.
- This is enforced both on creation and on activation.

---

## 4. Operational Deadlines (Optional Fields)

These are informational fields. The application does not currently enforce deadline cutoffs automatically — they are available for the frontend to display warnings or for future enforcement logic.

| Field | Purpose |
|-------|---------|
| `target_setting_deadline` | Last date targets should be created/confirmed |
| `actual_entry_deadline` | Last date employees should submit actuals |
| `scoring_start_date` | Earliest date scoring computation can begin |

---

## 5. Period Generation

When targets and actuals reference a cycle, the system uses the cycle's `start_date` and `end_date` together with the KPI's `frequency` to generate expected measurement periods.

**Example**: A `monthly` KPI in a cycle from 2025-01-01 to 2025-12-31 generates 12 expected period dates:
```
[2025-01-01, 2025-02-01, 2025-03-01, ..., 2025-12-01]
```

This is the shared `get_period_start_dates()` utility from `app/utils.py`. Actual `period_date` values submitted by employees must align to these expected dates — misaligned dates are rejected with HTTP 400.

---

## 6. Roles and Permissions

| Operation | hr_admin | manager | executive | employee |
|-----------|----------|---------|-----------|---------|
| Create cycle | ✅ | ❌ | ❌ | ❌ |
| List / get cycle | ✅ | ✅ | ✅ | ✅ |
| Update cycle (deadline dates) | ✅ | ❌ | ❌ | ❌ |
| Activate cycle (DRAFT → ACTIVE) | ✅ | ❌ | ❌ | ❌ |
| Close cycle (ACTIVE → CLOSED) | ✅ | ❌ | ❌ | ❌ |
| Archive cycle (CLOSED → ARCHIVED) | ✅ | ❌ | ❌ | ❌ |
| Revert ACTIVE → DRAFT | ✅ | ❌ | ❌ | ❌ |
| Revert CLOSED → ACTIVE | ✅ | ❌ | ❌ | ❌ |
| Get active cycle | ✅ | ✅ | ✅ | ✅ |

---

## 7. API Quick Reference

Full details are in [06 — API Reference](06-api-reference.md).

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/review-cycles/` | Create a new cycle |
| `GET` | `/api/v1/review-cycles/` | List cycles (paginated, optional status filter) |
| `GET` | `/api/v1/review-cycles/active` | Get the currently active cycle |
| `GET` | `/api/v1/review-cycles/{id}` | Get a specific cycle |
| `PUT` | `/api/v1/review-cycles/{id}` | Update deadline dates (DRAFT only) |
| `PATCH` | `/api/v1/review-cycles/{id}/status` | Transition cycle status |

---

## 8. Example: Full Cycle Lifecycle

### Step 1 — Create

```json
POST /api/v1/review-cycles/
{
  "name": "FY 2025 Annual Review",
  "cycle_type": "annual",
  "start_date": "2025-01-01",
  "end_date": "2025-12-31",
  "target_setting_deadline": "2025-01-31",
  "actual_entry_deadline": "2025-12-31",
  "scoring_start_date": "2026-01-01"
}
```

Response: `201 Created` with `status: "draft"`

### Step 2 — Activate

```json
PATCH /api/v1/review-cycles/{id}/status
{ "status": "active" }
```

Response: `200 OK` with `status: "active"`  
Side-effect: All draft/pending/acknowledged/approved targets in this cycle are now `locked`.

### Step 3 — Close

```json
PATCH /api/v1/review-cycles/{id}/status
{ "status": "closed" }
```

Response: `200 OK` with `status: "closed"`

### Step 4 — Archive

```json
PATCH /api/v1/review-cycles/{id}/status
{ "status": "archived" }
```

Response: `200 OK` with `status: "archived"`

---

## 9. Error Scenarios

| Scenario | HTTP Code | Error |
|----------|-----------|-------|
| `end_date` ≤ `start_date` | 422 | Pydantic validation error |
| Activating with overlapping ACTIVE cycle | 409 | ConflictException |
| Editing a non-DRAFT cycle | 400 | BadRequestException |
| Invalid status transition | 400 | BadRequestException |
| Cycle not found or wrong org | 404 | NotFoundException |
| Non-hr_admin attempting write | 403 | ForbiddenException |
