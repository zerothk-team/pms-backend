# 07 — Process Flow & Data Flow Diagrams

← [Back to Index](index.md)

---

> All diagrams use [Mermaid](https://mermaid.js.org/) syntax. They render natively in GitHub, GitLab, Notion, Obsidian, and VS Code with the Markdown Preview Mermaid Support extension.

---

## 1. System Architecture

High-level component diagram showing where the KPI module sits within the full system.

```mermaid
graph TB
    subgraph Client["Client Layer"]
        WEB[Web App / curl]
    end

    subgraph API["FastAPI Application (app/)"]
        AUTH[auth router\n/api/v1/auth]
        USERS[users router\n/api/v1/users]
        ORGS[organisations router\n/api/v1/organisations]
        KPIS[kpis router\n/api/v1/kpis]
        TARGETS[targets router\n/api/v1/targets]
        ACTUALS[actuals router\n/api/v1/actuals]
        SCORING[scoring router\n/api/v1/scoring]
    end

    subgraph KPIModule["KPI Module (app/kpis/)"]
        ROUTER[router.py\n15 endpoints]
        SERVICE[service.py\nBusiness logic]
        FORMULA[formula.py\nFormula engine]
        MODELS[models.py\nORM models]
        SCHEMAS[schemas.py\nPydantic v2]
        ENUMS[enums.py\n6 enum types]
        SEEDS[seeds.py\n13 system templates]
    end

    subgraph DB["PostgreSQL Database"]
        KPI_TABLES[(kpis\nkpi_categories\nkpi_tags\nkpi_history\nkpi_templates\njoin tables)]
        OTHER_TABLES[(users\norganisations\ntargets\nactuals)]
    end

    WEB -->|JWT + JSON| KPIS
    KPIS --> ROUTER
    ROUTER --> SERVICE
    SERVICE --> FORMULA
    SERVICE --> MODELS
    SERVICE --> SCHEMAS
    MODELS --> KPI_TABLES
    KPIS -.->|depends on| AUTH
    TARGETS -.->|references| KPIS
    ACTUALS -.->|references| KPIS
    SCORING -.->|reads| KPIS
    SEEDS -->|seeded on startup| KPI_TABLES
```

---

## 2. HTTP Request Lifecycle

Sequence diagram tracing a single `POST /kpis/` request from client to database and back.

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant MW as Middleware\n(CORS, Logging)
    participant RT as KPI Router
    participant DEP as Dependencies\n(JWT Auth, Role Check)
    participant SVC as KPIService
    participant FE as FormulaEngine
    participant DB as PostgreSQL

    C->>MW: POST /api/v1/kpis/ + JWT
    MW->>RT: Forward request
    RT->>DEP: Resolve get_current_active_user
    DEP->>DB: SELECT user WHERE token claims match
    DB-->>DEP: User row
    DEP->>RT: User (role=manager)
    RT->>DEP: require_roles("hr_admin","manager")
    DEP->>RT: Authorised ✓
    RT->>SVC: create_kpi(db, org_id, user_id, KPICreate)
    SVC->>DB: SELECT kpi WHERE code=GROSS_PROFIT_MARGIN AND org_id=...
    DB-->>SVC: None (not found = OK)
    SVC->>DB: SELECT kpi_category WHERE id=... AND org_id=...
    DB-->>SVC: KPICategory row
    alt data_source == formula
        SVC->>FE: validate_and_resolve(formula, org_id)
        FE->>DB: SELECT kpis WHERE org_id=... AND data_source=formula
        DB-->>FE: All formula KPIs
        FE->>FE: Build adjacency graph\nRun DFS cycle check
        FE-->>SVC: [REVENUE, COST] dependency codes
    end
    SVC->>DB: INSERT INTO kpis ...
    SVC->>DB: INSERT INTO kpi_history (version=1, "Initial creation")
    SVC->>DB: INSERT INTO kpi_formula_dependency (MARGIN→REVENUE, MARGIN→COST)
    DB-->>SVC: KPI row (with relationships loaded)
    SVC-->>RT: KPI ORM object
    RT-->>MW: KPIRead JSON (201)
    MW-->>C: 201 Created + body
```

---

## 3. Formula Validation Flow

Detailed flowchart of what happens when a formula expression is processed.

```mermaid
flowchart TD
    A([Input: formula_expression string]) --> B[Preprocess:\nReplace 'if(' with '_if_(']
    B --> C{ast.parse\nmode='eval'}
    C -->|SyntaxError| D[/"FormulaValidationError:\nInvalid syntax: ..."/]
    C -->|Success| E[Walk all AST nodes]
    E --> F{Node type in\n_SAFE_NODES?}
    F -->|No| G[/"FormulaValidationError:\nUnsafe node: ast.XXX"/]
    F -->|Yes| H{More nodes?}
    H -->|Yes| E
    H -->|No| I[Extract ast.Name nodes\nexcluding _SAFE_BUILTINS]
    I --> J[referenced_codes list]
    J --> K{Validate endpoint\nor KPI creation?}
    K -->|validate-formula endpoint| L[Query DB for each code\nin organisation]
    L --> M{All codes found?}
    M -->|No| N[/"valid=false,\nerror=KPI code not found"/]
    M -->|Yes| O[/"valid=true,\nreferenced_codes=[...]"/]
    K -->|KPI creation| P[Load all formula KPIs\nin org from DB]
    P --> Q[Build adjacency map\nfor all existing KPIs]
    Q --> R[Create _FakeKPI\nwith new KPI's code and deps]
    R --> S[Add _FakeKPI to adjacency map]
    S --> T{DFS cycle detection\nfrom new KPI's code}
    T -->|Cycle found| U[/"CircularDependencyError:\n... → ... → ..."/]
    T -->|No cycle| V{All dep codes\nexist in org?}
    V -->|Missing code| W[/NotFoundException: KPI code not found/]
    V -->|All found| X[Write kpi_formula_dependency rows\nto database]
    X --> Y([Formula validated and persisted])
```

---

## 4. KPI Status State Machine

```mermaid
stateDiagram-v2
    [*] --> draft : POST /kpis/ (created)

    draft --> pending_approval : Any user\nPATCH status
    draft --> active : hr_admin only\nPATCH status (fast-track)

    pending_approval --> active : hr_admin only\nPATCH status (approve)
    pending_approval --> draft : Any user\nPATCH status (reject/revise)

    active --> deprecated : Any user\nPATCH status

    deprecated --> archived : Any user\nPATCH status

    archived --> [*] : Terminal state\n(no transitions)

    note right of active
        Sets: approved_by_id
        Sets: approved_at
    end note

    note right of deprecated
        Sets: deprecated_at
    end note

    note left of draft
        hr_admin can reset
        ANY non-archived KPI
        back to draft
    end note
```

---

## 5. Database Entity Relationship Diagram

```mermaid
erDiagram
    organisations {
        uuid id PK
        string name
    }

    users {
        uuid id PK
        uuid organisation_id FK
        string email
        string role
    }

    kpi_categories {
        uuid id PK
        uuid organisation_id FK
        uuid created_by_id FK
        string name
        string department
        string colour_hex
    }

    kpi_tags {
        uuid id PK
        uuid organisation_id FK
        string name
    }

    kpis {
        uuid id PK
        uuid organisation_id FK
        uuid category_id FK
        uuid created_by_id FK
        uuid approved_by_id FK
        string name
        string code
        enum unit
        enum frequency
        enum data_source
        enum status
        text formula_expression
        integer version
        boolean is_template
        timestamp approved_at
        timestamp deprecated_at
    }

    kpi_history {
        uuid id PK
        uuid kpi_id FK
        uuid changed_by_id FK
        integer version
        string change_summary
        json snapshot
        timestamp changed_at
    }

    kpi_templates {
        uuid id PK
        string name
        string department
        enum unit
        enum frequency
        text suggested_formula
        json tags
        integer usage_count
        boolean is_active
    }

    kpi_tag_association {
        uuid kpi_id FK
        uuid tag_id FK
    }

    kpi_formula_dependency {
        uuid parent_kpi_id FK
        uuid dependency_kpi_id FK
    }

    organisations ||--o{ users : "has"
    organisations ||--o{ kpi_categories : "owns"
    organisations ||--o{ kpi_tags : "owns"
    organisations ||--o{ kpis : "owns"

    kpi_categories ||--o{ kpis : "groups"
    users ||--o{ kpis : "creates"
    users ||--o{ kpi_history : "authors"
    users ||--o{ kpi_categories : "creates"

    kpis ||--o{ kpi_history : "records"
    kpis }o--o{ kpi_tags : "kpi_tag_association"
    kpis }o--o{ kpis : "kpi_formula_dependency"
```

---

## 6. KPI Creation Data Flow

End-to-end data flow for creating a formula KPI, showing how data moves through layers.

```mermaid
flowchart LR
    subgraph Input
        REQ[HTTP Request\nPOST /kpis/]
        BODY[KPICreate JSON body]
    end

    subgraph Validation["1 · Pydantic Validation (schemas.py)"]
        PV[KPICreate model_validator\nChecks formula ↔ data_source\nconsistency]
    end

    subgraph Auth["2 · Auth & Role (dependencies.py)"]
        JWT[JWT decode\nUser lookup]
        ROLE[require_roles check\nhr_admin or manager]
    end

    subgraph Service["3 · Business Logic (service.py)"]
        DUP[Duplicate code check\nSELECT WHERE org+code]
        CAT[Category existence check\nSELECT WHERE category_id+org]
        FORMULA_VAL[Formula validation\nFormulaParser + DFS]
        PERSIST[INSERT kpis\nINSERT kpi_history v1\nINSERT kpi_formula_dependency]
    end

    subgraph Response["4 · Response"]
        LOAD[Eager-load\ncategory + tags + deps]
        SCHEMA[KPIRead serialisation\nPydantic .model_validate]
        RESP[201 Created\nJSON response]
    end

    REQ --> BODY
    BODY --> PV
    PV -->|valid| JWT
    JWT --> ROLE
    ROLE -->|authorised| DUP
    DUP -->|no conflict| CAT
    CAT -->|found| FORMULA_VAL
    FORMULA_VAL -->|no cycle| PERSIST
    PERSIST --> LOAD
    LOAD --> SCHEMA
    SCHEMA --> RESP
```

---

## 7. Audit Trail Flow

How history is recorded every time a KPI definition changes.

```mermaid
sequenceDiagram
    participant C as Client
    participant SVC as KPIService.update_kpi()
    participant DB as PostgreSQL

    C->>SVC: PUT /kpis/{id} {name, formula, change_summary}
    SVC->>DB: SELECT kpi WHERE id=... (+ eager load)
    DB-->>SVC: KPI (version=N)
    note over SVC: Take snapshot of CURRENT state\n_kpi_snapshot(kpi) → dict
    SVC->>DB: INSERT kpi_history\n(kpi_id, version=N+1,\nchange_summary, snapshot=current_state,\nchanged_by_id, changed_at=now())
    note over SVC: Apply changes to KPI row\nkpi.name = new_name\nkpi.formula_expression = new_expr\nkpi.version += 1
    SVC->>DB: UPDATE kpis SET name=..., formula=..., version=N+1
    DB-->>SVC: Updated KPI
    SVC-->>C: 200 OK, KPIRead (version=N+1)
```

**Key insight**: The snapshot stored in `kpi_history` is the state *before* the update. Reading `history[N]` gives you the KPI's state during version N.

---

## 8. Formula Dependency Graph (Conceptual)

How a multi-level dependency chain is represented and evaluated.

```mermaid
graph TB
    GM["GROSS_MARGIN\n(formula)\n=GROSS_PROFIT/REVENUE*100"]
    GP["GROSS_PROFIT\n(formula)\n=REVENUE-COST"]
    REV["REVENUE\n(manual)"]
    COST["COST\n(manual)"]

    GM -->|depends on| GP
    GM -->|depends on| REV
    GP -->|depends on| REV
    GP -->|depends on| COST

    style REV fill:#d4edda,stroke:#28a745
    style COST fill:#d4edda,stroke:#28a745
    style GP fill:#cce5ff,stroke:#004085
    style GM fill:#cce5ff,stroke:#004085
```

**Database representation** (rows in `kpi_formula_dependency`):

| parent_kpi_id | dependency_kpi_id |
|--------------|-----------------|
| GROSS_MARGIN.id | GROSS_PROFIT.id |
| GROSS_MARGIN.id | REVENUE.id |
| GROSS_PROFIT.id | REVENUE.id |
| GROSS_PROFIT.id | COST.id |

> Only *direct* dependencies (codes appearing literally in the formula expression) are stored. The evaluation engine resolves transitive dependencies at runtime.

---

## 9. Template Clone Workflow

```mermaid
flowchart TD
    A([User: POST /kpis/templates/clone/]) --> B[Load KPITemplate by template_id]
    B --> C{Template\nactive?}
    C -->|No| D[/404 Not Found/]
    C -->|Yes| E[Resolve category_id\nfrom request or template default]
    E --> F[Build KPICreate\nfrom template fields]
    F --> G[Call create_kpi internally\nwith same validation path]
    G --> H[/Duplicate code check/]
    H -->|Conflict| I[/409 Conflict/]
    H -->|OK| J[INSERT kpis]
    J --> K[INCREMENT template.usage_count]
    K --> L([201 Created, new KPIRead])
```

---

← [Back to Index](index.md) | Previous: [06 — Tutorials](06-tutorials.md)
