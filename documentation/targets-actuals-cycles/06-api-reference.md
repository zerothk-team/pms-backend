# 06 — API Reference

> All endpoints are prefixed with `/api/v1`. All requests must include a valid `Authorization: Bearer <token>` header.  
> All UUIDs are standard v4 UUIDs.  
> All dates are ISO-8601 strings: `"YYYY-MM-DD"`.  
> All timestamps are ISO-8601 with timezone: `"2025-01-15T10:30:00Z"`.  
> Decimal fields are returned as JSON strings to preserve precision.

---

## Review Cycles

### POST `/review-cycles/`

Create a new review cycle in DRAFT status.

**Roles**: `hr_admin`

**Request Body**
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

| Field | Type | Required | Validation |
|-------|------|----------|------------|
| `name` | string | ✅ | Length 2–255 |
| `cycle_type` | enum | ✅ | `annual`, `semi_annual`, `quarterly`, `monthly`, `custom` |
| `start_date` | date | ✅ | — |
| `end_date` | date | ✅ | Must be after `start_date` |
| `target_setting_deadline` | date | ❌ | Must be ≤ `end_date` |
| `actual_entry_deadline` | date | ❌ | Must be ≤ `end_date` |
| `scoring_start_date` | date | ❌ | Must be ≥ `start_date` |

**Response** `201 Created` → `ReviewCycleRead`  
**Errors**: `409` if an ACTIVE cycle already overlaps these dates; `422` on validation failure

---

### GET `/review-cycles/`

List review cycles for the organisation (paginated).

**Roles**: all authenticated

**Query Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `status` | enum | Filter: `draft`, `active`, `closed`, `archived` |
| `page` | int | Default: 1 |
| `size` | int | Default: 20; max: 100 |

**Response** `200 OK` → `PaginatedReviewCycles`
```json
{
  "items": [ ReviewCycleRead, ... ],
  "total": 5,
  "page": 1,
  "size": 20,
  "pages": 1
}
```

---

### GET `/review-cycles/active`

Get the currently active cycle (where today falls within `start_date–end_date`).

**Roles**: all authenticated  
**Response** `200 OK` → `ReviewCycleRead | null` (returns `null` if no active cycle)

---

### GET `/review-cycles/{cycle_id}`

Get a single review cycle by ID.

**Roles**: all authenticated  
**Response** `200 OK` → `ReviewCycleRead`  
**Errors**: `404` if not found

---

### PUT `/review-cycles/{cycle_id}`

Update editable fields on a DRAFT cycle.

**Roles**: `hr_admin`

**Request Body**
```json
{
  "name": "FY 2025 Mid-Year Review",
  "target_setting_deadline": "2025-02-28",
  "actual_entry_deadline": "2025-12-20",
  "scoring_start_date": "2026-01-15"
}
```

All fields optional. Core dates (`start_date`, `end_date`, `cycle_type`) are immutable.  
**Response** `200 OK` → `ReviewCycleRead`  
**Errors**: `400` if cycle is not in DRAFT status; `404` if not found

---

### PATCH `/review-cycles/{cycle_id}/status`

Transition the cycle's status through its lifecycle.

**Roles**: `hr_admin`

**Request Body**
```json
{ "status": "active" }
```

| Valid transition | Notes |
|----------------|-------|
| `draft` → `active` | Validates no overlap; auto-locks all targets |
| `active` → `closed` | Triggers scoring stub |
| `closed` → `archived` | Terminal state |
| `active` → `draft` *(hr_admin only)* | Revert for corrections |
| `closed` → `active` *(hr_admin only)* | Re-open for late actuals |

**Response** `200 OK` → `ReviewCycleRead`  
**Errors**: `400` for invalid transition; `409` for ACTIVE overlap

---

### ReviewCycleRead Schema

```json
{
  "id": "uuid",
  "name": "FY 2025 Annual Review",
  "cycle_type": "annual",
  "status": "draft",
  "start_date": "2025-01-01",
  "end_date": "2025-12-31",
  "target_setting_deadline": "2025-01-31",
  "actual_entry_deadline": "2025-12-15",
  "scoring_start_date": "2026-01-01",
  "organisation_id": "uuid",
  "created_by_id": "uuid",
  "created_at": "2025-01-01T09:00:00Z",
  "updated_at": "2025-01-01T09:00:00Z"
}
```

---

## Targets

### POST `/targets/`

Create a single KPI target.

**Roles**: `hr_admin`, `executive`, `manager`

**Request Body**
```json
{
  "kpi_id": "uuid",
  "review_cycle_id": "uuid",
  "assignee_type": "individual",
  "assignee_user_id": "uuid",
  "target_value": "100.00",
  "stretch_target_value": "120.00",
  "minimum_value": "70.00",
  "weight": "30.00",
  "notes": "Focus on new client acquisition",
  "milestones": [
    { "milestone_date": "2025-03-31", "expected_value": "25.00", "label": "Q1" },
    { "milestone_date": "2025-06-30", "expected_value": "50.00", "label": "Q2" }
  ]
}
```

| Field | Type | Required | Validation |
|-------|------|----------|------------|
| `kpi_id` | UUID | ✅ | KPI must be ACTIVE |
| `review_cycle_id` | UUID | ✅ | Cycle must not be CLOSED/ARCHIVED |
| `assignee_type` | enum | ✅ | `individual`, `team`, `organisation` |
| `assignee_user_id` | UUID | ✅ if `individual` | User must exist |
| `target_value` | Decimal | ✅ | Must be > 0 |
| `stretch_target_value` | Decimal | ❌ | Must be > `target_value` |
| `minimum_value` | Decimal | ❌ | Must be < `target_value` |
| `weight` | Decimal | ❌ | 0–100, default 100 |

**Response** `201 Created` → `KPITargetRead`  
**Errors**: `400` if KPI inactive or cycle closed; `409` if duplicate target

---

### POST `/targets/bulk`

Assign the same KPI to multiple users at once.

**Roles**: `hr_admin`, `executive`, `manager`

**Request Body**
```json
{
  "kpi_id": "uuid",
  "review_cycle_id": "uuid",
  "user_targets": [
    { "user_id": "uuid-1", "target_value": 100.0, "weight": 30.0, "notes": null },
    { "user_id": "uuid-2", "target_value": 80.0, "weight": 25.0, "stretch_target_value": 100.0 }
  ]
}
```

**Response** `201 Created` → `list[KPITargetRead]`

---

### POST `/targets/cascade`

Distribute a parent target down to individual users.

**Roles**: `hr_admin`, `executive`, `manager`

**Request Body**
```json
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

For `strategy = "manual"`, each entry must also include `"target_value"`:
```json
{ "user_id": "uuid-1", "weight": 50.0, "target_value": 55.0 }
```

**Response** `201 Created` → `list[KPITargetRead]`  
**Errors**: `400` if total_check fails (sum > parent × 1.01)

---

### GET `/targets/`

List targets (paginated + filterable).

**Roles**: all authenticated

**Query Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `cycle_id` | UUID | Filter by review cycle |
| `user_id` | UUID | Filter by assignee user |
| `kpi_id` | UUID | Filter by KPI |
| `assignee_type` | enum | `individual`, `team`, `organisation` |
| `status` | enum | `draft`, `pending_acknowledgement`, etc. |
| `at_risk_only` | bool | Only return at-risk targets (default: false) |
| `page` | int | Default: 1 |
| `size` | int | Default: 20; max: 100 |

**Response** `200 OK`
```json
{
  "items": [ KPITargetRead, ... ],
  "total": 42,
  "page": 1,
  "size": 20,
  "pages": 3
}
```

---

### GET `/targets/me`

My targets in the active cycle (or a specified cycle).

**Roles**: all authenticated

**Query Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `cycle_id` | UUID | Specific cycle; defaults to active cycle |

**Response** `200 OK` → `list[KPITargetRead]`

---

### GET `/targets/weights-check`

Check whether a user's KPI weights sum to 100%.

**Roles**: all authenticated

**Query Parameters**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `cycle_id` | UUID | ✅ | Review cycle |
| `user_id` | UUID | ❌ | User to check; defaults to current user |

**Response** `200 OK`
```json
{
  "user_id": "uuid",
  "cycle_id": "uuid",
  "total_weight": "85.00",
  "is_valid": false,
  "warning": "Total weight is 85.00%, not 100%..."
}
```

---

### GET `/targets/{target_id}`

Get a single target with live progress metrics.

**Roles**: all authenticated  
**Response** `200 OK` → `KPITargetProgressRead`

```json
{
  "id": "uuid",
  "kpi_id": "uuid",
  "kpi": { KPIRead },
  "review_cycle_id": "uuid",
  "assignee_type": "individual",
  "assignee_user_id": "uuid",
  "assignee_org_id": "uuid",
  "target_value": "100.0000",
  "stretch_target_value": "120.0000",
  "minimum_value": "70.0000",
  "weight": "30.00",
  "status": "locked",
  "cascade_parent_id": null,
  "notes": null,
  "milestones": [],
  "set_by_id": "uuid",
  "acknowledged_at": null,
  "locked_at": "2025-01-15T09:00:00Z",
  "created_at": "2025-01-10T08:00:00Z",
  "updated_at": "2025-01-15T09:00:00Z",
  "latest_actual_value": "82.0000",
  "total_actual_to_date": "82.0000",
  "achievement_percentage": "82.00",
  "is_at_risk": false,
  "trend": "improving"
}
```

---

### PUT `/targets/{target_id}`

Update target values and milestones.

**Roles**: `hr_admin`, `executive`, `manager`

**Request Body** (all fields optional)
```json
{
  "target_value": "110.00",
  "stretch_target_value": "130.00",
  "minimum_value": "75.00",
  "weight": "35.00",
  "notes": "Revised upward based on Q4 performance",
  "milestones": [
    { "milestone_date": "2025-06-30", "expected_value": "55.00", "label": "Mid-year" }
  ]
}
```

Note: `milestones` **replaces all existing milestones** when provided.  
**Response** `200 OK` → `KPITargetRead`  
**Errors**: `403` if target is LOCKED

---

### PATCH `/targets/{target_id}/acknowledge`

Employee acknowledges their own target.

**Roles**: the assigned employee (any role that is the `assignee_user_id`)  
**Request Body**: none  
**Response** `200 OK` → `KPITargetRead` with `status: "acknowledged"`  
**Errors**: `403` if trying to acknowledge someone else's target; `400` if status disallows acknowledgment

---

### PATCH `/targets/{target_id}/status`

Transition a target's workflow status.

**Roles**: `hr_admin`, `manager`

**Request Body**
```json
{ "status": "pending_acknowledgement" }
```

Valid values: `pending_acknowledgement`, `approved`, `draft` (revert)  
**Response** `200 OK` → `KPITargetRead`

---

### GET `/targets/{target_id}/cascade-tree`

View the full cascade tree from parent to grandchildren.

**Roles**: `hr_admin`, `executive`, `manager`  
**Response** `200 OK` → `CascadeTreeNode`

```json
{
  "id": "uuid",
  "assignee_type": "organisation",
  "assignee_user_id": null,
  "target_value": "1000.0",
  "weight": "100",
  "status": "locked",
  "children": [
    {
      "id": "uuid",
      "assignee_type": "individual",
      "assignee_user_id": "uuid",
      "target_value": "600.0",
      "weight": "60",
      "status": "locked",
      "children": []
    }
  ]
}
```

---

## Actuals

### POST `/actuals/`

Submit a KPI actual for a measurement period.

**Roles**: all authenticated (employees for own individual targets)

**Request Body**
```json
{
  "target_id": "uuid",
  "period_date": "2025-01-01",
  "actual_value": "82.00",
  "notes": "Sales figure confirmed from CRM export."
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `target_id` | UUID | ✅ | Target must be LOCKED |
| `period_date` | date | ✅ | Must align to KPI frequency; within cycle range |
| `actual_value` | Decimal | ✅ | — |
| `notes` | string | ❌ | Free-form context |

**Response** `201 Created` → `KPIActualRead`  
**Errors**: `400` if target not LOCKED, period invalid, or period misaligned; `403` if insufficient permission

---

### POST `/actuals/bulk`

Submit multiple period actuals in one request.

**Roles**: all authenticated

**Request Body**
```json
{
  "entries": [
    { "target_id": "uuid", "period_date": "2025-01-01", "actual_value": 82.0 },
    { "target_id": "uuid", "period_date": "2025-02-01", "actual_value": 91.5 }
  ]
}
```

Limit: **50 entries per request**. All entries are atomic — if one fails, none are committed.  
**Response** `201 Created` → `list[KPIActualRead]`

---

### GET `/actuals/`

List actuals across the organisation (paginated + filterable).

**Roles**: all authenticated

**Query Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `target_id` | UUID | Filter by target |
| `kpi_id` | UUID | Filter by KPI |
| `status` | enum | `pending_approval`, `approved`, `rejected`, `superseded` |
| `period_start` | date | Actuals from this date onwards |
| `period_end` | date | Actuals up to this date |
| `page` | int | Default: 1 |
| `size` | int | Default: 20; max: 100 |

**Response** `200 OK`
```json
{
  "items": [ KPIActualRead, ... ],
  "total": 30,
  "page": 1,
  "size": 20,
  "pages": 2
}
```

---

### GET `/actuals/pending-review`

Manager's inbox of pending actuals requiring approval.

**Roles**: `hr_admin`, `executive`, `manager`

- `hr_admin` / `executive`: all pending in the organisation
- `manager`: only from direct reports

**Query Parameters**: `page`, `size`  
**Response** `200 OK` → same paginated structure as list

---

### GET `/actuals/{actual_id}`

Get a single actual by ID.

**Roles**: all authenticated  
**Response** `200 OK` → `KPIActualRead`

---

### PATCH `/actuals/{actual_id}`

Edit a pending actual before it is reviewed.

**Roles**: the original submitter (or `hr_admin`/`executive`)

**Request Body** (all optional)
```json
{
  "actual_value": "88.50",
  "notes": "Updated with reconciled figures."
}
```

**Response** `200 OK` → `KPIActualRead`  
**Errors**: `400` if actual is not PENDING_APPROVAL; `403` if not the submitter

---

### POST `/actuals/{actual_id}/review`

Approve or reject a PENDING_APPROVAL actual.

**Roles**: `hr_admin`, `executive`, `manager`

**Request Body**
```json
{ "action": "approve" }
```
or
```json
{ "action": "reject", "rejection_reason": "Please use net revenue, not gross." }
```

`rejection_reason` is **required** when action is `reject`.  
**Response** `200 OK` → `KPIActualRead`  
**Errors**: `400` if actual is not PENDING_APPROVAL; `422` if rejecting without a reason

---

### GET `/actuals/time-series/{target_id}`

Full time series from cycle start to today.

**Roles**: all authenticated  
**Response** `200 OK` → `ActualTimeSeries`

```json
{
  "target_id": "uuid",
  "kpi_id": "uuid",
  "kpi_name": "Monthly Revenue",
  "kpi_unit": "currency",
  "data_points": [
    {
      "period_date": "2025-01-01",
      "period_label": "Jan 2025",
      "actual_value": "85000.0000",
      "target_value": "8333.3333",
      "milestone_value": null,
      "achievement_percentage": "1019.99"
    },
    {
      "period_date": "2025-02-01",
      "period_label": "Feb 2025",
      "actual_value": null,
      "target_value": "8333.3333",
      "milestone_value": null,
      "achievement_percentage": null
    }
  ],
  "overall_achievement": "425.00",
  "periods_with_data": 1,
  "total_periods": 12
}
```

---

### POST `/actuals/{actual_id}/evidence`

Attach a file or URL as evidence to an actual.

**Roles**: all authenticated

**Request Body**
```json
{
  "file_name": "January Sales Report.pdf",
  "file_url": "https://storage.company.com/reports/jan-2025.pdf",
  "file_type": "application/pdf"
}
```

**Response** `201 Created` → `ActualEvidenceRead`

---

### DELETE `/actuals/{actual_id}/evidence/{evidence_id}`

Remove an evidence attachment.

**Roles**: all authenticated  
**Response** `204 No Content`  
**Errors**: `404` if evidence not found

---

### GET `/actuals/for-target/{target_id}`

All actuals for a specific target (including superseded if requested).

**Roles**: all authenticated

**Query Parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `include_superseded` | bool | false | Include superseded (historical) records |
| `page` | int | 1 | — |
| `size` | int | 50 | max: 100 |

**Response** `200 OK` → `list[KPIActualRead]`

---

### KPIActualRead Schema

```json
{
  "id": "uuid",
  "target_id": "uuid",
  "kpi_id": "uuid",
  "period_date": "2025-01-01",
  "period_label": "Jan 2025",
  "actual_value": "82.0000",
  "entry_source": "manual",
  "status": "approved",
  "notes": "From CRM report",
  "submitted_by_id": "uuid",
  "reviewed_by_id": null,
  "reviewed_at": null,
  "rejection_reason": null,
  "evidence_attachments": [],
  "created_at": "2025-01-15T10:00:00Z",
  "updated_at": "2025-01-15T10:00:00Z"
}
```

---

## Common Error Responses

| HTTP Code | Exception Class | Typical Cause |
|-----------|----------------|---------------|
| `400 Bad Request` | `BadRequestException` | Business rule violation (wrong state, invalid period date) |
| `401 Unauthorized` | — | Missing or invalid JWT token |
| `403 Forbidden` | `ForbiddenException` | Insufficient role or accessing another user's resource |
| `404 Not Found` | `NotFoundException` | Resource doesn't exist or doesn't belong to your org |
| `409 Conflict` | `ConflictException` | Duplicate target, overlapping active cycle |
| `422 Unprocessable Entity` | Pydantic | Request body validation failure |

All error responses follow the shape:
```json
{ "detail": "Description of the error." }
```
