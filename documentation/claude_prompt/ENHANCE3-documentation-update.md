# Copilot Prompt — Enhancement 3: Update All Documentation & Diagrams
> **Model**: Claude Sonnet 4.6 | **Workspace**: @workspace
> **Run after**: Enhancements 1 and 2 are fully implemented and tests pass

---

## Context

Enhancements 1 and 2 have added significant new capabilities to the PMS KPI system:
- Per-KPI scoring configuration with 3-level precedence
- Named formula variables with dynamic external data binding
- A complete adapter pattern for ERP/HRMS/IoT integration

This prompt updates **all documentation, diagrams, and code-level comments** to reflect the new design, and adds a master `ARCHITECTURE.md` that future developers (and Copilot) can use as ground truth.

---

## Task 1: Create `ARCHITECTURE.md` in workspace root

Create a new file at `ARCHITECTURE.md` (repo root, alongside `README.md`).

This file is the **single source of truth** for the system design. It must include:

### 1.1 System Overview Section

```markdown
# PMS KPI Module — Architecture Reference

## System Purpose
A multi-tenant Performance Management System (PMS) focused on the KPI lifecycle:
Define KPIs → Set targets → Collect actuals → Score → Calibrate → Report.

## Stack
| Layer       | Technology          | Version |
|-------------|---------------------|---------|
| Backend     | FastAPI             | 0.111+  |
| ORM         | SQLAlchemy (async)  | 2.x     |
| DB          | PostgreSQL          | 15+     |
| Cache/Jobs  | Redis + APScheduler | 7+      |
| Frontend    | React + TypeScript  | 18 / 5  |
| State       | Redux Toolkit       | 2.x     |
| UI          | shadcn/ui           | latest  |
```

### 1.2 Module Map Section

Include this ASCII diagram in `ARCHITECTURE.md`:

```
app/
├── auth/              JWT (access + refresh), bcrypt passwords
├── users/             User CRUD, RBAC, org hierarchy
├── organisations/     Org management, settings
├── kpis/              KPI definitions, formula engine, templates
│   └── formula.py     ← FormulaParser + FormulaEvaluator (AST-safe)
├── review_cycles/     Cycle management (DRAFT→ACTIVE→CLOSED→ARCHIVED)
├── targets/           Target setting, cascading, milestones, weights
├── actuals/           Actual entry, evidence, approval, time-series
├── scoring/           Scoring engine, calibration, composite scores
│   ├── calculator.py  ← Pure scoring functions (no DB)
│   └── kpi_scoring_*  ← Per-KPI scoring configs (Enhancement 1)
├── integrations/      ← NEW (Enhancement 2)
│   ├── models.py      KPIVariable, VariableActual
│   ├── adapters/      REST API, Database, IoT, Webhook adapters
│   ├── adapter_registry.py
│   └── data_sync_service.py
├── notifications/     In-app + email alerts
├── tasks/             APScheduler background jobs
└── dashboards/        Read-only aggregation endpoints
```

### 1.3 Data Flow Diagrams Section

Include all three of these diagrams verbatim:

**Diagram 1: KPI Lifecycle**
```
┌──────────┐   submit    ┌────────────────────┐   approve   ┌────────┐
│  DRAFT   │───────────►│  PENDING APPROVAL  │───────────►│ ACTIVE │
└──────────┘            └────────────────────┘             └────┬───┘
     ▲                           │ reject                        │
     └───────────────────────────┘                        ┌──────▼──────┐
                                                           │ DEPRECATED  │
                                                           └──────┬──────┘
                                                                  │
                                                           ┌──────▼──────┐
                                                           │  ARCHIVED   │
                                                           └─────────────┘
Only ACTIVE KPIs can be assigned as targets.
Historical data preserved when deprecated.
```

**Diagram 2: Scoring Config Precedence (Enhancement 1)**
```
┌─────────────────────────────────────────────────────────┐
│  SCORING CONFIG PRECEDENCE (highest → lowest)            │
│                                                          │
│  Level 3 (HIGHEST):  KPITarget.scoring_config_id        │
│    "This specific employee's target for this KPI        │
│     in this cycle uses Safety Compliance thresholds"    │
│                           │                             │
│  Level 2:  KPI.scoring_config_id                        │
│    "All assignments of Revenue Growth KPI               │
│     default to Sales Org thresholds"                    │
│                           │                             │
│  Level 1 (LOWEST):  Cycle ScoreConfig                   │
│    "Org-wide default: 120/100/80/60/0"                  │
│                                                          │
│  resolve_scoring_config(target, cycle_config) → dict    │
│  determine_rating_with_config(achievement%, config)     │
└─────────────────────────────────────────────────────────┘
```

**Diagram 3: Formula Variable Data Flow (Enhancement 2)**
```
KPI formula: "(REVENUE - EXPENSES) / REVENUE * 100"
                        │
          ┌─────────────▼─────────────┐
          │    kpi_variables table     │
          │  REVENUE  → REST API (ERP)│
          │  EXPENSES → Manual entry  │
          └─────────────┬─────────────┘
                        │
          ┌─────────────▼─────────────┐
          │    DataSyncService         │
          │  1. Auto-sync REVENUE     │
          │  2. Collect EXPENSES      │
          │  3. Store variable_actuals│
          └─────────────┬─────────────┘
                        │
          ┌─────────────▼─────────────┐
          │    FormulaEvaluator        │
          │  AST-safe evaluation       │
          │  → 29.17%                  │
          └─────────────┬─────────────┘
                        │
          ┌─────────────▼─────────────┐
          │    kpi_actuals table       │
          │  actual_value: 29.17       │
          │  entry_source: auto_formula│
          └───────────────────────────┘
```

### 1.4 Role Permission Matrix Section

```markdown
| Capability                    | hr_admin | executive | manager | employee |
|-------------------------------|----------|-----------|---------|----------|
| Create/edit KPI definitions   | ✅       | ❌        | ✅ dept | ❌       |
| Manage KPI variables          | ✅       | ❌        | ✅      | ❌       |
| Configure adapter source      | ✅       | ❌        | ❌      | ❌       |
| Create scoring configs        | ✅       | ❌        | ❌      | ❌       |
| Assign scoring config to KPI  | ✅       | ❌        | ❌      | ❌       |
| Assign scoring config to target| ✅      | ❌        | ✅      | ❌       |
| Set targets                   | ✅       | ✅ org    | ✅ team | ❌       |
| Submit actuals (manual var)   | ✅       | ❌        | ✅      | ✅       |
| Trigger formula computation   | ✅       | ❌        | ❌      | ❌       |
| Run scoring engine            | ✅       | ❌        | ❌      | ❌       |
| Adjust scores                 | ✅       | ❌        | ✅ team | ❌       |
| Run calibration               | ✅       | ❌        | ❌      | ❌       |
| View org-level scores         | ✅       | ✅        | ❌      | ❌       |
```

### 1.5 Database Schema Section

Include an ERD diagram in ASCII:

```
organisations ──┐
                │
users ──────────┤ (FK: organisation_id, manager_id self-ref)
                │
kpi_categories ─┤ (FK: organisation_id)
                │
kpi_scoring_configs ─┐ (FK: organisation_id)  ← Enhancement 1
                     │
kpis ────────────────┤ (FK: organisation_id, category_id,
                     │      scoring_config_id → kpi_scoring_configs)
                     │
kpi_variables ───────┤ (FK: kpi_id, organisation_id)  ← Enhancement 2
                     │
review_cycles ───────┤ (FK: organisation_id)
                     │
kpi_targets ─────────┤ (FK: kpi_id, review_cycle_id, assignee_user_id,
                     │      scoring_config_id → kpi_scoring_configs)
                     │
target_milestones ───┤ (FK: target_id)
                     │
kpi_actuals ─────────┤ (FK: target_id, kpi_id, submitted_by_id)
                     │
variable_actuals ────┘ (FK: variable_id, kpi_id)  ← Enhancement 2
                     │
performance_scores ──┤ (FK: target_id, user_id, kpi_id, review_cycle_id)
                     │
composite_scores ────┤ (FK: user_id, review_cycle_id)
                     │
notifications ───────┤ (FK: recipient_id, organisation_id)
                     │
calibration_sessions ┘ (FK: review_cycle_id, organisation_id)
```

### 1.6 Scoring Formula Reference Section

```markdown
## Scoring Formulas

### Achievement Percentage
Higher-is-better: `(actual / target) × 100`
Lower-is-better:  `(target / actual) × 100`
Below minimum:    `0.0` (hard floor)
Cap:              `min(result, achievement_cap)`  [default: 200%]

### Weighted Score
`weighted_score = achievement_pct × (kpi_weight / 100)`

### Composite Score
`composite = Σ(weighted_scores) / Σ(weights) × 100`

### Default Rating Thresholds (Standard preset)
| Achievement % | Rating                  |
|---------------|-------------------------|
| ≥ 120%        | Exceptional             |
| ≥ 100%        | Exceeds Expectations    |
| ≥ 80%         | Meets Expectations      |
| ≥ 60%         | Partially Meets         |
| < 60%         | Does Not Meet           |

Thresholds are configurable per KPI and per target via `kpi_scoring_configs`.
```

---

## Task 2: Update `README.md`

Update (not replace) the existing README to add:

### 2.1 Quick Start section

```markdown
## Quick Start

### Prerequisites
- Python 3.11+, PostgreSQL 15+, Redis 7+, Node 18+

### Backend Setup
\`\`\`bash
cd pms-backend
cp .env.example .env       # edit DATABASE_URL, JWT_SECRET_KEY
docker-compose up -d db redis
alembic upgrade head
uvicorn app.main:app --reload
\`\`\`

### Frontend Setup  
\`\`\`bash
cd pms-frontend
npm install
npm run dev
\`\`\`

### First Login
- Default HR Admin: admin@company.com / changeme (set in seed data)
- Change password on first login
- Create your org, KPI library, and first review cycle
```

### 2.2 Feature Overview section

```markdown
## Features

### Core KPI Module
- **KPI Library** — Define KPIs with 6 measurement units, 6 frequencies, formula engine
- **Formula Variables** — Named variables in formulas, bound to ERP/HRMS/IoT or manual entry
- **External Data Adapters** — REST API, SQL database, InfluxDB, webhook push, CSV upload
- **Review Cycles** — Annual/quarterly/custom cycles with target-setting and scoring phases
- **Cascading Targets** — Org → Dept → Team → Individual with 3 distribution strategies
- **Per-KPI Scoring** — 5 built-in presets (Standard/Strict/Lenient/Binary/Sales) + custom
- **Scoring Engine** — Achievement%, weighted scores, composite rating, calibration sessions
- **Role-Based Dashboards** — Employee / Manager / Org views with real-time KPI heatmap
- **Notifications** — At-risk alerts, actuals reminders, period-close warnings
```

### 2.3 Environment Variables section

```markdown
## Environment Variables (.env)

\`\`\`env
# Database
DATABASE_URL=postgresql+asyncpg://pms_user:pms_pass@localhost:5432/pms_db

# Redis
REDIS_URL=redis://localhost:6379/0

# JWT
JWT_SECRET_KEY=your-very-long-random-string-here
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7

# CORS
CORS_ORIGINS=["http://localhost:3000","http://localhost:5173"]

# Integration secrets (referenced as {SECRET:KEY_NAME} in adapter configs)
# PMS_SECRET_ERP_API_TOKEN=your-erp-token
# PMS_SECRET_SALES_DB_CONN=postgresql://user:pass@erp-db:5432/sales
# PMS_SECRET_HRMS_KEY=your-hrms-api-key

# Debug (disable in production)
DEBUG=false
\`\`\`
```

---

## Task 3: Update Backend Part Files

### 3.1 Update `PART2-kpi-core.md`

Add a new section **after** Section 3 (formula.py):

```markdown
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
```

### 3.2 Update `PART4-scoring-dashboards.md`

Add a new section **before** the router section:

```markdown
### Per-KPI Scoring Configuration (Enhancement 1)

The scoring engine now supports 3-level precedence for thresholds:
1. **Target-level override** — highest precedence, set per employee assignment
2. **KPI-level default** — applies whenever the KPI is used
3. **Cycle-level default** — org-wide fallback (existing ScoreConfig)

See `app/scoring/kpi_scoring_model.py` and `app/scoring/calculator.py`.

Built-in presets:
| Preset   | Exceptional | Exceeds | Meets | Partial |
|----------|------------|---------|-------|---------|
| Standard | ≥120%      | ≥100%   | ≥80%  | ≥60%    |
| Strict   | ≥130%      | ≥110%   | ≥95%  | ≥80%    |
| Lenient  | ≥110%      | ≥90%    | ≥70%  | ≥50%    |
| Binary   | ≥100%      | ≥100%   | ≥90%  | ≥0%     |
| Sales    | ≥120%      | ≥100%   | ≥85%  | ≥70%    |
```

---

## Task 4: Update Frontend Documentation

### 4.1 Update `FRONTEND-pms-kpi-ui.md` — Section 3 (Types)

Add to the TypeScript types section:

```markdown
### New Types (Enhancements 1 & 2)

- `src/types/scoring-config.types.ts` — KPIScoringConfig, ScoringPreset, EffectiveScoringConfig
- `src/types/integration.types.ts` — KPIVariable, VariableWithCurrentValue, AdapterSchema

### New RTK Query Endpoints

- `scoringConfigEndpoints.ts` — CRUD for scoring configs, preview
- `variableEndpoints.ts` — CRUD for KPI variables, sync triggers
- `integrationEndpoints.ts` — adapter list, test connection, webhook push

### New Components

- `ScoringConfigManager.tsx` — list/create/edit scoring configs + live preview slider
- `KPIVariableManager.tsx` — manage variables per KPI + adapter config form
- `AdapterConfigForm.tsx` — dynamic form rendered from adapter JSON schema
- Updated `ActualEntryPage.tsx` — shows variable inputs for formula KPIs
- Updated `KPIBuilderForm.tsx` — Step 3 extended with variable manager
- Updated `KPIScorecardTable.tsx` — rating tooltip shows which config was used
```

---

## Task 5: Add Code Comments Throughout

### 5.1 `app/scoring/calculator.py` — add module docstring

```python
"""
scoring/calculator.py — Pure scoring calculation functions.

Design principles:
  - No database calls — all inputs passed as arguments
  - All functions are pure (same input always → same output)
  - Decimal arithmetic throughout — never float for money/percentages
  - Config-aware since Enhancement 1: resolve_scoring_config() handles 3-level precedence

Key functions:
  compute_achievement_percentage(actual, target, direction, minimum, cap) → Decimal
  compute_weighted_score(achievement_pct, weight) → Decimal
  compute_composite_score(scores) → Decimal
  resolve_scoring_config(target, cycle_config) → dict   ← Enhancement 1
  determine_rating_with_config(achievement_pct, config) → (RatingLabel, source_str)

Usage from ScoringEngine:
  config = resolve_scoring_config(target, cycle_config)
  pct = compute_achievement_percentage(actual, target.target_value, kpi.scoring_direction)
  rating, source = determine_rating_with_config(pct, config)
"""
```

### 5.2 `app/kpis/formula.py` — add module docstring

```python
"""
kpis/formula.py — Safe formula parser and evaluator.

Security model:
  Uses Python ast.parse() in 'eval' mode, then walks the AST with a whitelist visitor.
  Only these node types are allowed:
    Numbers, variable names (uppercase), arithmetic operators (+,-,*,/,**,%)
    Function calls: abs(), round(), min(), max(), if_func()
    Comparisons: <, <=, >, >=, ==, !=
  Anything else (imports, attribute access, subscripts, etc.) raises FormulaValidationError.
  eval() is NEVER called.

Formula syntax:
  Variables:  Uppercase identifiers — REVENUE, EXPENSES, HEADCOUNT
  Arithmetic: Standard Python operators
  Functions:  ABS(x), ROUND(x, n), MIN(a,b), MAX(a,b), IF(condition, true_val, false_val)
  Constants:  Numeric literals only (100, 0.5, etc.)

Examples:
  (REVENUE - EXPENSES) / REVENUE * 100
  IF(DEFECTS > 0, DEFECTS / OUTPUT * 100, 0)
  ABS(CURRENT_PERIOD - PRIOR_PERIOD) / PRIOR_PERIOD * 100
  MIN(ACTUAL, TARGET) / TARGET * 100

Enhancement 2: FormulaParser.extract_variable_names() returns the list of variable
names that must be resolved via DataSyncService before evaluation.
"""
```

### 5.3 `app/integrations/adapters/base.py` — add module docstring

```python
"""
integrations/adapters/base.py — Base class for all data source adapters.

Adapter contract:
  1. fetch(config, period_date, variable) → AdapterResult
     - Must be async
     - Must handle its own errors (return AdapterResult(success=False) on failure)
     - Must be idempotent (calling twice for same period returns same value)
     - Must respect timeout settings from config
     - Must NOT log resolved secrets

  2. validate_config(config) → list[str]
     - Called before saving a KPIVariable
     - Returns empty list if valid, list of error messages if invalid
     - Must verify {SECRET:KEY} references are used for credentials

  3. get_config_schema() → dict
     - Returns JSON Schema used by frontend AdapterConfigForm
     - Drives dynamic form rendering — no hardcoded forms per adapter type

Adding new adapters:
  1. Create class inheriting BaseAdapter in app/integrations/adapters/
  2. Implement all three methods
  3. Register in adapter_registry.py:
       AdapterRegistry.register("my_adapter", MyAdapter)
  No other changes needed — the registry handles discovery.

Built-in adapters:
  rest_api:         HTTP GET/POST to any JSON endpoint
  database:         Direct SQL SELECT query (PostgreSQL, MySQL, MSSQL)
  influxdb:         InfluxDB Flux query for IoT/time-series
  webhook_receive:  External system pushes data to PMS
  kpi_actual:       Pull latest actual from another KPI in same org
  csv_upload:       Batch upload via CSV file
"""
```

---

## Task 6: Update Mock Data Files

### 6.1 Add to `src/mocks/kpis.json`

Update the "Monthly Revenue Growth" KPI entry to include variables:

```json
{
  "id": "kpi-001",
  "name": "Monthly Revenue Growth",
  "code": "SALES_REVENUE_GROWTH",
  "data_source": "formula",
  "formula_expression": "(REVENUE - PRIOR_REVENUE) / PRIOR_REVENUE * 100",
  "variables": [
    {
      "id": "var-001",
      "variable_name": "REVENUE",
      "display_label": "Current Month Total Revenue (MYR)",
      "data_type": "currency",
      "source_type": "rest_api",
      "is_required": true,
      "auto_sync_enabled": true,
      "last_sync_status": "success",
      "last_synced_at": "2025-06-01T01:30:00Z",
      "source_config": {
        "adapter": "rest_api",
        "url": "https://erp.company.com/api/v1/revenue/monthly?month={period.iso}",
        "response_path": "data.total_revenue"
      }
    },
    {
      "id": "var-002",
      "variable_name": "PRIOR_REVENUE",
      "display_label": "Prior Month Total Revenue (MYR)",
      "data_type": "currency",
      "source_type": "manual",
      "is_required": true,
      "auto_sync_enabled": false,
      "last_sync_status": "never_synced"
    }
  ],
  "scoring_config": {
    "id": "sc-sales",
    "name": "Sales Org",
    "preset": "sales",
    "exceptional_min": 120,
    "exceeds_min": 100,
    "meets_min": 85,
    "partially_meets_min": 70,
    "summary": "Exceptional:≥120% | Exceeds:≥100% | Meets:≥85% | Partial:≥70%"
  }
}
```

### 6.2 Add `src/mocks/scoring_configs.json`

```json
[
  {
    "id": "sc-system-standard",
    "name": "Standard",
    "preset": "standard",
    "exceptional_min": 120, "exceeds_min": 100, "meets_min": 80, "partially_meets_min": 60,
    "does_not_meet_min": 0, "achievement_cap": 200,
    "is_system_preset": true,
    "summary": "Exceptional:≥120% | Exceeds:≥100% | Meets:≥80% | Partial:≥60%"
  },
  {
    "id": "sc-system-strict",
    "name": "Strict",
    "preset": "strict",
    "exceptional_min": 130, "exceeds_min": 110, "meets_min": 95, "partially_meets_min": 80,
    "does_not_meet_min": 0, "achievement_cap": 200,
    "is_system_preset": true,
    "summary": "Exceptional:≥130% | Exceeds:≥110% | Meets:≥95% | Partial:≥80%"
  },
  {
    "id": "sc-system-lenient",
    "name": "Lenient",
    "preset": "lenient",
    "exceptional_min": 110, "exceeds_min": 90, "meets_min": 70, "partially_meets_min": 50,
    "does_not_meet_min": 0, "achievement_cap": 200,
    "is_system_preset": true,
    "summary": "Exceptional:≥110% | Exceeds:≥90% | Meets:≥70% | Partial:≥50%"
  },
  {
    "id": "sc-system-binary",
    "name": "Binary (Pass/Fail)",
    "preset": "binary",
    "exceptional_min": 100, "exceeds_min": 100, "meets_min": 90, "partially_meets_min": 0,
    "does_not_meet_min": 0, "achievement_cap": 200,
    "is_system_preset": true,
    "summary": "Meets:≥90% | Does Not Meet:<90% (no partial rating)"
  },
  {
    "id": "sc-system-sales",
    "name": "Sales Org",
    "preset": "sales",
    "exceptional_min": 120, "exceeds_min": 100, "meets_min": 85, "partially_meets_min": 70,
    "does_not_meet_min": 0, "achievement_cap": 200,
    "is_system_preset": true,
    "summary": "Exceptional:≥120% | Exceeds:≥100% | Meets:≥85% | Partial:≥70%"
  },
  {
    "id": "sc-custom-safety",
    "name": "Safety Compliance",
    "preset": "custom",
    "exceptional_min": 100, "exceeds_min": 99, "meets_min": 98, "partially_meets_min": 95,
    "does_not_meet_min": 0, "achievement_cap": 100,
    "is_system_preset": false,
    "organisation_id": "org-001",
    "summary": "Meets:≥98% | Partial:≥95% | DNM:<95% (near-zero tolerance)"
  }
]
```

---

## Task 7: Final Integration Verification Checklist

After completing all tasks, verify:

**Backend:**
- [ ] `alembic upgrade head` runs cleanly — no conflicts between migrations
- [ ] `pytest tests/ -v` — all tests pass, no failures
- [ ] `GET /docs` — OpenAPI shows all new endpoints grouped under `/scoring/configs`, `/kpis/{id}/variables`, `/integrations/`
- [ ] Scoring engine uses `resolve_scoring_config()` — not hardcoded thresholds
- [ ] `FormulaEvaluator` has its own test file with ≥ 20 test cases
- [ ] All adapters have `validate_config()` called before any `KPIVariable` is saved
- [ ] No raw credentials stored in `source_config` — all use `{SECRET:KEY_NAME}`
- [ ] `seed_system_presets()` is called on startup and is idempotent
- [ ] `ARCHITECTURE.md` exists at repo root

**Frontend:**
- [ ] KPI builder Step 3 shows variable manager for formula KPIs
- [ ] KPI builder Step 4 shows scoring config dropdown with live preview
- [ ] Actuals entry page shows variable inputs with sync status for formula KPIs
- [ ] Live formula preview updates as user types manual variables
- [ ] Scorecard rating tooltip shows which config level was used
- [ ] Scoring config manager has List + Builder + Preview tabs
- [ ] `src/mocks/scoring_configs.json` exists with 6 configs
- [ ] TypeScript: `npm run build` produces zero errors
- [ ] All new RTK Query hooks handle loading / error / empty states