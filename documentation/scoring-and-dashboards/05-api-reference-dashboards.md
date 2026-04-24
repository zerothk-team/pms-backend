# 05 — API Reference: Dashboards

← [Back to Index](index.md)

> **Base URL**: `http://localhost:8000/api/v1/dashboards`  
> All endpoints require a valid JWT in `Authorization: Bearer <token>`.

---

## Endpoint Summary

| # | Method | Path | Roles | Description |
|---|--------|------|-------|-------------|
| 1 | GET | `/me` | All authenticated | Personal performance dashboard |
| 2 | GET | `/team` | `manager`, `hr_admin`, `executive` | Team performance dashboard |
| 3 | GET | `/org` | `hr_admin`, `executive` | Org overview (active cycle) |
| 4 | GET | `/org/{cycle_id}` | `hr_admin`, `executive` | Org overview (specific cycle) |
| 5 | GET | `/kpi/{kpi_id}/progress` | `manager`, `hr_admin`, `executive` | KPI progress (active cycle) |
| 6 | GET | `/kpi/{kpi_id}/progress/{cycle_id}` | `manager`, `hr_admin`, `executive` | KPI progress (specific cycle) |
| 7 | GET | `/leaderboard/{cycle_id}` | `manager`, `hr_admin`, `executive` | Top performers leaderboard |
| 8 | GET | `/export/{cycle_id}` | `hr_admin`, `executive` | CSV export of all scores |

---

## 1. GET `/me` — Employee Personal Dashboard

Returns the full personal performance dashboard for the requesting user, using the currently **active** review cycle.

**Response 200**
```json
{
  "active_cycle": {
    "id": "...",
    "name": "Q2 2025 Annual Review",
    "cycle_type": "annual",
    "start_date": "2025-01-01",
    "end_date": "2025-12-31",
    "status": "active"
  },
  "user": {
    "id": "...",
    "full_name": "Jane Smith",
    "email": "jane@example.com",
    "department": "Engineering",
    "role": "employee"
  },
  "overall_score": "91.50",
  "overall_rating": "meets_expectations",
  "score_status": "computed",
  "kpis": [
    {
      "kpi_id": "...",
      "kpi_name": "Revenue Target",
      "kpi_code": "REVENUE",
      "target_value": "100000.00",
      "weight": "60.00",
      "latest_actual": "115000.00",
      "latest_actual_date": "2025-06-01",
      "achievement_pct": "115.00",
      "rating": "exceeds_expectations",
      "trend": "improving",
      "at_risk": false,
      "pending_approval": false
    }
  ],
  "summary": {
    "total_kpis": 3,
    "kpis_with_actuals": 2,
    "kpis_at_risk": 0,
    "pending_approvals": 1,
    "kpis_on_track": 2
  }
}
```

**Field notes**:
- `active_cycle` is `null` if no active cycle exists (new organisations).
- `overall_score` and `overall_rating` are `null` if scoring has not run yet.
- `trend` is `"improving"`, `"declining"`, or `"stable"` based on last two actuals.
- `at_risk` is `true` when `achievement_pct < 80 %`.

---

## 2. GET `/team` — Manager Team Dashboard

Returns a summary of all direct reports for the requesting manager.

**Response 200**
```json
{
  "active_cycle": { /* ReviewCycleSummary */ },
  "manager": { /* UserSummary */ },
  "team_size": 8,
  "team_summary": [
    {
      "user": {
        "id": "...",
        "full_name": "Bob Chen",
        "email": "bob@example.com",
        "department": "Sales",
        "role": "employee"
      },
      "kpi_count": 4,
      "actuals_submitted": 3,
      "pending_approvals": 1,
      "at_risk_kpis": 1,
      "overall_achievement": "87.50",
      "composite_score": "87.50",
      "rating": "meets_expectations"
    }
  ],
  "team_pending_approvals": 3,
  "team_at_risk_kpis": 2,
  "rating_distribution": {
    "exceptional": 1,
    "exceeds_expectations": 2,
    "meets_expectations": 4,
    "partially_meets": 1,
    "does_not_meet": 0,
    "not_rated": 0
  },
  "cycle_progress_pct": "41.67"
}
```

**Notes**:
- `composite_score` and `rating` are `null` if scoring has not been run.
- `hr_admin` and `executive` see the full organisation, not just direct reports.

---

## 3 & 4. GET `/org` and GET `/org/{cycle_id}` — Organisation Dashboard

`/org` uses the active cycle; `/org/{cycle_id}` uses the specified cycle.

**Response 200**
```json
{
  "active_cycle": {
    "id": "...",
    "name": "Q2 2025 Annual Review",
    "cycle_type": "annual",
    "start_date": "2025-01-01",
    "end_date": "2025-12-31",
    "status": "active"
  },
  "total_employees": 120,
  "employees_with_targets": 115,
  "employees_with_actuals": 98,
  "avg_achievement": "88.40",
  "department_breakdown": [
    {
      "department": "Engineering",
      "employee_count": 35,
      "avg_achievement": "92.10",
      "at_risk_count": 3
    }
  ],
  "top_kpis_at_risk": [
    {
      "kpi_id": "...",
      "kpi_name": "Customer Satisfaction Score",
      "kpi_code": "CSAT",
      "at_risk_count": 12,
      "avg_achievement": "71.50"
    }
  ],
  "score_distribution": {
    "mean": "88.40",
    "median": "91.00",
    "std_dev": "12.35",
    "percentiles": { "p25": "79.00", "p50": "91.00", "p75": "98.50", "p90": "107.00" },
    "rating_counts": { /* ... */ },
    "rating_percentages": { /* ... */ }
  },
  "period_progress": "41.67"
}
```

**Field notes**:
- `avg_achievement` is `null` if no actuals have been submitted.
- `active_cycle` is `null` when using `/org` and no active cycle exists (returns 200 with null, not 404).
- `period_progress` — percentage of the cycle's calendar time that has elapsed.
- `top_kpis_at_risk` — up to 10 KPIs with the highest at-risk employee count.
- `score_distribution` — empty dict `{}` if scoring has not run.

---

## 5 & 6. GET `/kpi/{kpi_id}/progress[/{cycle_id}]` — KPI Progress Report

Shows per-employee progress for a single KPI.

**Response 200**
```json
{
  "kpi_id": "...",
  "kpi_name": "Revenue Target",
  "kpi_code": "REVENUE",
  "cycle_id": "...",
  "cycle_name": "Q2 2025 Annual Review",
  "total_assigned": 15,
  "submitted_actuals": 12,
  "avg_achievement": "93.20",
  "user_progress": [
    {
      "user": {
        "id": "...",
        "full_name": "Jane Smith",
        "email": "jane@example.com",
        "department": "Sales",
        "role": "employee"
      },
      "target_value": "100000.00",
      "latest_actual": "115000.00",
      "achievement_percentage": "115.00",
      "rating": "exceeds_expectations",
      "data_points": [
        {
          "period_date": "2025-01-01",
          "actual_value": "90000.00",
          "target_value": "100000.00",
          "achievement_percentage": "90.00"
        },
        {
          "period_date": "2025-02-01",
          "actual_value": "105000.00",
          "target_value": "100000.00",
          "achievement_percentage": "105.00"
        }
      ]
    }
  ]
}
```

**Access**: Employees cannot use this endpoint (`403 Forbidden`). No active cycle → `404 Not Found` (active cycle variant).

---

## 7. GET `/leaderboard/{cycle_id}` — Performance Leaderboard

Returns top performers ranked by composite score.

**Query parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | integer (1–50) | 10 | Number of entries to return |

**Access rules**:
- `employee` → `403 Forbidden`
- `manager` → sees only direct reports
- `hr_admin`, `executive` → sees entire organisation

**Response 200**
```json
[
  {
    "rank": 1,
    "user": {
      "id": "...",
      "full_name": "Alice Wang",
      "email": "alice@example.com",
      "department": "Product",
      "role": "employee"
    },
    "composite_score": "118.50",
    "rating": "exceptional",
    "kpis_completed": 4,
    "kpi_count": 4
  },
  {
    "rank": 2,
    "user": { /* ... */ },
    "composite_score": "107.20",
    "rating": "exceeds_expectations",
    "kpis_completed": 3,
    "kpi_count": 4
  }
]
```

**Notes**:
- Only employees with at least one approved actual are included.
- `kpis_completed` = number of KPIs with at least one approved actual.

---

## 8. GET `/export/{cycle_id}` — CSV Export

Streams a CSV file with all scores for the cycle.

**Headers on response**:
```
Content-Type: text/csv; charset=utf-8
Content-Disposition: attachment; filename="scores_{cycle_id}.csv"
```

**CSV columns**:
```
user_id, full_name, email, department, kpi_code, kpi_name,
target_value, actual_value, achievement_pct, weight,
weighted_score, final_score, rating, status, computed_at
```

**Access**: `hr_admin`, `executive` only.

**Example rows**:
```csv
user_id,full_name,email,department,kpi_code,kpi_name,target_value,actual_value,achievement_pct,weight,weighted_score,final_score,rating,status,computed_at
abc123,Jane Smith,jane@example.com,Engineering,REVENUE,Revenue Target,100000.00,115000.00,115.0000,60.00,69.0000,69.0000,exceeds_expectations,computed,2025-06-01T10:00:00
```

**Notes**:
- Uses chunked streaming — works for large organisations without memory issues.
- One row per `PerformanceScore` (not per composite).
