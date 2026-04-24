# 04 — Targets

> Targets define what is expected — a numeric goal for a specific KPI, assigned to a person (or team/org), within a review cycle. They form the benchmark against which actual measurements are evaluated.

---

## 1. What Is a Target?

A **KPI Target** answers the question: *"What should [person/team/org] achieve for [KPI] during [cycle]?"*

Each target has:
- A **KPI** it measures
- A **review cycle** it belongs to
- An **assignee** (individual user, team, or whole org)
- A **target value** (the primary goal), optionally with stretch and minimum values
- A **weight** (its relative importance in the overall score, 0–100%)
- A **status** that governs what operations are allowed
- Optional **milestones** (intermediate checkpoints)

---

## 2. Target Status Lifecycle

```
         ┌─────────┐
         │  DRAFT  │  ← Created here; editable
         └────┬────┘
              │
     ┌────────┤ submit for acknowledgment
     │        │
     │        ▼
     │  ┌─────────────────────────┐
     │  │  PENDING_ACKNOWLEDGEMENT│  ← Employee notified
     │  └────────────┬────────────┘
     │               │ employee acknowledges
     │               ▼
     │         ┌────────────┐
     │         │ ACKNOWLEDGED│  ← Employee accepted
     │         └──────┬──────┘
     │                │ manager/hr_admin approves
     │                ▼
     └──────▶  ┌──────────┐
               │ APPROVED  │  ← Formally accepted
               └─────┬─────┘
                     │ cycle activates (automatic)
                     ▼
               ┌─────────┐
               │  LOCKED  │  ← Performance period live; no edits allowed
               └─────────┘
```

### Valid Status Transitions

| From | To | Who |
|------|----|-----|
| `draft` | `pending_acknowledgement` | hr_admin, manager, executive |
| `draft` | `approved` | hr_admin, manager, executive |
| `pending_acknowledgement` | `acknowledged` | assigned employee only |
| `acknowledged` | `approved` | hr_admin, manager, executive |
| `approved` | `draft` | hr_admin, manager, executive (revert) |
| any non-locked | `locked` | automatic on cycle activation |

**Note**: The `acknowledge_target` endpoint is the dedicated path for employee acknowledgment. General status transitions use `PATCH /targets/{id}/status`.

---

## 3. Assignee Types

| Type | Value | Meaning |
|------|-------|---------|
| Individual | `individual` | Target for a single user (`assignee_user_id` required) |
| Team | `team` | Target for a team or department |
| Organisation | `organisation` | Target for the whole organisation |

Actual submission auto-approval rules depend on assignee type:
- **Individual** targets → actuals are **auto-approved** (no review step)
- **Team/Organisation** targets → actuals go to **PENDING_APPROVAL** for manager review

---

## 4. Target Values

### Primary, Stretch, and Minimum

| Field | Required | Business Rule |
|-------|----------|---------------|
| `target_value` | **Yes** | Must be > 0; the main goal |
| `stretch_target_value` | No | Must be > `target_value` if set; aspirational |
| `minimum_value` | No | Must be < `target_value` if set; "floor" threshold |

### Weight

The `weight` field (0–100) expresses this KPI's relative importance in the overall performance score. A user should have all their KPI targets sum to 100% weight for the scoring to be meaningful.

Use `GET /targets/weights-check` to validate whether a user's targets for a cycle sum to 100%.

---

## 5. Milestones

Optional intermediate checkpoints within a target's timeline.

```json
"milestones": [
  { "milestone_date": "2025-03-31", "expected_value": 25.0, "label": "Q1 checkpoint" },
  { "milestone_date": "2025-06-30", "expected_value": 50.0, "label": "Q2 checkpoint" }
]
```

Milestones can be provided at creation or can replace all existing milestones via `PUT /targets/{id}`. In the progress endpoint, the service computes how current actuals compare against the nearest preceding milestone.

---

## 6. Cascade Targets

The **cascade** feature lets a manager distribute an organisation-level or team-level target down to individual employees, automatically creating individual child targets linked back to the parent.

### Cascade Strategies

| Strategy | How child `target_value` is computed |
|----------|--------------------------------------|
| `equal` | `parent.target_value / number_of_children` |
| `proportional` | `(weight / sum_of_weights) * parent.target_value` |
| `manual` | Each child's `target_value` is taken as-is from the `distribution` list |

### Request Shape

```json
POST /api/v1/targets/cascade
{
  "parent_target_id": "uuid",
  "strategy": "proportional",
  "distribution": [
    { "user_id": "uuid-1", "weight": 60.0 },
    { "user_id": "uuid-2", "weight": 40.0 }
  ],
  "total_check": true
}
```

### Total Check Validation

When `total_check: true` (default), the service validates that the sum of all child `target_value`s does not exceed the parent's `target_value` by more than **1% tolerance**. This prevents over-allocation.

```
sum(child_values) ≤ parent.target_value × 1.01
```

Set `total_check: false` to bypass this check.

### Cascade Tree

Each child target has `cascade_parent_id` pointing back to the parent. The cascade tree can be retrieved via `GET /targets/{id}/cascade-tree`.

---

## 7. Bulk Create

Assign the same KPI to multiple users in a single request:

```json
POST /api/v1/targets/bulk
{
  "kpi_id": "uuid",
  "review_cycle_id": "uuid",
  "user_targets": [
    { "user_id": "uuid-1", "target_value": 100.0, "weight": 30 },
    { "user_id": "uuid-2", "target_value": 80.0, "weight": 25 }
  ]
}
```

Each entry in `user_targets` creates an `INDIVIDUAL` target. Duplicate detection runs per entry.

---

## 8. Acknowledgment Workflow

1. Manager sets a target → status = `draft`
2. Manager transitions to `pending_acknowledgement` (optional step)
3. Employee calls `POST /targets/{id}/acknowledge` → status = `acknowledged`
4. Manager/HR approves → status = `approved`

Employees may also acknowledge a target that is still in `draft` or `approved` status (e.g. if the workflow skipped the formal pending step).

---

## 9. Locking

Targets are locked in two ways:

1. **Automatic bulk lock**: When a review cycle transitions from `DRAFT` → `ACTIVE`, all non-locked targets in that cycle are immediately set to `LOCKED`.
2. **Immediate lock**: If a target is created while the cycle is already `ACTIVE`, it is locked on creation.

**Locked targets cannot be**:
- Updated (value or milestone changes) → HTTP 403
- Status-transitioned → HTTP 403

---

## 10. Progress Endpoint

`GET /targets/{id}/progress` returns the target enriched with live progress metrics:

| Field | Description |
|-------|-------------|
| `latest_actual_value` | Most recently APPROVED actual value |
| `total_actual_to_date` | Cumulative sum (for count/currency KPIs) or latest value (for rate/percentage KPIs) |
| `achievement_percentage` | `(actual / target) × 100`, direction-adjusted for LOWER_IS_BETTER KPIs |
| `is_at_risk` | `true` if past 50% of cycle duration AND `achievement_percentage < 60%` |
| `trend` | `"improving"` / `"declining"` / `"stable"` based on the last 3 approved actuals |
| `milestone_status` | List of milestones with actual vs expected values |

### Achievement Formula

For **HIGHER_IS_BETTER** KPIs:
```
achievement = (actual / target) × 100
```

For **LOWER_IS_BETTER** KPIs (e.g. cost, defect rate):
```
achievement = (target / actual) × 100
```
Achieving *less* is better, so being under target results in > 100% achievement.

---

## 11. Weights Check

`GET /targets/weights-check?user_id=...&cycle_id=...`

Returns:
```json
{
  "user_id": "...",
  "cycle_id": "...",
  "total_weight": "85.00",
  "is_valid": false,
  "warning": "Total weight is 85.00%, not 100%. Weighted scoring results will be proportional to this total."
}
```

---

## 12. Roles and Permissions

| Operation | hr_admin | manager | executive | employee |
|-----------|----------|---------|-----------|---------|
| Create target | ✅ | ✅ | ✅ | ❌ |
| Bulk create | ✅ | ✅ | ✅ | ❌ |
| Cascade | ✅ | ✅ | ✅ | ❌ |
| Update target | ✅ | ✅ | ✅ | ❌ |
| Acknowledge own target | ❌ | ❌ | ❌ | ✅ |
| Approve/transition status | ✅ | ✅ | ✅ | ❌ |
| Get / list targets | ✅ | ✅ | ✅ | ✅ (own) |
| Progress endpoint | ✅ | ✅ | ✅ | ✅ (own) |
| Weights check | ✅ | ✅ | ✅ | ✅ (own) |
| Cascade tree | ✅ | ✅ | ✅ | ❌ |

---

## 13. Error Scenarios

| Scenario | HTTP Code | Error |
|----------|-----------|-------|
| KPI not ACTIVE | 400 | BadRequestException |
| Review cycle is CLOSED/ARCHIVED | 400 | BadRequestException |
| Duplicate target (same KPI/cycle/assignee) | 409 | ConflictException |
| `stretch_target_value` ≤ `target_value` | 422 | Pydantic validation error |
| `minimum_value` ≥ `target_value` | 422 | Pydantic validation error |
| `assignee_user_id` missing for INDIVIDUAL type | 422 | Pydantic validation error |
| Updating a LOCKED target | 403 | ForbiddenException |
| Employee acknowledging another employee's target | 403 | ForbiddenException |
| Cascade total exceeds parent (total_check=true) | 400 | BadRequestException |
| Invalid status transition | 400 | BadRequestException |
| Target not found or wrong org | 404 | NotFoundException |
