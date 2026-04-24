# 02 — Data Models & Database Schema

← [Back to Index](index.md)

---

## Overview

The KPI module creates **7 database tables** in a single Alembic migration (`1811d467c578_create_kpi_tables`):

| Table | Model Class | Purpose |
|-------|------------|---------|
| `kpi_categories` | `KPICategory` | Groups KPIs by department |
| `kpi_tags` | `KPITag` | Free-form labels for searching/filtering |
| `kpis` | `KPI` | The core KPI definition record |
| `kpi_history` | `KPIHistory` | Immutable audit trail of every change |
| `kpi_templates` | `KPITemplate` | System-curated library of pre-built KPIs |
| `kpi_tag_association` | *(join table)* | Many-to-many: KPI ↔ KPITag |
| `kpi_formula_dependency` | *(join table)* | Self-referential many-to-many: KPI ↔ KPI dependencies |

---

## Entity Relationship Overview

```
organisations ──── kpi_categories ──┐
      │                             │
      └───────────────── kpis ──────┼── kpi_history
                          │         │
                    kpi_tag_assoc   │
                          │         │
                       kpi_tags     │
                                    │
users ─────── kpis.created_by_id    │
      └─────── kpis.approved_by_id  │

kpis ──── kpi_formula_dependency ──── kpis   (self-referential)
```

---

## Model: `KPICategory`

**Table**: `kpi_categories`

Organises KPIs into logical department groups with a visual colour coding. Categories can be system-wide (`organisation_id = NULL`) or organisation-specific.

### Columns

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | `UUID` | No | `uuid4()` | Primary key |
| `name` | `VARCHAR(100)` | No | — | Display name |
| `description` | `TEXT` | Yes | `NULL` | Optional prose description |
| `department` | `ENUM(DepartmentCategory)` | No | — | Department affiliation |
| `colour_hex` | `VARCHAR(7)` | No | `#888780` | CSS hex colour, e.g. `#FF5733` |
| `organisation_id` | `UUID` | Yes | `NULL` | FK → `organisations.id` (`SET NULL`). `NULL` = system-wide |
| `created_by_id` | `UUID` | Yes | `NULL` | FK → `users.id` (`SET NULL`) |
| `created_at` | `TIMESTAMPTZ` | No | `now()` | |
| `updated_at` | `TIMESTAMPTZ` | No | `now()` | Auto-updated on change |

### Relationships

- `kpis` → list of `KPI` (back-populated from `KPI.category`)

### Example JSON

```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "name": "Sales Performance",
  "description": "KPIs measuring sales team effectiveness",
  "department": "sales",
  "colour_hex": "#FF5733",
  "organisation_id": "00000000-0000-0000-0001-000000000001",
  "created_at": "2026-04-24T08:00:00Z"
}
```

### DepartmentCategory Enum Values

```
sales | marketing | finance | hr | operations |
engineering | customer_success | product | legal | general
```

---

## Model: `KPITag`

**Table**: `kpi_tags`

Free-form labels that can be applied to multiple KPIs for search and grouping. Tag names must be unique within an organisation.

### Columns

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | `UUID` | No | `uuid4()` | |
| `name` | `VARCHAR(50)` | No | — | Tag label, e.g. `revenue`, `growth` |
| `organisation_id` | `UUID` | No | — | FK → `organisations.id` (`CASCADE`) |
| `created_at` | `TIMESTAMPTZ` | No | `now()` | |

### Constraints

- **Unique**: `(name, organisation_id)` — constraint name `uq_kpi_tag_name_org`

### Relationships

- `kpis` → list of `KPI` via `kpi_tag_association` join table

### Example JSON

```json
{
  "id": "4a7c318f-1234-4567-abcd-ef0123456789",
  "name": "revenue"
}
```

> **Note**: Tags are created implicitly via the KPI service's `get_or_create_tag` method when referenced by name, or can be pre-created and referenced by UUID in `KPICreate.tag_ids`.

---

## Model: `KPI`

**Table**: `kpis`

The central record of the module. Represents a single measurable performance indicator.

### Columns

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | `UUID` | No | `uuid4()` | Primary key |
| `name` | `VARCHAR(255)` | No | — | Human-readable name |
| `code` | `VARCHAR(50)` | No | — | Machine-readable slug. Must be `UPPER_SNAKE_CASE` |
| `description` | `TEXT` | Yes | `NULL` | Detailed description |
| `unit` | `ENUM(MeasurementUnit)` | No | — | Unit of measurement |
| `unit_label` | `VARCHAR(50)` | Yes | `NULL` | Custom label when `unit=custom` |
| `currency_code` | `VARCHAR(3)` | Yes | `NULL` | ISO 4217 currency (e.g. `MYR`, `USD`) when `unit=currency` |
| `frequency` | `ENUM(MeasurementFrequency)` | No | — | How often this KPI is measured |
| `data_source` | `ENUM(DataSourceType)` | No | `manual` | Where the value comes from |
| `formula_expression` | `TEXT` | Yes | `NULL` | Formula string (only when `data_source=formula`) |
| `scoring_direction` | `ENUM(ScoringDirection)` | No | `higher_is_better` | Whether high or low is good |
| `min_value` | `NUMERIC(18,4)` | Yes | `NULL` | Lower clamp for input values |
| `max_value` | `NUMERIC(18,4)` | Yes | `NULL` | Upper clamp for input values |
| `decimal_places` | `INTEGER` | No | `2` | Display precision (0–6) |
| `status` | `ENUM(KPIStatus)` | No | `draft` | Lifecycle stage |
| `is_template` | `BOOLEAN` | No | `false` | Marks org-level reusable templates |
| `is_organisation_wide` | `BOOLEAN` | No | `false` | Visible to all users in org |
| `version` | `INTEGER` | No | `1` | Increments on every `update_kpi` call |
| `category_id` | `UUID` | Yes | `NULL` | FK → `kpi_categories.id` (`SET NULL`) |
| `organisation_id` | `UUID` | No | — | FK → `organisations.id` (`CASCADE`) |
| `created_by_id` | `UUID` | No | — | FK → `users.id` (`RESTRICT`) |
| `approved_by_id` | `UUID` | Yes | `NULL` | FK → `users.id` (`SET NULL`). Set when approved |
| `approved_at` | `TIMESTAMPTZ` | Yes | `NULL` | Timestamp of approval |
| `deprecated_at` | `TIMESTAMPTZ` | Yes | `NULL` | Timestamp of deprecation |
| `created_at` | `TIMESTAMPTZ` | No | `now()` | |
| `updated_at` | `TIMESTAMPTZ` | No | `now()` | Auto-updated on change |

### Constraints & Indexes

| Name | Type | Columns | Purpose |
|------|------|---------|---------|
| `uq_kpi_org_code` | UNIQUE | `(organisation_id, code)` | Prevents duplicate codes per org |
| `ix_kpi_org_status` | INDEX | `(organisation_id, status)` | Fast filtering of active KPIs |
| `ix_kpi_category` | INDEX | `(category_id)` | Fast category lookups |

### Relationships

| Relationship | Type | Description |
|-------------|------|-------------|
| `category` | Many-to-one | The `KPICategory` this KPI belongs to |
| `tags` | Many-to-many | `KPITag` records via `kpi_tag_association` |
| `organisation` | Many-to-one | The owning `Organisation` |
| `created_by` | Many-to-one | The `User` who created it |
| `approved_by` | Many-to-one | The `User` who approved it |
| `formula_dependencies` | Self many-to-many | Other `KPI` records this formula depends on |
| `history` | One-to-many | Ordered list of `KPIHistory` records |

### Enum Reference

**MeasurementUnit**
```
percentage | currency | count | score | ratio | duration_hours | custom
```

**MeasurementFrequency**
```
daily | weekly | monthly | quarterly | yearly | on_demand
```

**DataSourceType**
```
manual | formula | integration
```

**ScoringDirection**
```
higher_is_better | lower_is_better
```

**KPIStatus**
```
draft | pending_approval | active | deprecated | archived
```

### Example JSON (full `KPIRead` response)

```json
{
  "id": "b1c2d3e4-f5a6-7890-abcd-ef1234567890",
  "name": "Gross Profit Margin",
  "code": "GROSS_PROFIT_MARGIN",
  "description": "Percentage of revenue remaining after cost of goods sold.",
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
  "version": 3,
  "category": {
    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "name": "Finance KPIs",
    "description": null,
    "department": "finance",
    "colour_hex": "#4A90D9",
    "organisation_id": "...",
    "created_at": "2026-04-24T08:00:00Z"
  },
  "tags": [
    {"id": "aaa...", "name": "finance"},
    {"id": "bbb...", "name": "margin"}
  ],
  "organisation_id": "00000000-0000-0000-0001-000000000001",
  "created_by_id": "00000000-0000-0000-0000-000000000010",
  "approved_by_id": "00000000-0000-0000-0000-000000000010",
  "approved_at": "2026-04-24T09:00:00Z",
  "created_at": "2026-04-24T08:00:00Z",
  "updated_at": "2026-04-24T09:05:00Z"
}
```

---

## Model: `KPIHistory`

**Table**: `kpi_history`

Immutable audit trail. A new record is created **every time** a KPI is created or updated. It stores a full JSON snapshot of the KPI at that point in time so any version can be reconstructed.

### Columns

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| `id` | `UUID` | No | Primary key |
| `kpi_id` | `UUID` | No | FK → `kpis.id` (`CASCADE`) |
| `version` | `INTEGER` | No | Matches `kpi.version` at time of snapshot |
| `change_summary` | `VARCHAR(500)` | Yes | Human-readable description of the change |
| `snapshot` | `JSON` | No | Full frozen copy of the KPI row's fields |
| `changed_by_id` | `UUID` | No | FK → `users.id` (`RESTRICT`) |
| `changed_at` | `TIMESTAMPTZ` | No | Auto-set to `now()` |

### When entries are created

1. **On KPI creation** — `change_summary = "Initial creation"`, `version = 1`
2. **On every `PUT /kpis/{id}`** — snapshot of the *old* state is saved before applying new changes, `version` incremented

### Example JSON (KPIHistoryRead response)

```json
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
    ...
  },
  "changed_by_id": "00000000-0000-0000-0000-000000000010",
  "changed_at": "2026-04-24T08:00:00Z"
}
```

---

## Model: `KPITemplate`

**Table**: `kpi_templates`

A curated, read-only library of pre-built KPI definitions seeded by the system. Users can **clone** a template into their organisation to create a fully customisable KPI.

### Columns

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | `UUID` | No | `uuid4()` | |
| `name` | `VARCHAR(255)` | No | — | |
| `description` | `TEXT` | Yes | `NULL` | |
| `department` | `ENUM(DepartmentCategory)` | No | — | |
| `unit` | `ENUM(MeasurementUnit)` | No | — | |
| `frequency` | `ENUM(MeasurementFrequency)` | No | — | |
| `scoring_direction` | `ENUM(ScoringDirection)` | No | — | |
| `suggested_formula` | `TEXT` | Yes | `NULL` | Optional formula suggestion |
| `tags` | `JSON` | No | `[]` | Array of tag name strings |
| `usage_count` | `INTEGER` | No | `0` | Incremented when cloned |
| `is_active` | `BOOLEAN` | No | `true` | Soft-hide without deleting |
| `created_at` | `TIMESTAMPTZ` | No | `now()` | |

> **Note on `tags` column type**: The column uses `JSON` (not PostgreSQL `ARRAY`) for compatibility with the SQLite-based test database. In production, the value is always a JSON array of strings such as `["finance", "margin", "profit"]`.

### Seeded Templates

| Department | Name | Unit | Frequency | Direction |
|----------|------|------|-----------|-----------|
| Sales | Monthly Revenue Growth | percentage | monthly | higher |
| Sales | Sales Win Rate | percentage | monthly | higher |
| Sales | Average Deal Size | currency | monthly | higher |
| Sales | Customer Acquisition Cost | currency | monthly | lower |
| HR | Employee Turnover Rate | percentage | quarterly | lower |
| HR | Time to Hire | duration_hours | monthly | lower |
| HR | Employee Satisfaction Score | score | quarterly | higher |
| Finance | Gross Profit Margin | percentage | monthly | higher |
| Finance | Operating Cash Flow | currency | monthly | higher |
| Operations | Defect Rate | percentage | monthly | lower |
| Operations | On-Time Delivery Rate | percentage | monthly | higher |
| Engineering | Sprint Velocity | count | weekly | higher |
| Engineering | Bug Resolution Time | duration_hours | weekly | lower |

---

## Association Tables

### `kpi_tag_association`

Many-to-many join between `kpis` and `kpi_tags`. Cascade deletes both ways.

```sql
CREATE TABLE kpi_tag_association (
    kpi_id UUID NOT NULL REFERENCES kpis(id) ON DELETE CASCADE,
    tag_id UUID NOT NULL REFERENCES kpi_tags(id) ON DELETE CASCADE,
    PRIMARY KEY (kpi_id, tag_id)
);
```

### `kpi_formula_dependency`

Self-referential many-to-many on `kpis`. Records which KPIs a formula KPI depends on. Used for circular dependency detection.

```sql
CREATE TABLE kpi_formula_dependency (
    parent_kpi_id     UUID NOT NULL REFERENCES kpis(id) ON DELETE CASCADE,
    dependency_kpi_id UUID NOT NULL REFERENCES kpis(id) ON DELETE CASCADE,
    PRIMARY KEY (parent_kpi_id, dependency_kpi_id)
);
```

**Example**: If `GROSS_PROFIT_MARGIN` uses formula `(REVENUE - COST) / REVENUE * 100`, then two rows are inserted:

```
parent_kpi_id = GROSS_PROFIT_MARGIN.id
dependency_kpi_id = REVENUE.id

parent_kpi_id = GROSS_PROFIT_MARGIN.id
dependency_kpi_id = COST.id
```

---

## Technical: Eager Loading Strategy

Every KPI query in `service.py` uses `selectinload` to avoid N+1 queries:

```python
def _kpi_load_options():
    return [
        selectinload(KPI.category),
        selectinload(KPI.tags),
        selectinload(KPI.formula_dependencies),
    ]
```

This issues 3 additional SELECT queries (one per relationship), fetching all related records in bulk rather than one query per row.

---

← [Back to Index](index.md) | Previous: [01 — Overview](01-overview.md) | Next: [03 — Formula Engine →](03-formula-engine.md)
