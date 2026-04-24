# 07 — End-to-End Workflows

> This document traces four complete business workflows from first API call through all intermediate steps to the final outcome, with real JSON request/response pairs.

---

## Workflow 1: Annual Review Cycle Setup

**Scenario**: HR Admin sets up the FY 2025 annual review cycle, assigns targets to a team, and activates the cycle.

**Actors**: HR Admin (`hr_admin`), Manager, Employee

---

### Step 1 — HR Admin creates the cycle

```
POST /api/v1/review-cycles/
Authorization: Bearer <hr_admin_token>
```

**Request**
```json
{
  "name": "FY 2025 Annual Review",
  "cycle_type": "annual",
  "start_date": "2025-01-01",
  "end_date": "2025-12-31",
  "target_setting_deadline": "2025-01-31",
  "actual_entry_deadline": "2025-12-15",
  "scoring_start_date": "2026-01-01"
}
```

**Response** `201 Created`
```json
{
  "id": "cycle-uuid-001",
  "name": "FY 2025 Annual Review",
  "cycle_type": "annual",
  "status": "draft",
  "start_date": "2025-01-01",
  "end_date": "2025-12-31",
  ...
}
```

---

### Step 2 — Manager creates individual targets for their team

```
POST /api/v1/targets/
Authorization: Bearer <manager_token>
```

**Request (Employee A — Sales Revenue KPI)**
```json
{
  "kpi_id": "kpi-uuid-revenue",
  "review_cycle_id": "cycle-uuid-001",
  "assignee_type": "individual",
  "assignee_user_id": "user-uuid-employee-a",
  "target_value": "500000.00",
  "stretch_target_value": "600000.00",
  "minimum_value": "400000.00",
  "weight": "60.00",
  "milestones": [
    { "milestone_date": "2025-03-31", "expected_value": "120000.00", "label": "Q1" },
    { "milestone_date": "2025-06-30", "expected_value": "250000.00", "label": "Q2" }
  ]
}
```

**Response** `201 Created` with `status: "draft"`

Repeat for each team member and each KPI target.

---

### Step 3 — Manager sends targets for acknowledgment

```
PATCH /api/v1/targets/{target_id}/status
Authorization: Bearer <manager_token>
```

**Request**
```json
{ "status": "pending_acknowledgement" }
```

**Response** `200 OK` with `status: "pending_acknowledgement"`

---

### Step 4 — Employee acknowledges their target

```
PATCH /api/v1/targets/{target_id}/acknowledge
Authorization: Bearer <employee_a_token>
```

**Response** `200 OK` with `status: "acknowledged"`, `acknowledged_at: "2025-01-20T11:00:00Z"`

---

### Step 5 — HR Admin activates the cycle

```
PATCH /api/v1/review-cycles/cycle-uuid-001/status
Authorization: Bearer <hr_admin_token>
```

**Request**
```json
{ "status": "active" }
```

**Response** `200 OK` with `status: "active"`

**Side-effect**: All `acknowledged` and `draft` targets in this cycle are now automatically set to `locked`. No further target modifications are possible.

---

## Workflow 2: Monthly Actual Submission (Individual)

**Scenario**: Employee A submits their January revenue figure. Since it's an individual target, it is immediately auto-approved.

---

### Step 1 — Employee submits January actual

```
POST /api/v1/actuals/
Authorization: Bearer <employee_a_token>
```

**Request**
```json
{
  "target_id": "target-uuid-employee-a-revenue",
  "period_date": "2025-01-01",
  "actual_value": "112000.00",
  "notes": "January figures from CRM. Includes two new enterprise accounts."
}
```

**Response** `201 Created`
```json
{
  "id": "actual-uuid-001",
  "target_id": "target-uuid-employee-a-revenue",
  "kpi_id": "kpi-uuid-revenue",
  "period_date": "2025-01-01",
  "period_label": "Jan 2025",
  "actual_value": "112000.0000",
  "entry_source": "manual",
  "status": "approved",
  ...
}
```

Note: `status: "approved"` because `assignee_type = individual`.

---

### Step 2 — Employee attaches supporting evidence

```
POST /api/v1/actuals/actual-uuid-001/evidence
Authorization: Bearer <employee_a_token>
```

**Request**
```json
{
  "file_name": "Jan 2025 CRM Export.csv",
  "file_url": "https://storage.company.com/docs/jan-2025-crm.csv",
  "file_type": "text/csv"
}
```

**Response** `201 Created`
```json
{
  "id": "evidence-uuid-001",
  "actual_id": "actual-uuid-001",
  "file_name": "Jan 2025 CRM Export.csv",
  "file_url": "https://storage.company.com/docs/jan-2025-crm.csv",
  ...
}
```

---

### Step 3 — Check progress

```
GET /api/v1/targets/target-uuid-employee-a-revenue
Authorization: Bearer <employee_a_token>
```

**Response** highlights:
```json
{
  "status": "locked",
  "target_value": "500000.0000",
  "latest_actual_value": "112000.0000",
  "total_actual_to_date": "112000.0000",
  "achievement_percentage": "22.40",
  "is_at_risk": false,
  "trend": null
}
```

Achievement = 112,000 / 500,000 × 100 = 22.4% (only 1 month in).

---

## Workflow 3: Team Target with Manager Approval

**Scenario**: A team-level target requires manager review before actuals are accepted.

---

### Step 1 — HR Admin creates a team target

```
POST /api/v1/targets/
Authorization: Bearer <hr_admin_token>
```

**Request**
```json
{
  "kpi_id": "kpi-uuid-nps",
  "review_cycle_id": "cycle-uuid-001",
  "assignee_type": "team",
  "target_value": "75.00",
  "weight": "100.00",
  "notes": "Team NPS target for 2025"
}
```

**Response** `201 Created` with `status: "draft"`  
After cycle activation → `status: "locked"`

---

### Step 2 — Manager submits team actual

```
POST /api/v1/actuals/
Authorization: Bearer <manager_token>
```

**Request**
```json
{
  "target_id": "target-uuid-team-nps",
  "period_date": "2025-01-01",
  "actual_value": "72.00",
  "notes": "Q4 NPS survey completed. Response rate 68%."
}
```

**Response** `201 Created`
```json
{
  "status": "pending_approval",
  ...
}
```

Note: `status: "pending_approval"` because `assignee_type = team`.

---

### Step 3 — HR Admin reviews from the pending queue

```
GET /api/v1/actuals/pending-review
Authorization: Bearer <hr_admin_token>
```

**Response** shows the pending actual.

---

### Step 4 — HR Admin approves the actual

```
POST /api/v1/actuals/actual-uuid-nps-jan/review
Authorization: Bearer <hr_admin_token>
```

**Request**
```json
{ "action": "approve" }
```

**Response** `200 OK` with `status: "approved"`, `reviewed_at: "2025-02-01T09:00:00Z"`

---

### Step 5 — HR Admin rejects and requests correction (alternative path)

```
POST /api/v1/actuals/actual-uuid-nps-jan/review
Authorization: Bearer <hr_admin_token>
```

**Request**
```json
{
  "action": "reject",
  "rejection_reason": "Survey data must come from the official NPS tool, not manual entry."
}
```

**Response** `200 OK` with `status: "rejected"`, `rejection_reason` set.

**Resubmission**: Manager resubmits:
```
POST /api/v1/actuals/
```
Old rejected record → `SUPERSEDED`. New record created with `PENDING_APPROVAL`.

---

## Workflow 4: Target Cascade

**Scenario**: HR Admin creates an org-level revenue target, then cascades it proportionally to two sales managers who each get a portion.

---

### Step 1 — Create org-level target

```
POST /api/v1/targets/
Authorization: Bearer <hr_admin_token>
```

**Request**
```json
{
  "kpi_id": "kpi-uuid-revenue",
  "review_cycle_id": "cycle-uuid-001",
  "assignee_type": "organisation",
  "target_value": "10000000.00",
  "weight": "100.00",
  "notes": "Total company revenue target FY 2025"
}
```

**Response** `201 Created` with `id: "target-uuid-org-revenue"`, `status: "draft"`

---

### Step 2 — Cascade proportionally to two sales managers

```
POST /api/v1/targets/cascade
Authorization: Bearer <hr_admin_token>
```

**Request**
```json
{
  "parent_target_id": "target-uuid-org-revenue",
  "strategy": "proportional",
  "distribution": [
    { "user_id": "user-uuid-mgr-north", "weight": 60.0 },
    { "user_id": "user-uuid-mgr-south", "weight": 40.0 }
  ],
  "total_check": true
}
```

**Computed values**:
- North manager: 60 / 100 × 10,000,000 = **6,000,000**
- South manager: 40 / 100 × 10,000,000 = **4,000,000**
- Total = 10,000,000 ✅ (exactly at parent, passes total_check)

**Response** `201 Created` → list of 2 `KPITargetRead` with `cascade_parent_id = "target-uuid-org-revenue"`

---

### Step 3 — Managers cascade down to their own employees

```
POST /api/v1/targets/cascade
Authorization: Bearer <mgr_north_token>
```

**Request**
```json
{
  "parent_target_id": "target-uuid-mgr-north",
  "strategy": "equal",
  "distribution": [
    { "user_id": "user-uuid-rep-1", "weight": 100.0 },
    { "user_id": "user-uuid-rep-2", "weight": 100.0 },
    { "user_id": "user-uuid-rep-3", "weight": 100.0 }
  ],
  "total_check": false
}
```

**Computed values**: 6,000,000 / 3 = **2,000,000** each  
Total = 6,000,000 ✅

**Response**: 3 new individual targets, each with `target_value = "2000000.0000"` and `cascade_parent_id = "target-uuid-mgr-north"`

---

### Step 4 — View cascade tree

```
GET /api/v1/targets/target-uuid-org-revenue/cascade-tree
Authorization: Bearer <hr_admin_token>
```

**Response** shows root → North/South managers → North's 3 reps as a nested tree.

---

## Workflow 5: Anomaly Correction (Superseding an Actual)

**Scenario**: Employee B submitted the wrong figure for March and needs to correct it.

---

### Step 1 — March actual already approved

Previous submission: `period_date: "2025-03-01"`, `actual_value: "45000.00"`, `status: "approved"`

---

### Step 2 — Employee resubmits with corrected value

```
POST /api/v1/actuals/
Authorization: Bearer <employee_b_token>
```

**Request**
```json
{
  "target_id": "target-uuid-employee-b-revenue",
  "period_date": "2025-03-01",
  "actual_value": "52000.00",
  "notes": "Corrected — original figure omitted two late-booking deals."
}
```

**What happens internally**:
1. Service finds existing APPROVED record for `(target_id, period_date = 2025-03-01)`
2. Sets its status to `superseded`
3. Creates a new record with `status: "approved"` (individual target)

**Response** `201 Created`
```json
{
  "id": "actual-uuid-new",
  "actual_value": "52000.0000",
  "status": "approved",
  ...
}
```

---

### Step 3 — Query full history for audit

```
GET /api/v1/actuals/for-target/target-uuid-employee-b-revenue?include_superseded=true
Authorization: Bearer <manager_token>
```

**Response** shows both the superseded record (original 45,000) and the current approved record (52,000).
