# 06 — Tutorials

← [Back to Index](index.md)

---

## Prerequisites

All tutorials assume:
- The server is running at `http://localhost:8000`
- You have a running PostgreSQL database with migrations applied
- The environment variable `TOKEN` holds a valid JWT

### Obtain a JWT

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "alice@acme.com", "password": "secret"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

echo $TOKEN  # verify token is set
```

### Seed Data Note

When `DEBUG=True`, 13 system KPI templates are seeded automatically at startup. To enable:

```bash
# .env or environment
DEBUG=True
```

---

## Tutorial 1 — Create a Category and a Manual KPI

**Goal**: Create a "Finance" category, then create a `REVENUE` KPI tracked manually.

### Step 1: Create a Category

```bash
curl -s -X POST http://localhost:8000/api/v1/kpis/categories/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Finance KPIs",
    "description": "Financial performance indicators",
    "department": "finance",
    "colour_hex": "#4A90D9"
  }' | python3 -m json.tool
```

**Expected Response** (`201 Created`):

```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "name": "Finance KPIs",
  "description": "Financial performance indicators",
  "department": "finance",
  "colour_hex": "#4A90D9",
  "organisation_id": "00000000-0000-0000-0001-000000000001",
  "created_at": "2026-04-24T08:00:00Z"
}
```

Save the `id`:

```bash
CATEGORY_ID="3fa85f64-5717-4562-b3fc-2c963f66afa6"
```

---

### Step 2: Create a Manual KPI

```bash
curl -s -X POST http://localhost:8000/api/v1/kpis/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"name\": \"Monthly Revenue\",
    \"code\": \"REVENUE\",
    \"description\": \"Total sales revenue collected in the month.\",
    \"unit\": \"currency\",
    \"currency_code\": \"MYR\",
    \"frequency\": \"monthly\",
    \"data_source\": \"manual\",
    \"scoring_direction\": \"higher_is_better\",
    \"decimal_places\": 2,
    \"is_organisation_wide\": true,
    \"category_id\": \"$CATEGORY_ID\",
    \"tag_ids\": []
  }" | python3 -m json.tool
```

**Expected Response** (`201 Created`):

```json
{
  "id": "a1000000-0000-0000-0000-000000000001",
  "name": "Monthly Revenue",
  "code": "REVENUE",
  "description": "Total sales revenue collected in the month.",
  "unit": "currency",
  "unit_label": null,
  "currency_code": "MYR",
  "frequency": "monthly",
  "data_source": "manual",
  "formula_expression": null,
  "scoring_direction": "higher_is_better",
  "min_value": null,
  "max_value": null,
  "decimal_places": 2,
  "status": "draft",
  "is_template": false,
  "is_organisation_wide": true,
  "version": 1,
  "category": {
    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "name": "Finance KPIs",
    "department": "finance",
    ...
  },
  "tags": [],
  "organisation_id": "...",
  "created_by_id": "...",
  "approved_by_id": null,
  "approved_at": null,
  "created_at": "2026-04-24T08:01:00Z",
  "updated_at": "2026-04-24T08:01:00Z"
}
```

**What happened**:
- KPI created with `status: draft` (always the starting status)
- A `KPIHistory` v1 entry was automatically created (`"Initial creation"`)
- `version: 1`
- `formula_expression: null` because `data_source: manual`

Save the ID:

```bash
REVENUE_ID="a1000000-0000-0000-0000-000000000001"
```

---

### Step 3: Create a Second Manual KPI (Cost)

Repeat for `COST`:

```bash
curl -s -X POST http://localhost:8000/api/v1/kpis/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"name\": \"Cost of Goods Sold\",
    \"code\": \"COST\",
    \"description\": \"Total cost of goods and services sold.\",
    \"unit\": \"currency\",
    \"currency_code\": \"MYR\",
    \"frequency\": \"monthly\",
    \"data_source\": \"manual\",
    \"scoring_direction\": \"lower_is_better\",
    \"decimal_places\": 2,
    \"is_organisation_wide\": true,
    \"category_id\": \"$CATEGORY_ID\",
    \"tag_ids\": []
  }" | python3 -m json.tool
```

```bash
COST_ID="a2000000-0000-0000-0000-000000000002"
```

---

## Tutorial 2 — Create a Formula KPI with Dependencies

**Goal**: Create `GROSS_PROFIT_MARGIN` that derives its value from `REVENUE` and `COST`.

### Step 1: (Optional) Validate the Formula First

Use the validation endpoint to check syntax before creating:

```bash
curl -s -X POST http://localhost:8000/api/v1/kpis/validate-formula \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "expression": "(REVENUE - COST) / REVENUE * 100"
  }' | python3 -m json.tool
```

**Expected Response** (`200 OK`):

```json
{
  "valid": true,
  "referenced_codes": ["REVENUE", "COST"],
  "error": null
}
```

---

### Step 2: Create the Formula KPI

```bash
curl -s -X POST http://localhost:8000/api/v1/kpis/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"name\": \"Gross Profit Margin\",
    \"code\": \"GROSS_PROFIT_MARGIN\",
    \"description\": \"Percentage of revenue remaining after cost of goods sold.\",
    \"unit\": \"percentage\",
    \"frequency\": \"monthly\",
    \"data_source\": \"formula\",
    \"formula_expression\": \"(REVENUE - COST) / REVENUE * 100\",
    \"scoring_direction\": \"higher_is_better\",
    \"decimal_places\": 2,
    \"is_organisation_wide\": true,
    \"category_id\": \"$CATEGORY_ID\",
    \"tag_ids\": []
  }" | python3 -m json.tool
```

**Expected Response** (`201 Created`):

```json
{
  "id": "b3000000-0000-0000-0000-000000000003",
  "name": "Gross Profit Margin",
  "code": "GROSS_PROFIT_MARGIN",
  "data_source": "formula",
  "formula_expression": "(REVENUE - COST) / REVENUE * 100",
  "status": "draft",
  "version": 1,
  ...
}
```

Save the ID:

```bash
MARGIN_ID="b3000000-0000-0000-0000-000000000003"
```

---

### Step 3: Fetch with Dependencies

```bash
curl -s http://localhost:8000/api/v1/kpis/$MARGIN_ID \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

**Expected Response** (`200 OK`) — Note the `formula_dependencies` array:

```json
{
  "id": "b3000000-0000-0000-0000-000000000003",
  "name": "Gross Profit Margin",
  "code": "GROSS_PROFIT_MARGIN",
  "formula_expression": "(REVENUE - COST) / REVENUE * 100",
  "formula_dependencies": [
    {
      "id": "a1000000-0000-0000-0000-000000000001",
      "name": "Monthly Revenue",
      "code": "REVENUE",
      "unit": "currency",
      "status": "draft"
    },
    {
      "id": "a2000000-0000-0000-0000-000000000002",
      "name": "Cost of Goods Sold",
      "code": "COST",
      "unit": "currency",
      "status": "draft"
    }
  ]
}
```

---

### Step 4: Attempt Circular Dependency (Expect Error)

Try to add a circular dependency to `REVENUE` that references `GROSS_PROFIT_MARGIN`:

```bash
curl -s -X POST http://localhost:8000/api/v1/kpis/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Broken Revenue",
    "code": "REVENUE_BROKEN",
    "unit": "currency",
    "frequency": "monthly",
    "data_source": "formula",
    "formula_expression": "GROSS_PROFIT_MARGIN * 2"
  }' | python3 -m json.tool
```

**Expected Response** (`422 Unprocessable Entity`):
```json
{
  "detail": "Circular dependency detected: REVENUE_BROKEN → GROSS_PROFIT_MARGIN → REVENUE"
}
```

---

## Tutorial 3 — Full Approval Workflow

**Goal**: Move a KPI from `draft` → `pending_approval` → `active`.

Continuing from Tutorial 1, we have `REVENUE_ID` in `draft` status.

### Step 1: Submit for Approval (Any User)

```bash
curl -s -X PATCH \
  http://localhost:8000/api/v1/kpis/$REVENUE_ID/status \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "status": "pending_approval",
    "reason": "Ready for Q3 targets"
  }' | python3 -m json.tool
```

**Expected Response** (`200 OK`):

```json
{
  "id": "a1000000-0000-0000-0000-000000000001",
  "status": "pending_approval",
  "approved_by_id": null,
  "approved_at": null,
  ...
}
```

---

### Step 2: Approve (hr_admin only)

Login as hr_admin and get a new token:

```bash
ADMIN_TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@acme.com", "password": "adminpass"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
```

```bash
curl -s -X PATCH \
  http://localhost:8000/api/v1/kpis/$REVENUE_ID/status \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "status": "active"
  }' | python3 -m json.tool
```

**Expected Response** (`200 OK`):

```json
{
  "id": "a1000000-0000-0000-0000-000000000001",
  "status": "active",
  "approved_by_id": "00000000-0000-0000-0000-000000000010",
  "approved_at": "2026-04-24T09:00:00Z",
  ...
}
```

**What happened**: `approved_by_id` and `approved_at` were set automatically.

---

### Step 3: Try an Invalid Transition (Expect Error)

```bash
curl -s -X PATCH \
  http://localhost:8000/api/v1/kpis/$REVENUE_ID/status \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status": "draft"}' | python3 -m json.tool
```

**Expected Response** (`400 Bad Request`) — because a regular user cannot reset to draft:

```json
{
  "detail": "Invalid status transition from active to draft"
}
```

---

## Tutorial 4 — Browse Templates and Clone One

**Goal**: Find a "finance" template and clone it into our organisation.

### Step 1: List Finance Templates

```bash
curl -s "http://localhost:8000/api/v1/kpis/templates/?department=finance" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

**Expected Response** (partial):

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
    "usage_count": 0,
    "is_active": true,
    "created_at": "2026-01-01T00:00:00Z"
  },
  {
    "id": "t000000-0000-0000-0000-000000000009",
    "name": "Operating Cash Flow",
    "department": "finance",
    "unit": "currency",
    "frequency": "monthly",
    "scoring_direction": "higher_is_better",
    "suggested_formula": null,
    ...
  }
]
```

Save the template ID:

```bash
TEMPLATE_ID="t000000-0000-0000-0000-000000000008"
```

---

### Step 2: Clone the Template

```bash
curl -s -X POST http://localhost:8000/api/v1/kpis/templates/clone/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"template_id\": \"$TEMPLATE_ID\",
    \"name\": \"Acme Gross Profit Margin\",
    \"code\": \"ACME_GROSS_PROFIT_MARGIN\",
    \"category_id\": \"$CATEGORY_ID\"
  }" | python3 -m json.tool
```

**Expected Response** (`201 Created`):

```json
{
  "id": "c4000000-0000-0000-0000-000000000004",
  "name": "Acme Gross Profit Margin",
  "code": "ACME_GROSS_PROFIT_MARGIN",
  "unit": "percentage",
  "frequency": "monthly",
  "data_source": "formula",
  "formula_expression": "(REVENUE - COST) / REVENUE * 100",
  "scoring_direction": "higher_is_better",
  "status": "draft",
  "version": 1,
  ...
}
```

**What happened**:
- A new KPI was created in our organisation with `status: draft`
- `usage_count` on the template was incremented by 1
- The formula from the template was copied verbatim — we can customise it with `PUT /kpis/{id}`

---

## Tutorial 5 — Update a KPI and Inspect Version History

**Goal**: Update the formula of `GROSS_PROFIT_MARGIN`, then view the history to see the before/after snapshots.

### Step 1: Update the Formula

```bash
curl -s -X PUT \
  http://localhost:8000/api/v1/kpis/$MARGIN_ID \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "formula_expression": "if(REVENUE > 0, (REVENUE - COST) / REVENUE * 100, 0)",
    "description": "Updated to guard against zero revenue.",
    "change_summary": "Added zero-guard with if() to prevent division by zero"
  }' | python3 -m json.tool
```

**Expected Response** (`200 OK`):

```json
{
  "id": "b3000000-0000-0000-0000-000000000003",
  "name": "Gross Profit Margin",
  "formula_expression": "if(REVENUE > 0, (REVENUE - COST) / REVENUE * 100, 0)",
  "description": "Updated to guard against zero revenue.",
  "version": 2,
  ...
}
```

Note `version` incremented from `1` to `2`.

---

### Step 2: Inspect Version History

```bash
curl -s http://localhost:8000/api/v1/kpis/$MARGIN_ID/history \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

**Expected Response** (`200 OK`):

```json
[
  {
    "id": "h1000000-0000-0000-0000-000000000001",
    "version": 1,
    "change_summary": "Initial creation",
    "snapshot": {
      "name": "Gross Profit Margin",
      "code": "GROSS_PROFIT_MARGIN",
      "formula_expression": "(REVENUE - COST) / REVENUE * 100",
      "description": "Percentage of revenue remaining after cost of goods sold.",
      "status": "draft",
      "version": 1
    },
    "changed_by_id": "00000000-0000-0000-0000-000000000010",
    "changed_at": "2026-04-24T08:01:00Z"
  },
  {
    "id": "h2000000-0000-0000-0000-000000000002",
    "version": 2,
    "change_summary": "Added zero-guard with if() to prevent division by zero",
    "snapshot": {
      "name": "Gross Profit Margin",
      "formula_expression": "(REVENUE - COST) / REVENUE * 100",
      "description": "Percentage of revenue remaining after cost of goods sold.",
      "status": "draft",
      "version": 1
    },
    "changed_by_id": "00000000-0000-0000-0000-000000000010",
    "changed_at": "2026-04-24T09:00:00Z"
  }
]
```

**Reading the history**:
- Version 1 snapshot = the KPI at creation (before any changes)
- Version 2 snapshot = the state *before* the formula change was applied

This means: to reconstruct any historical version, read the snapshot at `version = N`.

---

## Tutorial 6 — Use the Formula Validation Endpoint

**Goal**: Test formula expressions interactively before committing to a KPI definition.

### Test 1: Valid Formula

```bash
curl -s -X POST http://localhost:8000/api/v1/kpis/validate-formula \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"expression": "round(abs(TARGET - ACTUAL) / TARGET * 100, 2)"}' \
  | python3 -m json.tool
```

**Expected**:

```json
{
  "valid": true,
  "referenced_codes": ["TARGET", "ACTUAL"],
  "error": null
}
```

---

### Test 2: Syntax Error

```bash
curl -s -X POST http://localhost:8000/api/v1/kpis/validate-formula \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"expression": "REVENUE +* COST"}' \
  | python3 -m json.tool
```

**Expected**:

```json
{
  "valid": false,
  "referenced_codes": [],
  "error": "Invalid syntax: invalid syntax (<unknown>, line 1)"
}
```

---

### Test 3: Unsafe Expression (Injection Attempt)

```bash
curl -s -X POST http://localhost:8000/api/v1/kpis/validate-formula \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"expression": "__import__(\"os\").system(\"rm -rf /\")"}' \
  | python3 -m json.tool
```

**Expected** (`422 Unprocessable Entity` or safe validation failure):

```json
{
  "valid": false,
  "referenced_codes": [],
  "error": "Unsafe expression: disallowed node type ast.Attribute"
}
```

The formula engine blocks this at the AST level — `ast.Attribute` (for `__import__`) is not in the safe node whitelist.

---

### Test 4: Missing KPI Code

```bash
curl -s -X POST http://localhost:8000/api/v1/kpis/validate-formula \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"expression": "NONEXISTENT_KPI + REVENUE"}' \
  | python3 -m json.tool
```

**Expected**:

```json
{
  "valid": false,
  "referenced_codes": [],
  "error": "KPI code not found in organisation: NONEXISTENT_KPI"
}
```

---

### Test 5: Conditional Formula

```bash
curl -s -X POST http://localhost:8000/api/v1/kpis/validate-formula \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"expression": "if(REVENUE > 0, PROFIT / REVENUE * 100, 0)"}' \
  | python3 -m json.tool
```

**Expected** (assuming `REVENUE` and `PROFIT` exist in the org):

```json
{
  "valid": true,
  "referenced_codes": ["REVENUE", "PROFIT"],
  "error": null
}
```

---

## Tutorial 7 — Promote a KPI to an Organisation Template

**Goal**: After a KPI has proven useful, promote it to a template so it can be cloned by other managers.

### Prerequisite: KPI must be active

```bash
# First activate it (hr_admin required)
curl -s -X PATCH \
  http://localhost:8000/api/v1/kpis/$MARGIN_ID/status \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status": "active"}' | python3 -m json.tool
```

### Promote to Template

```bash
curl -s -X POST \
  http://localhost:8000/api/v1/kpis/$MARGIN_ID/promote-template \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  | python3 -m json.tool
```

**Expected Response** (`200 OK`):

```json
{
  "id": "b3000000-0000-0000-0000-000000000003",
  "name": "Gross Profit Margin",
  "is_template": true,
  "status": "active",
  ...
}
```

Now other managers in the organisation can clone this KPI using `POST /kpis/templates/clone/` (note: `is_template=true` org-level templates are separate from the system templates at `GET /kpis/templates/`).

---

## Common curl Helpers

```bash
# Pretty-print all active KPIs
curl -s "http://localhost:8000/api/v1/kpis/?status=active" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# Filter by department
curl -s "http://localhost:8000/api/v1/kpis/?department=finance" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# Search by name
curl -s "http://localhost:8000/api/v1/kpis/?search=margin" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# Paginate (page 2, 5 per page)
curl -s "http://localhost:8000/api/v1/kpis/?page=2&size=5" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# Delete a category (hr_admin only)
curl -s -X DELETE \
  "http://localhost:8000/api/v1/kpis/categories/$CATEGORY_ID" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
# Returns 204 No Content
```

---

← [Back to Index](index.md) | Previous: [05 — Workflows](05-workflows.md) | Next: [07 — Process Flow Diagrams →](07-process-flow-diagrams.md)
