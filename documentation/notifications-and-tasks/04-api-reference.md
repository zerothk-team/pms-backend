# 04 — API Reference

All endpoints are under the base path **`/api/v1`**.

**Authentication**: All endpoints require a valid JWT bearer token.
```
Authorization: Bearer <access_token>
```

---

## Notifications Endpoints

### `GET /notifications/`

**Summary**: List notifications for the authenticated user.

**Access**: Any authenticated user (own notifications only).

**Query Parameters**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `status` | `string` | No | (all) | Filter by status: `unread`, `read`, or `dismissed` |
| `limit` | `integer` | No | `50` | Max results to return. Capped at `100`. |
| `before_id` | `uuid` | No | — | Cursor — return notifications older than this ID |

**Response: `200 OK`**

```json
{
  "notifications": [
    {
      "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "recipient_id": "a1b2c3d4-...",
      "organisation_id": "org-uuid-here",
      "notification_type": "kpi_at_risk",
      "channel": "in_app",
      "status": "unread",
      "title": "KPI At Risk: Revenue Growth",
      "body": "Your KPI \"Revenue Growth\" is currently at 45% of target. Immediate attention may be required.",
      "action_url": "/targets/550e8400-...",
      "metadata_": null,
      "sent_at": "2025-03-01T08:00:00Z",
      "read_at": null,
      "expires_at": "2025-04-01T08:00:00Z",
      "created_at": "2025-03-01T08:00:00Z"
    }
  ],
  "unread_count": 7,
  "has_more": false
}
```

**Pagination**: Use cursor-based pagination by passing the `id` of the last
notification in the response as `before_id` in the next request.

**Example**:

```bash
# First page
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/notifications/?limit=20&status=unread"

# Next page (cursor)
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/notifications/?limit=20&before_id=3fa85f64-5717-4562-b3fc-2c963f66afa6"
```

---

### `GET /notifications/unread-count`

**Summary**: Get the unread notification count for the badge counter in the UI.

**Access**: Any authenticated user.

**No query parameters.**

**Response: `200 OK`**

```json
{
  "unread": 7
}
```

**Example**:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/notifications/unread-count"
```

> **UI usage pattern**: Call this endpoint on page load and every 30–60 seconds
> to keep the notification badge count up to date.

---

### `PATCH /notifications/{notification_id}/read`

**Summary**: Mark a single notification as read.

**Access**: Any authenticated user (own notifications only).

**Path Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `notification_id` | `uuid` | UUID of the notification to mark as read |

**Request body**: None.

**Response: `200 OK`** — the updated notification object.

```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "status": "read",
  "read_at": "2025-03-15T10:30:00Z",
  ...
}
```

**Error responses**

| Status | Meaning |
|--------|---------|
| `403 Forbidden` | Notification belongs to a different user |
| `404 Not Found` | No notification with that ID exists |

**Example**:

```bash
curl -X PATCH \
  -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/notifications/3fa85f64-5717-4562-b3fc-2c963f66afa6/read"
```

> **Idempotent**: If the notification is already `READ`, this returns `200` without
> modifying `read_at` again.

---

### `POST /notifications/read-all`

**Summary**: Mark all unread notifications as read for the authenticated user.

**Access**: Any authenticated user.

**Request body**: None.

**Response: `200 OK`**

```json
{
  "marked_read": 7
}
```

The `marked_read` field shows how many notifications were updated.
If there are no unread notifications, returns `{"marked_read": 0}`.

**Example**:

```bash
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/notifications/read-all"
```

---

### `DELETE /notifications/{notification_id}`

**Summary**: Dismiss (permanently delete) a notification.

**Access**: Any authenticated user (own notifications only).

**Path Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `notification_id` | `uuid` | UUID of the notification to delete |

**Request body**: None.

**Response: `204 No Content`** — empty body.

**Error responses**

| Status | Meaning |
|--------|---------|
| `403 Forbidden` | Notification belongs to a different user |
| `404 Not Found` | No notification with that ID exists |

**Example**:

```bash
curl -X DELETE \
  -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/notifications/3fa85f64-5717-4562-b3fc-2c963f66afa6"
```

> **Note**: This is a **hard delete**.  The row is permanently removed from the
> database.  The automated cleanup job soft-deletes (sets `status=dismissed`)
> before the final removal — this endpoint bypasses soft-delete.

---

### `GET /notifications/preferences/`

**Summary**: Get notification preferences for the authenticated user.

**Access**: Any authenticated user.

**No query parameters.**

**Side effect**: If the user has never set preferences, a new row is created with
all defaults (`True` for everything, 3 days for period-closing, `immediate` for digest).

**Response: `200 OK`**

```json
{
  "id": "pref-uuid-here",
  "user_id": "a1b2c3d4-...",
  "organisation_id": "org-uuid-here",
  "kpi_at_risk_in_app": true,
  "kpi_at_risk_email": true,
  "actual_due_in_app": true,
  "actual_due_email": false,
  "target_achieved_in_app": true,
  "target_achieved_email": true,
  "period_closing_in_app": true,
  "period_closing_email": true,
  "score_finalised_in_app": true,
  "score_finalised_email": true,
  "score_adjusted_in_app": true,
  "score_adjusted_email": true,
  "period_closing_days_before": 3,
  "email_digest_frequency": "immediate",
  "updated_at": "2025-03-01T00:00:00Z"
}
```

**Example**:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/notifications/preferences/"
```

---

### `PUT /notifications/preferences/`

**Summary**: Update notification preferences for the authenticated user.

**Access**: Any authenticated user.

**Request body** (partial update — only include fields to change):

```json
{
  "kpi_at_risk_email": false,
  "actual_due_email": false,
  "period_closing_days_before": 5,
  "email_digest_frequency": "daily"
}
```

**Preference fields**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `kpi_at_risk_in_app` | `boolean` | `true` | In-app alerts for KPI_AT_RISK / TEAM_KPI_AT_RISK |
| `kpi_at_risk_email` | `boolean` | `true` | Email alerts for KPI_AT_RISK / TEAM_KPI_AT_RISK |
| `actual_due_in_app` | `boolean` | `true` | In-app reminders for ACTUAL_ENTRY_DUE |
| `actual_due_email` | `boolean` | `true` | Email reminders for ACTUAL_ENTRY_DUE |
| `target_achieved_in_app` | `boolean` | `true` | In-app for TARGET_ACHIEVED / STRETCH_TARGET_ACHIEVED |
| `target_achieved_email` | `boolean` | `true` | Email for TARGET_ACHIEVED / STRETCH_TARGET_ACHIEVED |
| `period_closing_in_app` | `boolean` | `true` | In-app for PERIOD_CLOSING_SOON |
| `period_closing_email` | `boolean` | `true` | Email for PERIOD_CLOSING_SOON |
| `score_finalised_in_app` | `boolean` | `true` | In-app for SCORING_COMPLETE / SCORE_FINALISED / SCORE_ADJUSTED |
| `score_finalised_email` | `boolean` | `true` | Email for SCORING_COMPLETE / SCORE_FINALISED / SCORE_ADJUSTED |
| `score_adjusted_in_app` | `boolean` | `true` | In-app for CALIBRATION_REQUIRED |
| `score_adjusted_email` | `boolean` | `true` | Email for CALIBRATION_REQUIRED |
| `period_closing_days_before` | `integer` | `3` | Days-before-end to trigger PERIOD_CLOSING_SOON |
| `email_digest_frequency` | `string` | `"immediate"` | `"immediate"`, `"daily"`, or `"weekly"` |

**Response: `200 OK`** — the full updated preferences object (same shape as GET).

**Example**:

```bash
curl -X PUT \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"kpi_at_risk_email": false, "period_closing_days_before": 5}' \
  "http://localhost:8000/api/v1/notifications/preferences/"
```

---

## Task Management Endpoints

> **Access**: `hr_admin` role required for all task endpoints.

---

### `GET /tasks/jobs/`

**Summary**: List all registered background jobs with their next scheduled run time.

**Access**: `hr_admin` only.

**Response: `200 OK`** — array of job objects.

```json
[
  {
    "id": "check_at_risk_kpis",
    "name": "check_at_risk_kpis_job",
    "next_run_time": "2025-03-16T08:00:00+00:00",
    "trigger": "cron[hour='8']"
  },
  {
    "id": "entry_reminders",
    "name": "send_actual_entry_reminders_job",
    "next_run_time": "2025-03-17T09:00:00+00:00",
    "trigger": "cron[hour='9', day_of_week='mon-fri']"
  },
  {
    "id": "period_closing_reminders",
    "name": "send_period_closing_reminders_job",
    "next_run_time": "2025-03-16T07:00:00+00:00",
    "trigger": "cron[hour='7']"
  },
  {
    "id": "formula_actuals",
    "name": "auto_compute_formula_actuals_job",
    "next_run_time": "2025-04-01T00:30:00+00:00",
    "trigger": "cron[day='1', hour='0', minute='30']"
  },
  {
    "id": "auto_close_cycle",
    "name": "auto_close_cycle_job",
    "next_run_time": "2025-03-16T00:00:00+00:00",
    "trigger": "cron[hour='0']"
  },
  {
    "id": "cleanup_notifications",
    "name": "cleanup_expired_notifications_job",
    "next_run_time": "2025-03-23T03:00:00+00:00",
    "trigger": "cron[day_of_week='sun', hour='3']"
  }
]
```

> **Note**: `next_run_time` is `null` if the scheduler is stopped or the job is paused.

**Example**:

```bash
curl -H "Authorization: Bearer $HR_ADMIN_TOKEN" \
  "http://localhost:8000/api/v1/tasks/jobs/"
```

---

### `POST /tasks/run/{job_id}`

**Summary**: Manually trigger a background job immediately.

**Access**: `hr_admin` only.

**Path Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `job_id` | `string` | One of the registered job IDs (see table below) |

**Valid `job_id` values**

| job_id | Runs |
|--------|------|
| `check_at_risk_kpis` | At-risk KPI detection and notifications |
| `entry_reminders` | Overdue actual entry reminders |
| `period_closing_reminders` | Period-closing warning alerts |
| `formula_actuals` | Auto-compute formula-based KPI actuals |
| `auto_close_cycle` | Close review cycles past their end date |
| `cleanup_notifications` | Delete old READ/DISMISSED notifications |

**Request body**: None.

**Response: `202 Accepted`**

```json
{
  "accepted": true,
  "job_id": "check_at_risk_kpis",
  "message": "Job 'check_at_risk_kpis' queued for immediate execution.",
  "triggered_by": "a1b2c3d4-user-uuid"
}
```

The `202` response is returned **immediately**.  The job runs asynchronously
in the background and does not block the HTTP response.  Check the server logs
for execution status and any errors.

**Error responses**

| Status | Meaning |
|--------|---------|
| `401 Unauthorized` | No or invalid JWT |
| `403 Forbidden` | User is not `hr_admin` |
| `404 Not Found` | Unknown `job_id` |

**Example**:

```bash
curl -X POST \
  -H "Authorization: Bearer $HR_ADMIN_TOKEN" \
  "http://localhost:8000/api/v1/tasks/run/check_at_risk_kpis"
```

---

## Common Error Response Shape

All error responses follow the standard FastAPI format:

```json
{
  "detail": "Human-readable error message"
}
```

Or for validation errors (`422 Unprocessable Entity`):

```json
{
  "detail": [
    {
      "type": "value_error",
      "loc": ["body", "field_name"],
      "msg": "description of the error",
      "input": "...",
      "url": "..."
    }
  ]
}
```

---

## Authentication Flow

Obtain a token first using the auth endpoints:

```bash
# Login
TOKEN=$(curl -s -X POST \
  -H "Content-Type: application/json" \
  -d '{"username": "admin@example.com", "password": "secret"}' \
  "http://localhost:8000/api/v1/auth/login" | jq -r .access_token)

# Use token
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/notifications/unread-count"
```
