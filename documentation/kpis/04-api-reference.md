# 04 — API Reference

← [Back to Index](index.md)

---

## Base URL & Auth

All KPI endpoints share the prefix `/api/v1/kpis`.

| Item | Value |
|------|-------|
| Base URL | `http://localhost:8000` |
| API prefix | `/api/v1/kpis` |
| Auth header | `Authorization: Bearer <jwt_token>` |
| Content-Type | `application/json` |

Obtain a JWT by calling `POST /api/v1/auth/login` first. See the [Auth module docs](../auth/) for details.

### Role Summary

| Role | Capabilities |
|------|-------------|
| Any authenticated user | GET all read endpoints |
| `manager` | Create/update categories, create/update/clone KPIs |
| `hr_admin` | All of the above + delete, approve, promote to template, status changes |

---

## Endpoint Overview

| # | Method | Path | Auth | Min Role | Summary |
|---|--------|------|------|---------|---------|
| 1 | `GET` | `/kpis/categories/` | ✓ | any | List categories |
| 2 | `POST` | `/kpis/categories/` | ✓ | manager | Create category |
| 3 | `PUT` | `/kpis/categories/{id}` | ✓ | hr_admin | Update category |
| 4 | `DELETE` | `/kpis/categories/{id}` | ✓ | hr_admin | Delete category |
| 5 | `GET` | `/kpis/tags/` | ✓ | any | List tags |
| 6 | `GET` | `/kpis/templates/` | ✓ | any | List system templates |
| 7 | `POST` | `/kpis/templates/clone/` | ✓ | manager | Clone template to KPI |
| 8 | `POST` | `/kpis/validate-formula` | ✓ | any | Validate formula |
| 9 | `GET` | `/kpis/` | ✓ | any | List KPIs (paginated) |
| 10 | `POST` | `/kpis/` | ✓ | manager | Create KPI |
| 11 | `GET` | `/kpis/{id}` | ✓ | any | Get single KPI |
| 12 | `PUT` | `/kpis/{id}` | ✓ | manager | Update KPI definition |
| 13 | `PATCH` | `/kpis/{id}/status` | ✓ | any* | Transition KPI status |
| 14 | `GET` | `/kpis/{id}/history` | ✓ | any | Get KPI version history |
| 15 | `POST` | `/kpis/{id}/promote-template` | ✓ | hr_admin | Mark KPI as template |

> *Status endpoint is accessible to any authenticated user, but transitions are role-gated within the service.

---

## 1. `GET /kpis/categories/`

Returns all KPI categories visible to the user's organisation (both organisation-specific and system-wide).

### Request

```bash
curl -s http://localhost:8000/api/v1/kpis/categories/ \
  -H "Authorization: Bearer $TOKEN"
```

### Response `200 OK`

```json
[
  {
    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "name": "Sales Performance",
    "description": "KPIs for the sales team",
    "department": "sales",
    "colour_hex": "#FF5733",
    "organisation_id": "00000000-0000-0000-0001-000000000001",
    "created_at": "2026-04-24T08:00:00Z"
  }
]
```

---

## 2. `POST /kpis/categories/`

Creates a new KPI category for the user's organisation.

### Request Body

```json
{
  "name": "Sales Performance",
  "description": "KPIs for measuring revenue and win rate",
  "department": "sales",
  "colour_hex": "#FF5733"
}
```

| Field | Type | Required | Constraints |
|-------|------|---------|------------|
| `name` | string | ✓ | 1–100 chars |
| `description` | string | — | |
| `department` | enum | ✓ | `DepartmentCategory` value |
| `colour_hex` | string | — | Default `#888780`; pattern `#RRGGBB` |

### Response `201 Created`

```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "name": "Sales Performance",
  "description": "KPIs for measuring revenue and win rate",
  "department": "sales",
  "colour_hex": "#FF5733",
  "organisation_id": "00000000-0000-0000-0001-000000000001",
  "created_at": "2026-04-24T08:00:00Z"
}
```

### Errors

| Code | When |
|------|------|
| `401` | No/invalid JWT |
| `403` | User lacks `hr_admin` or `manager` role |
| `422` | Validation failure (bad `colour_hex`, etc.) |

---

## 3. `PUT /kpis/categories/{category_id}`

Updates a category's `name`, `description`, or `colour_hex`. Department cannot be changed.

### Request Body

```json
{
  "name": "Revenue KPIs",
  "colour_hex": "#22AA55"
}
```

All fields are optional. Only supplied fields are updated.

### Response `200 OK`

Returns the updated `KPICategoryRead` object.

### Errors

| Code | When |
|------|------|
| `403` | User lacks `hr_admin` role |
| `404` | Category not found or belongs to different org |

---

## 4. `DELETE /kpis/categories/{category_id}`

Permanently deletes a category. Fails if any KPIs reference it.

### Response `204 No Content`

Empty body on success.

### Errors

| Code | When |
|------|------|
| `400` | Category has KPIs attached (set them to a different category first) |
| `403` | User lacks `hr_admin` role |
| `404` | Category not found |

---

## 5. `GET /kpis/tags/`

Returns all tags defined within the user's organisation.

### Request

```bash
curl -s http://localhost:8000/api/v1/kpis/tags/ \
  -H "Authorization: Bearer $TOKEN"
```

### Response `200 OK`

```json
[
  {"id": "aaa00000-0000-0000-0000-000000000001", "name": "finance"},
  {"id": "bbb00000-0000-0000-0000-000000000002", "name": "revenue"},
  {"id": "ccc00000-0000-0000-0000-000000000003", "name": "growth"}
]
```

> Tags are created automatically via `get_or_create_tag` when referenced by `tag_ids` in `KPICreate` / `KPIUpdate`. You can also obtain existing tag UUIDs from this endpoint.

---

## 6. `GET /kpis/templates/`

Lists system-curated KPI templates from the library. Optionally filter by department or search term.

### Query Parameters

| Param | Type | Description |
|-------|------|-------------|
| `department` | enum | Filter by `DepartmentCategory` value |
| `search` | string | Case-insensitive search on name/description |

### Request

```bash
curl -s "http://localhost:8000/api/v1/kpis/templates/?department=finance" \
  -H "Authorization: Bearer $TOKEN"
```

### Response `200 OK`

```json
[
  {
    "id": "t000000-0000-0000-0000-000000000008",
    "name": "Gross Profit Margin",
    "description": "Percentage of revenue that exceeds cost of goods sold.",
    "department": "finance",
    "unit": "percentage",
    "frequency": "monthly",
    "scoring_direction": "higher_is_better",
    "suggested_formula": "(REVENUE - COST) / REVENUE * 100",
    "tags": ["finance", "profit", "margin"],
    "usage_count": 47,
    "is_active": true,
    "created_at": "2026-01-01T00:00:00Z"
  }
]
```

---

## 7. `POST /kpis/templates/clone/`

Clones a system template into a new KPI within the user's organisation. The created KPI starts in `draft` status.

### Request Body

```json
{
  "template_id": "t000000-0000-0000-0000-000000000008",
  "name": "Our Gross Profit Margin",
  "code": "OUR_GROSS_PROFIT_MARGIN",
  "category_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6"
}
```

| Field | Type | Required | Notes |
|-------|------|---------|-------|
| `template_id` | UUID | ✓ | Must be an active template |
| `name` | string | — | Defaults to template name |
| `code` | string | ✓ | `UPPER_SNAKE_CASE`, unique per org |
| `category_id` | UUID | — | Override default category |

### Response `201 Created`

Returns a `KPIRead` object (same shape as `POST /kpis/`). The template's `usage_count` is incremented.

### Errors

| Code | When |
|------|------|
| `404` | Template not found or inactive |
| `409` | Code already exists in org |
| `403` | User lacks `hr_admin` or `manager` role |

---

## 8. `POST /kpis/validate-formula`

Validates a formula expression without persisting anything. Useful for real-time editor feedback.

### Request Body

```json
{
  "expression": "(REVENUE - COST) / REVENUE * 100"
}
```

### Response `200 OK` — Valid

```json
{
  "valid": true,
  "referenced_codes": ["REVENUE", "COST"],
  "error": null
}
```

### Response `200 OK` — Invalid

```json
{
  "valid": false,
  "referenced_codes": [],
  "error": "KPI code not found in organisation: COST"
}
```

Both valid and invalid results return `200`. Inspect the `valid` boolean to determine success.

> **Note**: This endpoint verifies that all referenced KPI codes exist in the organisation. It does **not** check for circular dependencies (that check runs during `POST /kpis/`).

---

## 9. `GET /kpis/`

Returns a paginated list of KPIs for the user's organisation.

### Query Parameters

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `page` | int | `1` | Page number (≥1) |
| `size` | int | `20` | Items per page (1–100) |
| `status` | enum | — | Filter by `KPIStatus` |
| `category_id` | UUID | — | Filter by category |
| `department` | enum | — | Filter by department via category |
| `data_source` | enum | — | Filter by `DataSourceType` |
| `tag_ids` | list[UUID] | — | Filter by tags (AND logic) |
| `search` | string | — | Case-insensitive search on name/description |

### Request

```bash
curl -s "http://localhost:8000/api/v1/kpis/?status=active&page=1&size=10" \
  -H "Authorization: Bearer $TOKEN"
```

### Response `200 OK`

```json
{
  "items": [
    {
      "id": "b1c2d3e4-f5a6-7890-abcd-ef1234567890",
      "name": "Gross Profit Margin",
      "code": "GROSS_PROFIT_MARGIN",
      "description": "Percentage of revenue remaining after COGS.",
      "unit": "percentage",
      "unit_label": null,
      "currency_code": null,
      "frequency": "monthly",
      "data_source": "formula",
      "formula_expression": "(REVENUE - COST) / REVENUE * 100",
      "scoring_direction": "higher_is_better",
      "min_value": null,
      "max_value": null,
      "decimal_places": 2,
      "status": "active",
      "is_template": false,
      "is_organisation_wide": true,
      "version": 1,
      "category": { "id": "...", "name": "Finance KPIs", ... },
      "tags": [{"id": "...", "name": "finance"}],
      "organisation_id": "...",
      "created_by_id": "...",
      "approved_by_id": "...",
      "approved_at": "2026-04-24T09:00:00Z",
      "created_at": "2026-04-24T08:00:00Z",
      "updated_at": "2026-04-24T09:05:00Z"
    }
  ],
  "total": 1,
  "page": 1,
  "size": 10,
  "pages": 1
}
```

---

## 10. `POST /kpis/`

Creates a new KPI definition. The KPI starts in `draft` status.

### Request Body — Manual KPI

```json
{
  "name": "Monthly Revenue",
  "code": "REVENUE",
  "description": "Total sales revenue for the month.",
  "unit": "currency",
  "currency_code": "MYR",
  "frequency": "monthly",
  "data_source": "manual",
  "scoring_direction": "higher_is_better",
  "decimal_places": 2,
  "is_organisation_wide": true,
  "category_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "tag_ids": []
}
```

### Request Body — Formula KPI

```json
{
  "name": "Gross Profit Margin",
  "code": "GROSS_PROFIT_MARGIN",
  "description": "Revenue minus COGS as a percentage of revenue.",
  "unit": "percentage",
  "frequency": "monthly",
  "data_source": "formula",
  "formula_expression": "(REVENUE - COST) / REVENUE * 100",
  "scoring_direction": "higher_is_better",
  "decimal_places": 2,
  "is_organisation_wide": true,
  "category_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "tag_ids": []
}
```

### Field Reference

| Field | Type | Required | Constraints |
|-------|------|---------|------------|
| `name` | string | ✓ | 2–255 chars |
| `code` | string | ✓ | 2–50 chars, `^[A-Z0-9_]+$` |
| `description` | string | — | |
| `unit` | enum | ✓ | `MeasurementUnit` |
| `unit_label` | string | — | Required when `unit=custom` |
| `currency_code` | string | — | 3-letter ISO 4217 when `unit=currency` |
| `frequency` | enum | ✓ | `MeasurementFrequency` |
| `data_source` | enum | — | Default `manual` |
| `formula_expression` | string | Conditional | Required if `data_source=formula`; must be null otherwise |
| `scoring_direction` | enum | — | Default `higher_is_better` |
| `min_value` | decimal | — | |
| `max_value` | decimal | — | |
| `decimal_places` | int | — | 0–6, default 2 |
| `category_id` | UUID | — | |
| `tag_ids` | list[UUID] | — | Default `[]` |
| `is_organisation_wide` | bool | — | Default `false` |

### Response `201 Created`

Returns the created `KPIRead` object (see structure under endpoint 9).

### Errors

| Code | When |
|------|------|
| `403` | User lacks `hr_admin` or `manager` role |
| `404` | `category_id` not found in org |
| `409` | `code` already exists in org |
| `422` | Invalid formula syntax, circular dependency, or missing referenced KPI code |

---

## 11. `GET /kpis/{kpi_id}`

Returns a single KPI by its UUID, including its formula dependency list.

### Request

```bash
curl -s http://localhost:8000/api/v1/kpis/b1c2d3e4-f5a6-7890-abcd-ef1234567890 \
  -H "Authorization: Bearer $TOKEN"
```

### Response `200 OK`

Returns `KPIReadWithDependencies` — a superset of `KPIRead` with an additional `formula_dependencies` field:

```json
{
  "id": "b1c2d3e4-f5a6-7890-abcd-ef1234567890",
  "name": "Gross Profit Margin",
  "code": "GROSS_PROFIT_MARGIN",
  ...
  "formula_dependencies": [
    {
      "id": "a1a1a1a1-...",
      "name": "Monthly Revenue",
      "code": "REVENUE",
      "unit": "currency",
      "status": "active",
      ...
    },
    {
      "id": "b2b2b2b2-...",
      "name": "Cost of Goods Sold",
      "code": "COST",
      "unit": "currency",
      "status": "active",
      ...
    }
  ]
}
```

### Errors

| Code | When |
|------|------|
| `404` | KPI not found or belongs to different org |

---

## 12. `PUT /kpis/{kpi_id}`

Updates a KPI's definition fields. Increments `version` by 1 and saves a `KPIHistory` snapshot of the state *before* the update.

> **Immutable fields**: `code`, `data_source`, `unit`, `frequency`, and `organisation_id` cannot be changed after creation.

### Request Body

```json
{
  "name": "Gross Profit Margin (Revised)",
  "description": "Updated description.",
  "formula_expression": "if(REVENUE > 0, (REVENUE - COST) / REVENUE * 100, 0)",
  "scoring_direction": "higher_is_better",
  "decimal_places": 4,
  "tag_ids": ["aaa00000-0000-0000-0000-000000000001"],
  "change_summary": "Added zero-guard to formula"
}
```

All fields are optional. Only supplied fields are applied.

| Field | Notes |
|-------|-------|
| `formula_expression` | Triggers full re-validation and dependency re-resolution on save |
| `change_summary` | Required when `formula_expression` is present |
| `tag_ids` | Replaces the entire tag set (not additive) |

### Response `200 OK`

Returns the updated `KPIRead` object with incremented `version`.

### Errors

| Code | When |
|------|------|
| `400` | `change_summary` missing when changing formula |
| `403` | User lacks `hr_admin` or `manager` role |
| `404` | KPI not found |
| `422` | Invalid formula or circular dependency |

---

## 13. `PATCH /kpis/{kpi_id}/status`

Transitions a KPI through the approval workflow.

### Request Body

```json
{
  "status": "pending_approval",
  "reason": "Ready for review"
}
```

| Field | Type | Required | Notes |
|-------|------|---------|-------|
| `status` | enum | ✓ | Target `KPIStatus` value |
| `reason` | string | — | Optional human note, max 500 chars |

### Valid Transitions

| From | To | Who can do it |
|------|----|--------------|
| `draft` | `pending_approval` | Any authenticated user in org |
| `draft` | `active` | `hr_admin` only |
| `pending_approval` | `active` | `hr_admin` only |
| `pending_approval` | `draft` | Any authenticated user in org |
| `active` | `deprecated` | Any authenticated user in org |
| `deprecated` | `archived` | Any authenticated user in org |
| any | `draft` | `hr_admin` override |

### Response `200 OK`

Returns the updated `KPIRead` with the new `status` and any timestamps (`approved_at`, `deprecated_at`) that were set.

### Errors

| Code | When |
|------|------|
| `400` | Invalid transition (e.g. `active → pending_approval`) |
| `403` | Transition requires `hr_admin` |
| `404` | KPI not found |

### Side Effects

| Transition | Field set |
|-----------|----------|
| `→ active` | `approved_by_id`, `approved_at` |
| `→ deprecated` | `deprecated_at` |

---

## 14. `GET /kpis/{kpi_id}/history`

Returns the full, ordered audit trail of changes to a KPI.

### Request

```bash
curl -s http://localhost:8000/api/v1/kpis/b1c2d3e4-f5a6-7890-abcd-ef1234567890/history \
  -H "Authorization: Bearer $TOKEN"
```

### Response `200 OK`

```json
[
  {
    "id": "c1d2e3f4-a5b6-7890-abcd-ef1234567890",
    "version": 1,
    "change_summary": "Initial creation",
    "snapshot": {
      "id": "b1c2d3e4-...",
      "name": "Gross Profit Margin",
      "code": "GROSS_PROFIT_MARGIN",
      "formula_expression": "(REVENUE - COST) / REVENUE * 100",
      "status": "draft",
      "version": 1,
      "created_at": "2026-04-24T08:00:00Z"
    },
    "changed_by_id": "00000000-0000-0000-0000-000000000010",
    "changed_at": "2026-04-24T08:00:00Z"
  },
  {
    "id": "d2e3f4a5-b6c7-1234-abcd-ef1234567890",
    "version": 2,
    "change_summary": "Added zero-guard to formula",
    "snapshot": {
      "formula_expression": "(REVENUE - COST) / REVENUE * 100",
      "status": "draft",
      "version": 1
    },
    "changed_by_id": "00000000-0000-0000-0000-000000000010",
    "changed_at": "2026-04-24T09:00:00Z"
  }
]
```

> The `snapshot` captures the state of the KPI **before** the change. Version 1 snapshot is the initial state at creation. The list is ordered oldest-first.

---

## 15. `POST /kpis/{kpi_id}/promote-template`

Marks an existing KPI as an organisation-level template (`is_template = true`). This makes it discoverable in the org's template library and clonable by other managers.

### Request

No body required.

```bash
curl -s -X POST \
  http://localhost:8000/api/v1/kpis/b1c2d3e4-f5a6-7890-abcd-ef1234567890/promote-template \
  -H "Authorization: Bearer $TOKEN"
```

### Response `200 OK`

Returns the updated `KPIRead` with `"is_template": true`.

### Errors

| Code | When |
|------|------|
| `400` | KPI is already a template |
| `403` | User lacks `hr_admin` role |
| `404` | KPI not found |

---

## Common Error Shapes

All errors follow the standard FastAPI exception format:

```json
{
  "detail": "Human-readable error message"
}
```

### HTTP Status Code Reference

| Code | Meaning |
|------|---------|
| `200` | Success |
| `201` | Created |
| `204` | No content (DELETE) |
| `400` | Bad request (invalid state, business rule violation) |
| `401` | Missing or invalid JWT |
| `403` | Insufficient role |
| `404` | Resource not found in organisation |
| `409` | Conflict (duplicate code, duplicate name) |
| `422` | Validation error (Pydantic or formula engine) |

---

← [Back to Index](index.md) | Previous: [03 — Formula Engine](03-formula-engine.md) | Next: [05 — Workflows →](05-workflows.md)
