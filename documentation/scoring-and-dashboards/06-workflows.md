# 06 — Workflows & Business Rules

← [Back to Index](index.md)

---

## Score Status Lifecycle

Both `PerformanceScore` and `CompositeScore` have a `status` column that controls what operations are permitted.

```
                    ┌──────────────────────────────────┐
                    │                                  │
        POST /compute  ┌──────────┐                   │
        (engine run)   │ COMPUTED │                   │
    ───────────────►   └──────────┘                   │
                           │                          │
              Manager or HR admin                     │
              applies adjustment                      │
                           │                          │
                    ┌──────▼──────┐                   │
                    │  ADJUSTED   │                   │
                    └─────────────┘                   │
                           │                          │
               Adjustment in calibration              │
               session (hr_admin only)               │
                           │                          │
                    ┌──────▼──────┐                   │
                    │ CALIBRATED  │                   │
                    └─────────────┘                   │
                           │                          │
              POST /finalise (hr_admin, cycle closed) │
                           │                          │
                    ┌──────▼──────┐                   │
                    │    FINAL    │◄─────────────────-┘
                    └─────────────┘
                      (immutable)
```

### Rules by Status

| Status | Can be recomputed? | Can be adjusted (manager)? | Can be adjusted (calibration)? |
|--------|-------------------|---------------------------|---------------------------------|
| `COMPUTED` | Yes | Yes | Yes |
| `ADJUSTED` | Yes (resets to computed unless already adjusted) | Yes | Yes |
| `CALIBRATED` | Yes | Yes | Yes |
| `FINAL` | **No** | **No** | **No** |

**Important**: When the engine re-runs (`POST /compute` or `/recompute`), it will NOT overwrite `final_score` on a PerformanceScore that is `ADJUSTED`, `CALIBRATED`, or `FINAL`. The raw `achievement_pct` and `weighted_score` are always recalculated, but `final_score` is only set on `COMPUTED` records.

---

## Calibration Session Lifecycle

```
                     POST /calibration
                          │
                    ┌─────▼────┐
                    │   OPEN   │
                    └──────────┘
                          │
          First PATCH /calibration/{id}/scores/{composite_id}
                          │
                    ┌─────▼──────────┐
                    │  IN_PROGRESS   │
                    └────────────────┘
                          │
          POST /calibration/{id}/complete
                          │
                    ┌─────▼──────────┐
                    │   COMPLETED    │
                    └────────────────┘
                         (no further session updates)
```

---

## Scoring Pipeline Workflow

The complete end-to-end flow from cycle creation to finalised scores:

```
1. HR Admin creates a Review Cycle (cycle_type: annual/quarterly/etc.)
   └─► Cycle status: DRAFT → ACTIVE

2. (Optional) HR Admin creates a ScoreConfig for the cycle
   └─► Defines custom thresholds and adjustment policy

3. Managers/HR assign KPI Targets to employees
   └─► Target status: DRAFT → LOCKED (when cycle becomes active)

4. Employees submit Actuals throughout the cycle
   └─► Actual status: PENDING_APPROVAL → APPROVED (manager approves)

5. HR Admin closes the cycle
   └─► Cycle status: ACTIVE → CLOSED

6. HR Admin runs scoring: POST /scoring/compute/{cycle_id}
   └─► Creates PerformanceScore + CompositeScore rows
   └─► Status: COMPUTED; Rating labels assigned

7. (Optional) Managers apply adjustments
   └─► PATCH /scoring/kpi-score/{id}/adjust
   └─► Composite is automatically recomputed
   └─► Status: COMPUTED → ADJUSTED

8. (Optional) HR Admin runs calibration sessions
   └─► POST /scoring/calibration
   └─► PATCH /scoring/calibration/{id}/scores/{composite_id}
   └─► POST /scoring/calibration/{id}/complete
   └─► Status: ADJUSTED → CALIBRATED

9. HR Admin finalises scores
   └─► POST /scoring/finalise/{cycle_id}
   └─► Pre-condition: if requires_calibration=true, must have completed session
   └─► Status: → FINAL (immutable)
```

---

## Manager Adjustment Rules

| Rule | Detail |
|------|--------|
| **Who can adjust** | `manager` and `hr_admin` roles |
| **What can be adjusted** | Individual KPI scores (`PATCH /kpi-score/{id}/adjust`) or composite scores directly (`PATCH /composite/{id}/adjust`) |
| **Adjustment cap** | `abs(new_score - current_score) ≤ max_adjustment_points` (default: ±10) |
| **Mandatory reason** | `reason` field is required (minimum 5 chars) |
| **FINAL scores** | Cannot be adjusted — returns `403 Forbidden` |
| **Automatic propagation** | KPI-level adjustments automatically recompute the composite score |
| **Audit record** | Every adjustment creates an immutable `ScoreAdjustment` row |

### Adjustment Propagation Detail

When a manager adjusts a KPI score:

1. `performance_score.final_score` is set to the new value.
2. The engine recomputes the composite using `final_score` (not `weighted_score`) for ALL KPI scores.
3. `composite_score.final_weighted_average` and `composite_score.rating` are updated.
4. `composite_score.status` is set to `ADJUSTED`.

This ensures that KPI-level context (e.g. "equipment failure in H2") flows through to the employee's overall rating.

---

## Calibration Adjustment Rules

| Rule | Detail |
|------|--------|
| **Who can calibrate** | `hr_admin` only |
| **No cap** | Calibration adjustments bypass the `max_adjustment_points` restriction |
| **Session scope** | Only composite scores listed in `scope_user_ids` can be adjusted within a session |
| **Session must be open/in-progress** | Cannot adjust a `completed` session |
| **Audit record** | Recorded with `adjustment_type = "calibration"` |
| **Score status** | Composite moves to `CALIBRATED` |

---

## Finalisation Rules

`POST /scoring/finalise/{cycle_id}` enforces these checks:

1. The cycle must have `status = "closed"` — actively running cycles cannot be finalised.
2. If `ScoreConfig.requires_calibration = true`, at least one `CalibrationSession` with `status = "completed"` must exist for that cycle.
3. All `CompositeScore` and `PerformanceScore` rows for the cycle are set to `FINAL`.

After finalisation:
- `GET /scoring/users/{user_id}/{cycle_id}` still works (read-only).
- `PATCH /kpi-score/{id}/adjust` returns `403 Forbidden`.
- `PATCH /composite/{id}/adjust` returns `403 Forbidden`.
- `POST /compute/{cycle_id}` will run but individual scores with `status = FINAL` are preserved.

---

## Access Control Summary

| Endpoint group | employee | manager | hr_admin | executive |
|----------------|----------|---------|---------|-----------|
| View own score | ✓ | ✓ | ✓ | ✓ |
| View team scores | — | ✓ (direct reports) | ✓ (all) | ✓ (all) |
| Run scoring engine | — | — | ✓ | — |
| Apply KPI adjustments | — | ✓ (direct reports) | ✓ | — |
| Apply composite adjustments | — | ✓ | ✓ | — |
| Manage calibration | — | — | ✓ | — |
| Finalise scores | — | — | ✓ | — |
| Employee dashboard | ✓ | ✓ | ✓ | ✓ |
| Manager/team dashboard | — | ✓ | ✓ | ✓ |
| Org dashboard | — | — | ✓ | ✓ |
| KPI progress report | — | ✓ | ✓ | ✓ |
| Leaderboard | — | ✓ (team only) | ✓ | ✓ |
| CSV export | — | — | ✓ | ✓ |
