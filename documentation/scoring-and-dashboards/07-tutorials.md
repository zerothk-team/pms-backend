# 07 — Step-by-Step Tutorials

← [Back to Index](index.md)

> **Prerequisites**: Review cycle is `active`, KPI targets are `locked`, actuals have been submitted and `approved`.  
> **Base URL**: `http://localhost:8000`

---

## Tutorial 1: Run Scoring for a Review Cycle

**Goal**: Compute `PerformanceScore` and `CompositeScore` rows for all employees in a cycle.

### Step 1 — Log in as HR Admin
```bash
curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "hr@example.com", "password": "secret123"}' \
  | jq '.access_token'
```

```json
"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

Export for convenience:
```bash
export TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
export CYCLE_ID="c3d41234-..."
```

### Step 2 — Run the scoring engine
```bash
curl -s -X POST "http://localhost:8000/api/v1/scoring/compute/$CYCLE_ID" \
  -H "Authorization: Bearer $TOKEN"
```

```json
{
  "cycle_id": "c3d41234-...",
  "users_scored": 42,
  "composite_scores": [
    {
      "id": "a1b2c3d4-...",
      "user_id": "u1234...",
      "weighted_average": "91.5000",
      "final_weighted_average": "91.5000",
      "rating": "meets_expectations",
      "kpi_count": 3,
      "kpis_with_actuals": 3,
      "status": "computed",
      ...
    }
  ]
}
```

### Step 3 — View an individual employee's scores
```bash
export USER_ID="u1234..."
curl -s "http://localhost:8000/api/v1/scoring/users/$USER_ID/$CYCLE_ID" \
  -H "Authorization: Bearer $TOKEN" | jq '.'
```

---

## Tutorial 2: Customise Scoring Thresholds

**Goal**: Create a `ScoreConfig` with a stricter "Exceptional" bar (130 % instead of 120 %).

```bash
curl -s -X POST "http://localhost:8000/api/v1/scoring/config" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "review_cycle_id": "'$CYCLE_ID'",
    "exceptional_min": "130.00",
    "exceeds_min": "110.00",
    "meets_min": "90.00",
    "partially_meets_min": "70.00",
    "allow_manager_adjustment": true,
    "max_adjustment_points": "15.00",
    "requires_calibration": true
  }'
```

```json
{
  "id": "sc-uuid-...",
  "review_cycle_id": "c3d41234-...",
  "exceptional_min": "130.00",
  "exceeds_min": "110.00",
  "meets_min": "90.00",
  "partially_meets_min": "70.00",
  "does_not_meet_min": "0.00",
  "allow_manager_adjustment": true,
  "max_adjustment_points": "15.00",
  "requires_calibration": true,
  "created_at": "2025-06-01T10:00:00Z",
  "updated_at": "2025-06-01T10:00:00Z"
}
```

> **Note**: After creating a config, re-run `POST /scoring/compute/{cycle_id}` to apply the new thresholds.

---

## Tutorial 3: Manager Applies a KPI Adjustment

**Goal**: A manager adds +5 points to an employee's "Revenue" KPI score because of a system outage in Q4 that affected data capture.

### Step 1 — Get the employee's score detail to find the KPI score ID
```bash
curl -s "http://localhost:8000/api/v1/scoring/users/$USER_ID/$CYCLE_ID" \
  -H "Authorization: Bearer $MANAGER_TOKEN" | jq '.kpi_scores[] | {id, kpi_code, weighted_score}'
```

```json
[
  {"id": "kpi-score-abc", "kpi_code": "REVENUE", "weighted_score": "63.0000"},
  {"id": "kpi-score-def", "kpi_code": "CALLS", "weighted_score": "28.5000"}
]
```

### Step 2 — Apply the adjustment
```bash
curl -s -X PATCH "http://localhost:8000/api/v1/scoring/kpi-score/kpi-score-abc/adjust" \
  -H "Authorization: Bearer $MANAGER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "adjusted_score": "68.00",
    "reason": "System outage in Q4 prevented accurate data capture for 6 weeks. Employee performance was tracking at 115% before the outage."
  }'
```

```json
{
  "id": "composite-uuid-...",
  "user_id": "u1234...",
  "weighted_average": "91.5000",
  "final_weighted_average": "94.17",
  "rating": "meets_expectations",
  "status": "adjusted",
  ...
}
```

The composite is **automatically recomputed** from the new `final_score`.

---

## Tutorial 4: Run a Calibration Session

**Goal**: HR facilitates a calibration session for the Sales team to align scores around the rating boundary.

### Step 1 — Identify employees near the Meets/Does Not Meet boundary

Use `GET /scoring/org/{cycle_id}` to find employees with scores around 80 %.

### Step 2 — Create the calibration session
```bash
curl -s -X POST "http://localhost:8000/api/v1/scoring/calibration" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "review_cycle_id": "'$CYCLE_ID'",
    "name": "Sales Team Q2 Calibration",
    "scope_user_ids": [
      "user-uuid-1",
      "user-uuid-2",
      "user-uuid-3"
    ],
    "notes": "Focus: employees within 5 points of the Meets/Does Not Meet boundary."
  }'
```

```json
{
  "id": "session-uuid-...",
  "name": "Sales Team Q2 Calibration",
  "status": "open",
  "facilitator_id": "hr-admin-uuid",
  "scope_user_ids": ["user-uuid-1", "user-uuid-2", "user-uuid-3"],
  "created_at": "2025-06-15T14:00:00Z",
  ...
}
```

### Step 3 — Adjust scores during the session
```bash
export SESSION_ID="session-uuid-..."
export COMPOSITE_ID="composite-of-user-1..."

curl -s -X PATCH \
  "http://localhost:8000/api/v1/scoring/calibration/$SESSION_ID/scores/$COMPOSITE_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "new_score": "82.00",
    "note": "Team consensus: employee showed consistent effort. System issues masked Q3 performance."
  }'
```

### Step 4 — Complete the session
```bash
curl -s -X POST \
  "http://localhost:8000/api/v1/scoring/calibration/$SESSION_ID/complete" \
  -H "Authorization: Bearer $TOKEN"
```

```json
{
  "id": "session-uuid-...",
  "status": "completed",
  "completed_at": "2025-06-15T16:30:00Z",
  ...
}
```

---

## Tutorial 5: Finalise Scores and Export CSV

**Goal**: Lock all scores for the cycle when it has closed, then download a CSV.

### Step 1 — Close the cycle (review_cycles endpoint)
```bash
curl -s -X PATCH "http://localhost:8000/api/v1/review-cycles/$CYCLE_ID/status" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status": "closed"}'
```

### Step 2 — Finalise scores
```bash
curl -s -X POST "http://localhost:8000/api/v1/scoring/finalise/$CYCLE_ID" \
  -H "Authorization: Bearer $TOKEN"
```

```json
{
  "message": "Successfully finalised 42 composite scores.",
  "scores_finalised": 42,
  "cycle_id": "c3d41234-..."
}
```

### Step 3 — Download the CSV
```bash
curl -s "http://localhost:8000/api/v1/dashboards/export/$CYCLE_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -o scores_q2_2025.csv
```

```csv
user_id,full_name,email,department,kpi_code,kpi_name,target_value,actual_value,achievement_pct,weight,weighted_score,final_score,rating,status,computed_at
u1234,Jane Smith,jane@example.com,Engineering,REVENUE,Revenue Target,100000.00,115000.00,115.0000,60.00,69.0000,69.0000,exceeds_expectations,final,2025-06-01T10:00:00
...
```
