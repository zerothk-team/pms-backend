# 08 — Process & Data Flow Diagrams

> All diagrams use [Mermaid](https://mermaid.js.org/) syntax. Render them in any Markdown viewer that supports Mermaid, in the Mermaid Live Editor, or via VS Code's Mermaid extension.

---

## 1. System Context Diagram

How Part 3 fits into the overall PMS:

```mermaid
graph TD
    subgraph Part1 ["Part 1 — Foundation"]
        ORG[Organisations]
        USR[Users]
    end

    subgraph Part2 ["Part 2 — KPIs"]
        KPI[KPI Definitions]
        FORMULA[Formula Engine]
    end

    subgraph Part3 ["Part 3 — Operations (THIS MODULE)"]
        RC[Review Cycles]
        TGT[Targets]
        ACT[Actuals]
    end

    subgraph Part4 ["Part 4 — Scoring (future)"]
        SCR[Scoring Engine]
        CAL[Calibration]
    end

    ORG --> RC
    USR --> TGT
    USR --> ACT
    KPI --> TGT
    KPI --> ACT
    FORMULA --> ACT
    RC --> TGT
    TGT --> ACT
    ACT --> SCR
```

---

## 2. Review Cycle State Machine

```mermaid
stateDiagram-v2
    [*] --> DRAFT : create (hr_admin)

    DRAFT --> ACTIVE : activate\n[no ACTIVE overlap]\n(side-effect: lock all targets)
    ACTIVE --> CLOSED : close
    CLOSED --> ARCHIVED : archive
    ARCHIVED --> [*]

    ACTIVE --> DRAFT : revert (hr_admin only)
    CLOSED --> ACTIVE : reopen (hr_admin only)

    note right of ACTIVE
        Targets become LOCKED
        Actuals can be submitted
    end note

    note right of CLOSED
        Actuals entry ends
        Scoring triggered
    end note
```

---

## 3. Target Status State Machine

```mermaid
stateDiagram-v2
    [*] --> DRAFT : create target

    DRAFT --> PENDING_ACKNOWLEDGEMENT : send for ack\n(manager/hr_admin)
    DRAFT --> APPROVED : direct approve\n(manager/hr_admin)
    PENDING_ACKNOWLEDGEMENT --> ACKNOWLEDGED : employee acknowledges
    ACKNOWLEDGED --> APPROVED : approve\n(manager/hr_admin)
    APPROVED --> DRAFT : revert\n(manager/hr_admin)

    DRAFT --> LOCKED : cycle activates (automatic)
    PENDING_ACKNOWLEDGEMENT --> LOCKED : cycle activates (automatic)
    ACKNOWLEDGED --> LOCKED : cycle activates (automatic)
    APPROVED --> LOCKED : cycle activates (automatic)

    LOCKED --> [*] : terminal (no edits)

    note right of LOCKED
        Set when review cycle
        transitions DRAFT → ACTIVE
    end note
```

---

## 4. Actual Entry Status State Machine

```mermaid
stateDiagram-v2
    [*] --> APPROVED : individual target\n(auto-approved)
    [*] --> PENDING_APPROVAL : team/org target

    PENDING_APPROVAL --> APPROVED : manager approves
    PENDING_APPROVAL --> REJECTED : manager rejects\n(reason required)

    APPROVED --> SUPERSEDED : new submission for\nsame period
    REJECTED --> SUPERSEDED : new submission for\nsame period

    SUPERSEDED --> [*] : archived (read-only)
    APPROVED --> [*] : used for scoring

    note right of SUPERSEDED
        Record retained for
        complete audit trail
    end note
```

---

## 5. Entity Relationship Diagram

```mermaid
erDiagram
    ORGANISATIONS {
        uuid id PK
        string name
    }

    USERS {
        uuid id PK
        uuid organisation_id FK
        uuid manager_id FK
        string role
    }

    KPIS {
        uuid id PK
        uuid organisation_id FK
        string frequency
        string unit
        string scoring_direction
        string kpi_type
    }

    REVIEW_CYCLES {
        uuid id PK
        uuid organisation_id FK
        uuid created_by_id FK
        string cycle_type
        string status
        date start_date
        date end_date
    }

    KPI_TARGETS {
        uuid id PK
        uuid review_cycle_id FK
        uuid kpi_id FK
        uuid assignee_user_id FK
        uuid set_by_id FK
        uuid cascade_parent_id FK
        string assignee_type
        string status
        decimal target_value
        decimal weight
    }

    TARGET_MILESTONES {
        uuid id PK
        uuid target_id FK
        date milestone_date
        decimal expected_value
    }

    KPI_ACTUALS {
        uuid id PK
        uuid target_id FK
        uuid kpi_id FK
        uuid submitted_by_id FK
        uuid reviewed_by_id FK
        date period_date
        decimal actual_value
        string status
        string entry_source
    }

    ACTUAL_EVIDENCE {
        uuid id PK
        uuid actual_id FK
        uuid uploaded_by_id FK
        string file_name
        string file_url
    }

    ORGANISATIONS ||--o{ REVIEW_CYCLES : "has"
    ORGANISATIONS ||--o{ USERS : "employs"
    USERS ||--o{ KPI_TARGETS : "assigned to (assignee)"
    USERS ||--o{ KPI_TARGETS : "set by"
    USERS ||--o{ KPI_ACTUALS : "submitted by"
    KPIS ||--o{ KPI_TARGETS : "measured by"
    KPIS ||--o{ KPI_ACTUALS : "tracks"
    REVIEW_CYCLES ||--o{ KPI_TARGETS : "scopes"
    KPI_TARGETS ||--o{ TARGET_MILESTONES : "has"
    KPI_TARGETS ||--o{ KPI_ACTUALS : "records"
    KPI_ACTUALS ||--o{ ACTUAL_EVIDENCE : "evidenced by"
    KPI_TARGETS ||--o{ KPI_TARGETS : "cascades to (parent-child)"
```

---

## 6. Target Cascade Tree

Example of a 3-level cascade hierarchy (Org → Managers → Employees):

```mermaid
graph TD
    ORG["🏢 Org Target\nRevenue: 10,000,000\n[LOCKED]"]

    MGR_N["👤 North Manager\nRevenue: 6,000,000 (60%)\n[LOCKED]"]
    MGR_S["👤 South Manager\nRevenue: 4,000,000 (40%)\n[LOCKED]"]

    EMP1["👤 Rep A (North)\nRevenue: 2,000,000\n[LOCKED]"]
    EMP2["👤 Rep B (North)\nRevenue: 2,000,000\n[LOCKED]"]
    EMP3["👤 Rep C (North)\nRevenue: 2,000,000\n[LOCKED]"]
    EMP4["👤 Rep D (South)\nRevenue: 2,000,000\n[LOCKED]"]
    EMP5["👤 Rep E (South)\nRevenue: 2,000,000\n[LOCKED]"]

    ORG -->|cascade| MGR_N
    ORG -->|cascade| MGR_S
    MGR_N -->|cascade| EMP1
    MGR_N -->|cascade| EMP2
    MGR_N -->|cascade| EMP3
    MGR_S -->|cascade| EMP4
    MGR_S -->|cascade| EMP5
```

---

## 7. Actual Submission Request Flow

```mermaid
sequenceDiagram
    participant EMP as Employee
    participant API as FastAPI Router
    participant SVC as ActualService
    participant DB as Database

    EMP->>API: POST /actuals/ {target_id, period_date, actual_value}
    API->>API: Authenticate + authorise
    API->>SVC: submit_actual(org_id, user, data)

    SVC->>DB: Load target + cycle
    DB-->>SVC: KPITarget + ReviewCycle

    SVC->>SVC: Assert target is LOCKED
    SVC->>SVC: Assert caller has permission
    SVC->>SVC: Validate period_date alignment

    SVC->>DB: Query existing actual for (target, period_date)
    DB-->>SVC: Existing record (or None)

    alt Existing APPROVED
        SVC->>DB: Mark existing as SUPERSEDED
    else Existing PENDING_APPROVAL
        SVC->>DB: Update in-place
        DB-->>SVC: Updated actual
        SVC-->>API: KPIActual
        API-->>EMP: 201 Created
    else No existing record
        SVC->>SVC: Determine initial status\n(APPROVED if individual else PENDING_APPROVAL)
        SVC->>DB: Insert new KPIActual
        DB-->>SVC: New actual
        SVC-->>API: KPIActual
        API-->>EMP: 201 Created
    end
```

---

## 8. Cycle Activation Flow (Target Auto-Lock)

```mermaid
sequenceDiagram
    participant HR as HR Admin
    participant API as FastAPI Router
    participant CYC_SVC as ReviewCycleService
    participant DB as Database

    HR->>API: PATCH /review-cycles/{id}/status {status: "active"}
    API->>CYC_SVC: update_status(cycle_id, data)

    CYC_SVC->>DB: Load ReviewCycle
    DB-->>CYC_SVC: cycle (status=DRAFT)

    CYC_SVC->>CYC_SVC: Validate DRAFT → ACTIVE is allowed

    CYC_SVC->>DB: Check no overlapping ACTIVE cycle
    DB-->>CYC_SVC: No overlap ✅

    CYC_SVC->>DB: SELECT all KPITargets WHERE review_cycle_id=id\nAND status IN (draft, pending_ack, acknowledged, approved)
    DB-->>CYC_SVC: N targets

    loop For each target
        CYC_SVC->>DB: UPDATE target SET status=locked, locked_at=now()
    end

    CYC_SVC->>DB: UPDATE cycle SET status=active
    DB-->>CYC_SVC: Updated cycle

    CYC_SVC-->>API: ReviewCycle
    API-->>HR: 200 OK {status: "active"}

    note over DB: All N targets are now LOCKED\nNo further target edits possible
```

---

## 9. Achievement Percentage Calculations

```mermaid
graph LR
    subgraph HIGHER_IS_BETTER["HIGHER IS BETTER KPI (e.g. Revenue, Sales)"]
        H_ACT["actual = 80,000"]
        H_TGT["target = 100,000"]
        H_CALC["(80,000 / 100,000) × 100 = 80%"]
        H_ACT --> H_CALC
        H_TGT --> H_CALC
    end

    subgraph LOWER_IS_BETTER["LOWER IS BETTER KPI (e.g. Defect Rate, Cost)"]
        L_ACT["actual = 3% defects"]
        L_TGT["target = 5% defects"]
        L_CALC["(5 / 3) × 100 = 166%\n(Beating the target = >100%)"]
        L_ACT --> L_CALC
        L_TGT --> L_CALC
    end
```

---

## 10. Time Series Data Model

Illustrates how a 12-period annual cycle builds up over time:

```mermaid
gantt
    title Revenue KPI — FY 2025 Monthly Actuals
    dateFormat YYYY-MM-DD
    axisFormat %b

    section Submitted
    Jan (112,000 ✅)  :done, 2025-01-01, 2025-01-31
    Feb (98,000 ✅)   :done, 2025-02-01, 2025-02-28
    Mar (125,000 ✅)  :done, 2025-03-01, 2025-03-31
    Apr (107,000 ✅)  :done, 2025-04-01, 2025-04-30

    section Pending
    May (⏳ PENDING)  :active, 2025-05-01, 2025-05-31

    section Future
    Jun               :crit, 2025-06-01, 2025-06-30
    Jul               :crit, 2025-07-01, 2025-07-31
    Aug               :crit, 2025-08-01, 2025-08-31
    Sep               :crit, 2025-09-01, 2025-09-30
    Oct               :crit, 2025-10-01, 2025-10-31
    Nov               :crit, 2025-11-01, 2025-11-30
    Dec               :crit, 2025-12-01, 2025-12-31
```
