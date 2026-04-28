> ⛔ DEPRECATED — This file is superseded by `MASTER_USER_GUIDE.md` at the repo root.
> Do not update this file. It is kept for historical reference only.
> Last active version: see git history.

# Copilot Prompt — Part 2: KPI Definition, Library & Formula Engine
> **Model**: Claude Sonnet 4.6 | **Depends on**: Part 1 complete

---

## Context

Part 1 is complete. The project scaffold, auth, users, and organisations modules are working. Now build the **core KPI module** inside `app/kpis/`. This is the heart of the system — every other module (targets, actuals, scoring) depends on these models.

---

## What to Build in This Part

```
app/kpis/
├── __init__.py
├── models.py        ← KPI, KPICategory, KPITag, KPITemplate models
├── schemas.py       ← All Pydantic v2 request/response schemas
├── service.py       ← KPIService with full CRUD + formula validation
├── router.py        ← All KPI endpoints
├── formula.py       ← Safe formula parser and evaluator
└── enums.py         ← All KPI-specific enums
```

---

## 1. `app/kpis/enums.py`

Define these Python `Enum` classes (also registered as SQLAlchemy `Enum` types):

```python
class MeasurementUnit(str, Enum):
    PERCENTAGE = "percentage"        # 0–100 or 0–∞ (configurable)
    CURRENCY = "currency"            # tied to org's currency setting
    COUNT = "count"                  # integer count
    SCORE = "score"                  # arbitrary numeric score
    RATIO = "ratio"                  # e.g. 3.5:1
    DURATION_HOURS = "duration_hours"
    CUSTOM = "custom"                # free-form unit label

class MeasurementFrequency(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"
    ON_DEMAND = "on_demand"          # no schedule, entered whenever

class DataSourceType(str, Enum):
    MANUAL = "manual"                # human enters value
    FORMULA = "formula"              # calculated from other KPIs
    INTEGRATION = "integration"      # synced from external system (stub for now)

class ScoringDirection(str, Enum):
    HIGHER_IS_BETTER = "higher_is_better"   # e.g. revenue, NPS
    LOWER_IS_BETTER = "lower_is_better"     # e.g. defect rate, churn

class KPIStatus(str, Enum):
    DRAFT = "draft"                  # being defined, not yet usable
    PENDING_APPROVAL = "pending_approval"
    ACTIVE = "active"                # can be assigned
    DEPRECATED = "deprecated"        # retired, historical data preserved
    ARCHIVED = "archived"            # hidden from lists

class DepartmentCategory(str, Enum):
    SALES = "sales"
    MARKETING = "marketing"
    FINANCE = "finance"
    HR = "hr"
    OPERATIONS = "operations"
    ENGINEERING = "engineering"
    CUSTOMER_SUCCESS = "customer_success"
    PRODUCT = "product"
    LEGAL = "legal"
    GENERAL = "general"
```

---

## 2. `app/kpis/models.py`

### Model: `KPICategory`

```
Table: kpi_categories
```

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `name` | String(100) | not null |
| `description` | Text | nullable |
| `department` | Enum(DepartmentCategory) | not null |
| `colour_hex` | String(7) | hex colour code e.g. `#534AB7`, default `#888780` |
| `organisation_id` | UUID FK → organisations.id | nullable (null = system-wide) |
| `created_by_id` | UUID FK → users.id | nullable |
| `created_at` | DateTime UTC | |
| `updated_at` | DateTime UTC | |

---

### Model: `KPITag`

```
Table: kpi_tags
```

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `name` | String(50) | unique per org |
| `organisation_id` | UUID FK → organisations.id | |
| `created_at` | DateTime UTC | |

---

### Model: `KPI`

```
Table: kpis
```

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `name` | String(255) | not null |
| `code` | String(50) | unique per org, URL-safe slug e.g. `SALES_REVENUE_GROWTH` |
| `description` | Text | nullable |
| `unit` | Enum(MeasurementUnit) | not null |
| `unit_label` | String(50) | nullable — custom unit label when unit=CUSTOM |
| `currency_code` | String(3) | nullable — ISO 4217, e.g. MYR, USD |
| `frequency` | Enum(MeasurementFrequency) | not null |
| `data_source` | Enum(DataSourceType) | not null, default MANUAL |
| `formula_expression` | Text | nullable — only when data_source=FORMULA |
| `scoring_direction` | Enum(ScoringDirection) | not null, default HIGHER_IS_BETTER |
| `min_value` | Numeric(18,4) | nullable — clamp input |
| `max_value` | Numeric(18,4) | nullable — clamp input |
| `decimal_places` | Integer | default 2 |
| `status` | Enum(KPIStatus) | not null, default DRAFT |
| `is_template` | Boolean | default False — marks library templates |
| `is_organisation_wide` | Boolean | default False — visible to entire org |
| `version` | Integer | default 1 — increments on definition change |
| `category_id` | UUID FK → kpi_categories.id | nullable |
| `organisation_id` | UUID FK → organisations.id | not null |
| `created_by_id` | UUID FK → users.id | not null |
| `approved_by_id` | UUID FK → users.id | nullable |
| `approved_at` | DateTime UTC | nullable |
| `deprecated_at` | DateTime UTC | nullable |
| `created_at` | DateTime UTC | |
| `updated_at` | DateTime UTC | |

**Relationships:**
- `category` → KPICategory (many-to-one)
- `tags` → KPITag (many-to-many via `kpi_tag_association` join table)
- `organisation` → Organisation
- `created_by` → User
- `approved_by` → User
- `formula_dependencies` → list[KPI] (self-referential many-to-many via `kpi_formula_dependency` join table)
- `targets` → list[KPITarget] (back-populates, defined in targets module)
- `history` → list[KPIHistory]

**Indexes:**
- `(organisation_id, code)` — unique composite
- `(organisation_id, status)` — for filtering active KPIs
- `(category_id)`

---

### Model: `KPIHistory`

Tracks every change to a KPI definition for audit purposes.

```
Table: kpi_history
```

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `kpi_id` | UUID FK → kpis.id | not null |
| `version` | Integer | snapshot version number |
| `change_summary` | String(500) | human-readable description of what changed |
| `snapshot` | JSON | full JSON snapshot of the KPI row at that version |
| `changed_by_id` | UUID FK → users.id | |
| `changed_at` | DateTime UTC | |

---

### Model: `KPITemplate`

A curated library of pre-built KPI templates (seeded by the system).

```
Table: kpi_templates
```

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `name` | String(255) | |
| `description` | Text | |
| `department` | Enum(DepartmentCategory) | |
| `unit` | Enum(MeasurementUnit) | |
| `frequency` | Enum(MeasurementFrequency) | |
| `scoring_direction` | Enum(ScoringDirection) | |
| `suggested_formula` | Text | nullable |
| `tags` | ARRAY(String) | PostgreSQL array of tag names |
| `usage_count` | Integer | default 0, incremented when cloned |
| `is_active` | Boolean | default True |
| `created_at` | DateTime UTC | |

---

### Association Tables

```python
kpi_tag_association = Table(
    "kpi_tag_association",
    Base.metadata,
    Column("kpi_id", UUID, ForeignKey("kpis.id"), primary_key=True),
    Column("tag_id", UUID, ForeignKey("kpi_tags.id"), primary_key=True),
)

kpi_formula_dependency = Table(
    "kpi_formula_dependency",
    Base.metadata,
    Column("parent_kpi_id", UUID, ForeignKey("kpis.id"), primary_key=True),
    Column("dependency_kpi_id", UUID, ForeignKey("kpis.id"), primary_key=True),
)
```

---

## 3. `app/kpis/formula.py`

Build a **safe formula evaluator** — this is critical. Do NOT use Python's `eval()` directly.

### Requirements

- Parse expressions like: `(KPI_REVENUE - KPI_COST) / KPI_REVENUE * 100`
- KPI references are uppercase slugs (matching `kpi.code`)
- Supported operators: `+`, `-`, `*`, `/`, `**` (power), `(`, `)`
- Supported functions: `abs()`, `round()`, `min()`, `max()`, `if(condition, true_val, false_val)`
- Must detect **circular dependencies** — A → B → A should raise an error
- Must validate that all referenced KPI codes exist in the database

### Classes / Functions to generate

```python
class FormulaParser:
    """Tokenises and validates a formula expression without evaluating it."""

    def extract_kpi_references(self, expression: str) -> list[str]:
        """Return list of KPI code strings found in the expression."""
        ...

    def validate_syntax(self, expression: str) -> bool:
        """Return True if syntax is valid, raise FormulaValidationError with detail if not."""
        ...

class FormulaDependencyResolver:
    """Detects circular dependencies in formula chains."""

    def build_dependency_graph(self, kpi_id: UUID, all_kpis: list[KPI]) -> dict:
        """Returns adjacency dict {kpi_id: [dependent_kpi_ids]}."""
        ...

    def detect_cycle(self, graph: dict, start: UUID) -> bool:
        """DFS cycle detection. Raises CircularDependencyError if cycle found."""
        ...

class FormulaEvaluator:
    """Safely evaluates a formula expression given resolved KPI values."""

    SAFE_NAMES = {"abs": abs, "round": round, "min": min, "max": max}

    def evaluate(self, expression: str, kpi_values: dict[str, float]) -> float:
        """
        Replace KPI codes with their numeric values, evaluate safely.
        Raises EvaluationError on division by zero or missing values.
        """
        ...
```

Use Python's `ast` module for safe parsing. Walk the AST to whitelist only `Num`, `BinOp`, `UnaryOp`, `Call`, `Name` node types. Reject anything else.

---

### 3a. Formula Variables (Enhancement 2)

The formula engine has been extended with named variables. Instead of referencing
other KPI codes directly in formulas, you now define `KPIVariable` records that:
1. Give each input a name (e.g. `REVENUE`, `EXPENSES`)
2. Configure where the value comes from (manual / ERP API / database / IoT / webhook)
3. Store every value with a full audit trail in `variable_actuals`

See `app/integrations/` for the adapter system and `ARCHITECTURE.md` for the data flow diagram.

Formula validation now checks:
- Syntax (AST-safe, no eval)
- Variable existence (all referenced names have a KPIVariable defined)
- Circular dependencies (KPI_A → KPI_B → KPI_A is rejected)

---

## 4. `app/kpis/schemas.py`

### Request Schemas

```python
class KPICategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    department: DepartmentCategory
    colour_hex: str = Field(default="#888780", pattern=r"^#[0-9A-Fa-f]{6}$")

class KPICategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    colour_hex: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")

class KPICreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    code: str = Field(min_length=2, max_length=50, pattern=r"^[A-Z0-9_]+$")
    description: str | None = None
    unit: MeasurementUnit
    unit_label: str | None = None
    currency_code: str | None = Field(default=None, min_length=3, max_length=3)
    frequency: MeasurementFrequency
    data_source: DataSourceType = DataSourceType.MANUAL
    formula_expression: str | None = None
    scoring_direction: ScoringDirection = ScoringDirection.HIGHER_IS_BETTER
    min_value: Decimal | None = None
    max_value: Decimal | None = None
    decimal_places: int = Field(default=2, ge=0, le=6)
    category_id: UUID | None = None
    tag_ids: list[UUID] = Field(default_factory=list)
    is_organisation_wide: bool = False

    @model_validator(mode="after")
    def validate_formula_fields(self):
        if self.data_source == DataSourceType.FORMULA and not self.formula_expression:
            raise ValueError("formula_expression is required when data_source is FORMULA")
        if self.data_source != DataSourceType.FORMULA and self.formula_expression:
            raise ValueError("formula_expression must be null when data_source is not FORMULA")
        return self

class KPIUpdate(BaseModel):
    # All fields optional
    name: str | None = None
    description: str | None = None
    formula_expression: str | None = None
    scoring_direction: ScoringDirection | None = None
    min_value: Decimal | None = None
    max_value: Decimal | None = None
    decimal_places: int | None = None
    category_id: UUID | None = None
    tag_ids: list[UUID] | None = None
    change_summary: str | None = Field(default=None, max_length=500,
        description="Required when modifying formula_expression")

class KPIStatusUpdate(BaseModel):
    status: KPIStatus
    reason: str | None = Field(default=None, max_length=500)

class KPICloneFromTemplate(BaseModel):
    template_id: UUID
    name: str | None = None     # override template name
    code: str = Field(pattern=r"^[A-Z0-9_]+$")
    category_id: UUID | None = None
```

### Response Schemas

```python
class KPICategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    description: str | None
    department: DepartmentCategory
    colour_hex: str
    organisation_id: UUID | None
    created_at: datetime

class KPITagRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str

class KPIRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    code: str
    description: str | None
    unit: MeasurementUnit
    unit_label: str | None
    currency_code: str | None
    frequency: MeasurementFrequency
    data_source: DataSourceType
    formula_expression: str | None
    scoring_direction: ScoringDirection
    min_value: Decimal | None
    max_value: Decimal | None
    decimal_places: int
    status: KPIStatus
    is_template: bool
    is_organisation_wide: bool
    version: int
    category: KPICategoryRead | None
    tags: list[KPITagRead]
    organisation_id: UUID
    created_by_id: UUID
    approved_by_id: UUID | None
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime

class KPIReadWithDependencies(KPIRead):
    formula_dependencies: list[KPIRead]   # resolved dependency KPIs

class KPIHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    version: int
    change_summary: str | None
    snapshot: dict
    changed_by_id: UUID
    changed_at: datetime

class KPITemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    description: str | None
    department: DepartmentCategory
    unit: MeasurementUnit
    frequency: MeasurementFrequency
    scoring_direction: ScoringDirection
    suggested_formula: str | None
    tags: list[str]
    usage_count: int

class PaginatedKPIs(BaseModel):
    items: list[KPIRead]
    total: int
    page: int
    size: int
    pages: int
```

---

## 5. `app/kpis/service.py`

Generate `KPIService` class with **all methods async**:

### Category Methods
```python
async def create_category(db, org_id, user_id, data: KPICategoryCreate) -> KPICategory
async def list_categories(db, org_id) -> list[KPICategory]
async def update_category(db, category_id, org_id, data: KPICategoryUpdate) -> KPICategory
async def delete_category(db, category_id, org_id) -> None  # soft: only if no KPIs attached
```

### Tag Methods
```python
async def get_or_create_tag(db, name: str, org_id: UUID) -> KPITag
async def list_tags(db, org_id) -> list[KPITag]
```

### KPI CRUD
```python
async def create_kpi(db, org_id, user_id, data: KPICreate) -> KPI:
    # 1. Validate code uniqueness within org
    # 2. If data_source=FORMULA: validate syntax via FormulaParser
    # 3. If formula: resolve + validate KPI code references exist in org
    # 4. If formula: check no circular dependencies
    # 5. Create KPI, attach tags, save formula_dependencies
    # 6. Create KPIHistory entry (version=1, change_summary="Initial creation")
    ...

async def get_kpi_by_id(db, kpi_id, org_id) -> KPI     # raises NotFoundException
async def get_kpi_by_code(db, code, org_id) -> KPI | None

async def list_kpis(
    db, org_id, page, size,
    status: KPIStatus | None,
    category_id: UUID | None,
    department: DepartmentCategory | None,
    data_source: DataSourceType | None,
    tag_ids: list[UUID] | None,
    search: str | None,           # full-text search on name + description
    created_by_id: UUID | None,
) -> PaginatedKPIs

async def update_kpi(db, kpi_id, org_id, user_id, data: KPIUpdate) -> KPI:
    # 1. Load existing KPI
    # 2. If formula changed: re-validate and re-resolve dependencies
    # 3. Increment version
    # 4. Snapshot old state → KPIHistory
    # 5. Apply changes + save
    ...

async def update_kpi_status(db, kpi_id, org_id, user_id, data: KPIStatusUpdate) -> KPI:
    # Enforce valid transitions:
    # DRAFT → PENDING_APPROVAL or ACTIVE (hr_admin can skip approval)
    # PENDING_APPROVAL → ACTIVE (requires hr_admin) or DRAFT (reject)
    # ACTIVE → DEPRECATED
    # DEPRECATED → ARCHIVED
    # Any → DRAFT only by hr_admin
    ...

async def get_kpi_history(db, kpi_id, org_id) -> list[KPIHistory]
```

### Template Methods
```python
async def list_templates(db, department: DepartmentCategory | None, search: str | None) -> list[KPITemplate]
async def clone_from_template(db, org_id, user_id, data: KPICloneFromTemplate) -> KPI:
    # Copy template fields → KPICreate, increment template.usage_count
    ...
async def promote_to_template(db, kpi_id, org_id) -> KPI  # hr_admin only, sets is_template=True
```

### Formula Utility
```python
async def evaluate_formula_for_kpi(db, kpi_id, org_id, period_date: date) -> Decimal:
    # Recursively resolve dependencies, evaluate formula, return calculated value
    ...

async def validate_formula_expression(db, org_id, expression: str) -> dict:
    # Returns {"valid": bool, "referenced_codes": list[str], "errors": list[str]}
    ...
```

---

## 6. `app/kpis/router.py`

Generate all endpoints with full docstrings, correct status codes, and role-based access:

### Category Endpoints
```
GET    /kpis/categories/                → list categories (all roles)
POST   /kpis/categories/               → create category (hr_admin, manager)
PUT    /kpis/categories/{id}           → update (hr_admin)
DELETE /kpis/categories/{id}           → delete if empty (hr_admin)
```

### Tag Endpoints
```
GET    /kpis/tags/                     → list org tags (all roles)
```

### KPI Endpoints
```
GET    /kpis/                          → list KPIs, paginated + filtered
POST   /kpis/                          → create KPI (hr_admin, manager)
GET    /kpis/templates/                → list system templates
POST   /kpis/templates/clone/          → clone template to org KPI
GET    /kpis/{kpi_id}                  → get single KPI with dependencies
PUT    /kpis/{kpi_id}                  → update KPI definition
PATCH  /kpis/{kpi_id}/status          → update status (approval workflow)
GET    /kpis/{kpi_id}/history          → get version history
POST   /kpis/{kpi_id}/promote-template → mark as org template (hr_admin)
POST   /kpis/validate-formula          → validate formula without saving
```

### Query Parameters for `GET /kpis/`
```python
status: KPIStatus | None = None
category_id: UUID | None = None
department: DepartmentCategory | None = None
data_source: DataSourceType | None = None
tag_ids: list[UUID] | None = Query(default=None)
search: str | None = None
page: int = 1
size: int = Query(default=20, le=100)
```

---

## 7. Alembic Migration

After generating all models, create the initial Alembic migration:

```bash
alembic revision --autogenerate -m "create_kpi_tables"
```

Verify the generated migration includes:
- `kpi_categories` table
- `kpi_tags` table
- `kpis` table with all columns and enum types
- `kpi_history` table
- `kpi_templates` table
- `kpi_tag_association` join table
- `kpi_formula_dependency` join table
- All foreign key constraints
- All indexes

---

## 8. Seed Data Script — `app/kpis/seeds.py`

Create `async def seed_kpi_templates(db: AsyncSession)` that inserts these templates:

| Department | Name | Unit | Frequency | Direction |
|---|---|---|---|---|
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

Call this from `app/main.py` startup only when `settings.DEBUG=True` and templates table is empty.

---

## Tests to Write — `tests/test_kpis.py`

```python
# Test cases to cover:
test_create_kpi_manual()                      # success
test_create_kpi_duplicate_code_fails()        # 409
test_create_kpi_formula_valid()               # success, dependencies resolved
test_create_kpi_formula_invalid_syntax()      # 422
test_create_kpi_formula_circular_dep_fails()  # 422
test_create_kpi_formula_missing_ref_fails()   # 422
test_kpi_status_workflow_draft_to_active()    # success
test_kpi_status_invalid_transition_fails()    # 400
test_list_kpis_pagination()
test_list_kpis_filter_by_status()
test_list_kpis_filter_by_department()
test_update_kpi_increments_version()
test_update_kpi_saves_history()
test_clone_from_template()
test_validate_formula_endpoint()
```

---

## What to Build Next (Do NOT build yet)

- Part 3: Target setting (cascading, milestones, weights) + Actuals data entry