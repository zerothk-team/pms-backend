# 05 — Actuals

> Actuals are the measured values — what was *actually achieved* for a KPI during a measurement period. They are the raw input for performance scoring and the evidence that a target was (or was not) met.

---

## 1. What Is an Actual?

A **KPI Actual** answers the question: *"For the [month/quarter/period], what was the real measured value for [person]'s [KPI]?"*

Each actual record stores:
- Which **target** it measures (links to KPITarget)
- Which **measurement period** it covers (`period_date` = period start date)
- The **measured value** (`actual_value`)
- The **source** (manual, auto_formula, import)
- The **approval status** (pending, approved, rejected, superseded)
- Optional **evidence attachments** (files/URLs)

---

## 2. Approval Status Lifecycle

```
             ┌──────────────────────┐
             │   PENDING_APPROVAL  │  ← Default for team/org targets
             └──────────┬──────────┘
                        │ manager approves
                        ▼
                  ┌──────────┐
                  │ APPROVED │  ← Confirmed; used for scoring
                  └──────────┘

             OR

                        │ manager rejects (reason required)
                        ▼
                  ┌──────────┐
                  │ REJECTED │  ← Employee must resubmit
                  └──────────┘

     ─────────────── superseding ───────────────

     APPROVED or REJECTED → SUPERSEDED when a new submission
     is made for the same period, preserving audit trail
```

### Auto-Approval for Individual Targets

When `assignee_type = individual`, actuals are **immediately set to APPROVED** on submission — no manager review step is required. This reflects the assumption that individual employees are directly accountable for their own data.

### Team/Org Targets

When `assignee_type = team` or `organisation`, actuals go to `PENDING_APPROVAL`. A manager (or hr_admin) must explicitly approve or reject.

---

## 3. Submission Rules

### Pre-Requisites
1. The **target must be LOCKED** (the cycle must be ACTIVE).  
   → Submitting actuals to an unlocked target returns HTTP 400.
2. The `period_date` must be within the cycle's date range.
3. The `period_date` must align to the KPI's measurement frequency (e.g. must be the 1st of the month for a monthly KPI).
4. The caller must have permission: hr_admin/executive/manager always; employee only for their own individual target.

### Period Alignment

The service calls `get_period_start_dates(cycle.start_date, cycle.end_date, kpi.frequency)` to generate expected dates. If the submitted `period_date` is not in this list, the submission is rejected:

```
HTTP 400
{
  "detail": "period_date 2025-01-15 does not align to the expected monthly measurement periods. Expected dates: [2025-01-01, 2025-02-01, ...]"
}
```

---

## 4. Audit Trail — Superseding

The system preserves **complete history**. When a new actual is submitted for a period that already has an active record:

| Existing status | Action |
|----------------|--------|
| `pending_approval` | Updated **in-place** (no new record created) |
| `approved` | Existing record → `superseded`; new record created |
| `rejected` | Existing record → `superseded`; new record created |

This means you can always query all records for a target/period (including `include_superseded=true`) to see the full submission history.

---

## 5. Bulk Submit

Submit multiple period actuals in a single transaction:

```json
POST /api/v1/actuals/bulk
{
  "entries": [
    { "target_id": "uuid", "period_date": "2025-01-01", "actual_value": 80.0 },
    { "target_id": "uuid", "period_date": "2025-02-01", "actual_value": 92.5 },
    { "target_id": "uuid", "period_date": "2025-03-01", "actual_value": 75.0 }
  ]
}
```

The same business rules apply to each entry. If any entry fails, the entire transaction rolls back (atomic).

The service limits bulk submissions to **50 entries per request**.

---

## 6. Approval Workflow (Team/Org Targets)

### Approve
```json
POST /api/v1/actuals/{id}/review
{ "action": "approve" }
```

### Reject
```json
POST /api/v1/actuals/{id}/review
{ "action": "reject", "rejection_reason": "Wrong metric — should be net revenue, not gross." }
```

`rejection_reason` is **required** when action is `reject`. This ensures employees receive clear feedback.

### Edit Before Approval
An employee may edit a `PENDING_APPROVAL` actual (only theirs, only if not yet reviewed):

```json
PATCH /api/v1/actuals/{id}
{ "actual_value": 95.0, "notes": "Corrected figure from updated report." }
```

---

## 7. Formula Auto-Compute

For KPIs with `kpi_type = formula`, the system can **automatically compute** the actual value by evaluating the formula against the dependency KPIs' actuals for the same period.

- Source will be `auto_formula`
- `submitted_by_id` will be `null` (no human submitter)
- Initial status for individual formula targets = `approved` (auto-approved)

This is controlled by the same engine described in the KPI module's Formula Engine documentation.

---

## 8. Time Series

`GET /api/v1/actuals/time-series/{target_id}` returns a complete timeline from cycle start to today, including missing (null) periods:

```json
{
  "target_id": "...",
  "kpi_id": "...",
  "kpi_name": "Monthly Revenue",
  "kpi_unit": "currency",
  "data_points": [
    {
      "period_date": "2025-01-01",
      "period_label": "Jan 2025",
      "actual_value": 85000.00,
      "target_value": 8333.33,
      "milestone_value": null,
      "achievement_percentage": "1019.99"
    },
    {
      "period_date": "2025-02-01",
      "period_label": "Feb 2025",
      "actual_value": null,
      "target_value": 8333.33,
      "milestone_value": null,
      "achievement_percentage": null
    }
  ],
  "overall_achievement": "425.00",
  "periods_with_data": 1,
  "total_periods": 12
}
```

### Per-Period Target Value

The time series `target_value` shown per point depends on the KPI's unit:
- **COUNT, CURRENCY, DURATION_HOURS**: `target_value / total_periods` (equal distribution over the cycle)
- **PERCENTAGE, RATIO, SCORE, other**: `target_value` directly (point-in-time measurement)

### Overall Achievement
Overall achievement is `(total_actual_to_date / target.target_value) × 100`, computed the same way as the progress endpoint.

---

## 9. Evidence Attachments

After submitting an actual, attachments can be added or removed:

### Add Evidence
```json
POST /api/v1/actuals/{id}/evidence
{
  "file_name": "Q1 Sales Report.pdf",
  "file_url": "https://storage.example.com/reports/q1-2025.pdf"
}
```

### Delete Evidence
```
DELETE /api/v1/actuals/{id}/evidence/{evidence_id}
```

Evidence is cascade-deleted when the parent actual is deleted.

---

## 10. Pending Reviews (Manager Dashboard)

`GET /api/v1/actuals/pending-review` returns all `PENDING_APPROVAL` actuals within the manager's scope:

- **hr_admin / executive**: all pending actuals in the organisation
- **manager**: only pending actuals from their direct reports

This endpoint supports the manager approval dashboard workflow.

---

## 11. Listing and Filtering

`GET /api/v1/actuals/` supports the following query parameters:

| Parameter | Type | Description |
|-----------|------|-------------|
| `target_id` | UUID | Filter by specific target |
| `kpi_id` | UUID | Filter by KPI |
| `status` | string | Filter by entry status |
| `period_start` | date | Actuals on or after this date |
| `period_end` | date | Actuals on or before this date |
| `page` | int | Page number (default: 1) |
| `size` | int | Page size (default: 20, max: 100) |

---

## 12. Roles and Permissions

| Operation | hr_admin | manager | executive | employee |
|-----------|----------|---------|-----------|---------|
| Submit actual | ✅ | ✅ | ✅ | ✅ (own) |
| Bulk submit | ✅ | ✅ | ✅ | ✅ (own) |
| Edit pending actual | ✅ | ✅ | ✅ | ✅ (own) |
| Approve/reject actual | ✅ | ✅ | ✅ | ❌ |
| Add/delete evidence | ✅ | ✅ | ✅ | ✅ (own) |
| View pending approvals | ✅ (all) | ✅ (direct reports) | ✅ (all) | ❌ |
| Time series | ✅ | ✅ | ✅ | ✅ (own) |
| List actuals | ✅ | ✅ | ✅ | ✅ (own) |

---

## 13. Error Scenarios

| Scenario | HTTP Code | Error |
|----------|-----------|-------|
| Target not LOCKED (cycle not ACTIVE) | 400 | BadRequestException |
| `period_date` outside cycle range | 400 | BadRequestException |
| `period_date` misaligned to KPI frequency | 400 | BadRequestException |
| Employee submitting for another employee's target | 403 | ForbiddenException |
| Non-manager attempting to review (approve/reject) | 403 | ForbiddenException |
| Reviewing a non-PENDING actual | 400 | BadRequestException |
| Rejecting without `rejection_reason` | 422 | Pydantic validation error |
| Editing a non-PENDING actual | 400 | BadRequestException |
| Editing another user's actual (employee) | 403 | ForbiddenException |
| Actual not found or wrong org | 404 | NotFoundException |
