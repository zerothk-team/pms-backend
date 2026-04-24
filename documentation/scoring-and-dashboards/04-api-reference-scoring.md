# 04 — API Reference: Scoring

← [Back to Index](index.md)

> **Base URL**: `http://localhost:8000/api/v1/scoring`  
> All endpoints require a valid JWT in `Authorization: Bearer <token>`.

---

## Endpoint Summary

| # | Method | Path | Roles | Description |
|---|--------|------|-------|-------------|
| 1 | GET | `/config` | All authenticated | Get score config for a cycle |
| 2 | POST | `/config` | `hr_admin` | Create score config |
| 3 | PUT | `/config/{config_id}` | `hr_admin` | Update score config |
| 4 | POST | `/compute/{cycle_id}` | `hr_admin` | Run scoring engine for a cycle |
| 5 | POST | `/recompute/{user_id}/{cycle_id}` | `hr_admin`, `manager` | Recompute scores for one user |
| 6 | GET | `/users/{user_id}/{cycle_id}` | See notes | Get full score breakdown |
| 7 | GET | `/team/{cycle_id}` | `manager`, `hr_admin`, `executive` | Team composite scores |
| 8 | GET | `/org/{cycle_id}` | `hr_admin`, `executive` | Org score distribution |
| 9 | PATCH | `/kpi-score/{score_id}/adjust` | `manager`, `hr_admin` | Adjust a KPI score |
| 10 | PATCH | `/composite/{composite_id}/adjust` | `hr_admin`, `manager` | Adjust composite score directly |
| 11 | POST | `/finalise/{cycle_id}` | `hr_admin` | Lock all scores for a cycle |
| 12 | POST | `/calibration` | `hr_admin` | Create calibration session |
| 13 | GET | `/calibration` | `hr_admin` | List calibration sessions |
| 14 | GET | `/calibration/{session_id}` | `hr_admin` | Get session with scores |
| 15 | PATCH | `/calibration/{session_id}/scores/{composite_id}` | `hr_admin` | Adjust score in session |
| 16 | POST | `/calibration/{session_id}/complete` | `hr_admin` | Mark session as completed |

---

## 1. GET `/config`

Get the scoring threshold configuration for a review cycle.

**Query parameters**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `cycle_id` | UUID | Yes | The review cycle to retrieve config for |

**Response 200**
```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "organisation_id": "...",
  "review_cycle_id": "...",
  "exceptional_min": "120.00",
  "exceeds_min": "100.00",
  "meets_min": "80.00",
  "partially_meets_min": "60.00",
  "does_not_meet_min": "0.00",
  "allow_manager_adjustment": true,
  "max_adjustment_points": "10.00",
  "requires_calibration": false,
  "created_at": "2025-01-15T08:00:00Z",
  "updated_at": "2025-01-15T08:00:00Z"
}
```

**Errors**:
- `404 Not Found` — no config exists for this cycle (use `POST /config` to create one)

---

## 2. POST `/config`

Create a scoring configuration for a review cycle.

**Request body**
```json
{
  "review_cycle_id": "...",
  "exceptional_min": "125.00",
  "exceeds_min": "105.00",
  "meets_min": "85.00",
  "partially_meets_min": "65.00",
  "allow_manager_adjustment": true,
  "max_adjustment_points": "15.00",
  "requires_calibration": true
}
```

**Validation rules**:
- Thresholds must be strictly descending: `exceptional_min > exceeds_min > meets_min > partially_meets_min ≥ 0`
- Only one config per `(organisation, review_cycle)` — duplicates return `409 Conflict`

**Response 201** — same shape as GET `/config`

**Errors**:
- `400 Bad Request` — thresholds not in descending order
- `409 Conflict` — config already exists for this cycle

---

## 3. PUT `/config/{config_id}`

Update thresholds on an existing config. All fields are optional.

**Request body** (all optional)
```json
{
  "exceptional_min": "130.00",
  "max_adjustment_points": "20.00",
  "requires_calibration": true
}
```

**Response 200** — full `ScoreConfigRead`

---

## 4. POST `/compute/{cycle_id}`

Run the scoring engine for an entire review cycle. Re-running is safe.

**Query parameters** (optional)

| Parameter | Type | Description |
|-----------|------|-------------|
| `user_ids` | list[UUID] | If provided, compute only for these users |

**Response 200**
```json
{
  "cycle_id": "...",
  "users_scored": 42,
  "composite_scores": [
    {
      "id": "...",
      "user_id": "...",
      "review_cycle_id": "...",
      "organisation_id": "...",
      "weighted_average": "91.5000",
      "final_weighted_average": "91.5000",
      "rating": "meets_expectations",
      "kpi_count": 3,
      "kpis_with_actuals": 3,
      "status": "computed",
      "manager_comment": null,
      "calibration_note": null,
      "computed_at": "2025-06-01T10:00:00Z",
      "updated_at": "2025-06-01T10:00:00Z"
    }
  ]
}
```

**Errors**:
- `404 Not Found` — cycle not found or doesn't belong to the organisation

---

## 5. POST `/recompute/{user_id}/{cycle_id}`

Recompute scores for a single employee. Preserves existing manual adjustments for scores that are already `ADJUSTED`, `CALIBRATED`, or `FINAL`.

**Response 200** — `CompositeScoreRead`

---

## 6. GET `/users/{user_id}/{cycle_id}`

Get the full score breakdown for one employee, including each KPI score and adjustment history.

**Access rules**:
- `employee` — only their own `user_id`
- `manager` — their direct reports
- `hr_admin`, `executive` — any user

**Response 200**
```json
{
  "id": "...",
  "user_id": "...",
  "review_cycle_id": "...",
  "organisation_id": "...",
  "weighted_average": "91.5000",
  "final_weighted_average": "91.5000",
  "rating": "meets_expectations",
  "kpi_count": 2,
  "kpis_with_actuals": 2,
  "status": "computed",
  "manager_comment": null,
  "calibration_note": null,
  "computed_at": "2025-06-01T10:00:00Z",
  "updated_at": "2025-06-01T10:00:00Z",
  "kpi_scores": [
    {
      "id": "...",
      "user_id": "...",
      "kpi_id": "...",
      "target_id": "...",
      "review_cycle_id": "...",
      "organisation_id": "...",
      "achievement_pct": "115.0000",
      "weighted_score": "69.0000",
      "final_score": "69.0000",
      "rating": "exceeds_expectations",
      "status": "computed",
      "adjustment_reason": null,
      "computed_at": "2025-06-01T10:00:00Z",
      "updated_at": "2025-06-01T10:00:00Z",
      "kpi_name": "Revenue",
      "kpi_code": "REVENUE",
      "target_value": "100000.00",
      "weight": "60.00",
      "adjustments": []
    }
  ],
  "adjustment_history": []
}
```

**Errors**:
- `403 Forbidden` — employee trying to view another user
- `404 Not Found` — scoring has not run for this user/cycle

---

## 7. GET `/team/{cycle_id}`

Get composite scores for the requesting manager's direct reports.

- `hr_admin` — sees all users in the organisation
- `manager` — sees only direct reports
- `executive` — sees all (read-only)

**Response 200** — `list[CompositeScoreRead]`

---

## 8. GET `/org/{cycle_id}`

Statistical distribution of all composite scores for the organisation.

**Query parameters** (optional)

| Parameter | Type | Description |
|-----------|------|-------------|
| `department` | string | Filter to a specific department |

**Response 200**
```json
{
  "mean": "88.40",
  "median": "91.00",
  "std_dev": "12.35",
  "percentiles": {
    "p25": "79.00",
    "p50": "91.00",
    "p75": "98.50",
    "p90": "107.00"
  },
  "rating_counts": {
    "exceptional": 3,
    "exceeds_expectations": 8,
    "meets_expectations": 22,
    "partially_meets": 6,
    "does_not_meet": 2,
    "not_rated": 1
  },
  "rating_percentages": {
    "exceptional": "7.14",
    "exceeds_expectations": "19.05",
    "meets_expectations": "52.38",
    "partially_meets": "14.29",
    "does_not_meet": "4.76",
    "not_rated": "2.38"
  }
}
```

---

## 9. PATCH `/kpi-score/{score_id}/adjust`

Apply a qualitative adjustment to a single KPI score. The composite is automatically recomputed.

**Request body**
```json
{
  "adjusted_score": "75.00",
  "reason": "Employee exceeded target in Q1 but faced system outage in Q4 affecting Q4 metrics."
}
```

**Validation**: `abs(adjusted_score - weighted_score) ≤ max_adjustment_points`

**Response 200** — updated `CompositeScoreRead`

**Errors**:
- `400 Bad Request` — adjustment exceeds cap
- `403 Forbidden` — score is `FINAL` (locked)
- `404 Not Found` — score not found

---

## 10. PATCH `/composite/{composite_id}/adjust`

Directly adjust the overall composite score.

**Request body**
```json
{
  "adjusted_score": "92.00",
  "reason": "Cross-department collaboration not captured in individual KPI metrics."
}
```

**Response 200** — `CompositeScoreRead`

---

## 11. POST `/finalise/{cycle_id}`

Lock all scores for the cycle. **This action is irreversible.**

**Pre-conditions**:
- Cycle must be `closed`
- If `ScoreConfig.requires_calibration = true`, at least one `CalibrationSession` with `status = completed` must exist

**Response 200**
```json
{
  "message": "Successfully finalised 42 composite scores.",
  "scores_finalised": 42,
  "cycle_id": "..."
}
```

**Errors**:
- `400 Bad Request` — cycle not closed
- `400 Bad Request` — calibration required but not completed

---

## 12. POST `/calibration`

Create a calibration session for a group of employees.

**Request body**
```json
{
  "review_cycle_id": "...",
  "name": "Q2 Sales Team Calibration",
  "scope_user_ids": ["user-uuid-1", "user-uuid-2", "user-uuid-3"],
  "notes": "Focus on high-performers and those near rating boundaries."
}
```

**Validation**: All users in `scope_user_ids` must have computed composite scores.

**Response 201** — `CalibrationSessionRead`

---

## 13. GET `/calibration`

List calibration sessions for a cycle.

**Query parameters**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `cycle_id` | UUID | Yes | The review cycle |

**Response 200** — `list[CalibrationSessionRead]`

---

## 14. GET `/calibration/{session_id}`

Get a calibration session including all in-scope composite scores and distribution statistics.

**Response 200**
```json
{
  "id": "...",
  "review_cycle_id": "...",
  "organisation_id": "...",
  "name": "Q2 Sales Team Calibration",
  "status": "in_progress",
  "facilitator_id": "...",
  "scope_user_ids": ["..."],
  "notes": "Focus on boundaries.",
  "completed_at": null,
  "created_at": "2025-06-01T10:00:00Z",
  "composite_scores": [ /* CompositeScoreRead items, sorted by score desc */ ],
  "distribution": { /* same shape as GET /org/{cycle_id} */ }
}
```

---

## 15. PATCH `/calibration/{session_id}/scores/{composite_id}`

Adjust a composite score during an open calibration session. No adjustment cap applies.

**Request body**
```json
{
  "new_score": "87.00",
  "note": "Team agreed to adjust down based on peer feedback shared in meeting."
}
```

**Response 200** — updated `CompositeScoreRead`

**Errors**:
- `400 Bad Request` — session is `completed` (closed)

---

## 16. POST `/calibration/{session_id}/complete`

Mark a calibration session as completed.

**Response 200** — `CalibrationSessionRead` with `status = "completed"`
