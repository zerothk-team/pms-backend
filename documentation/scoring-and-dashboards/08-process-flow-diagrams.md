# 08 — Process Flow Diagrams

← [Back to Index](index.md)

> All diagrams use [Mermaid](https://mermaid.js.org/) syntax. Render in VS Code with the *Markdown Preview Mermaid Support* extension, or paste into [mermaid.live](https://mermaid.live/).

---

## 1. System Architecture — Module Placement

```mermaid
graph TD
    subgraph PMS Backend
        AUTH[auth module]
        USERS[users module]
        ORGS[organisations module]
        KPIS[kpis module]
        TARGETS[targets module]
        ACTUALS[actuals module]
        CYCLES[review_cycles module]
        SCORING[scoring module]
        DASHBOARDS[dashboards module]
        NOTIF[notifications module]
    end

    CYCLES -->|provides cycle context| SCORING
    TARGETS -->|provides weight, target_value| SCORING
    ACTUALS -->|provides actual_value| SCORING
    KPIS -->|provides frequency, direction| SCORING
    USERS -->|provides employee list| SCORING
    SCORING -->|reads CompositeScore, PerformanceScore| DASHBOARDS
    SCORING -->|finalised event| NOTIF
    USERS -->|role-based access| AUTH
    AUTH -.->|JWT guard| SCORING
    AUTH -.->|JWT guard| DASHBOARDS
```

---

## 2. Scoring Engine Pipeline

```mermaid
flowchart TD
    A([Start: POST /scoring/compute/cycle_id]) --> B{Cycle status == active?}
    B -- No --> ERR1([400: Cycle not active])
    B -- Yes --> C[Load all targets for cycle\nwhere status = locked]
    C --> D[For each employee with targets\ngroup by user_id]
    D --> E[For each KPI target]
    E --> F[Fetch approved actuals\nfiltered by period_date range]
    F --> G{Actuals found?}
    G -- No --> H[Apply missing-actuals penalty\nachievement_pct = 0]
    G -- Yes --> I{KPI direction?}
    I -- higher_is_better --> J[achievement_pct = actual / target × 100]
    I -- lower_is_better --> K[achievement_pct = target / actual × 100\ncapped at 200%]
    J --> L[Clamp at 200%]
    K --> L
    H --> M[weighted_score = achievement_pct × weight / 100]
    L --> M
    M --> N[final_score = weighted_score\nunless adjusted]
    N --> O{All KPIs done?}
    O -- No --> E
    O -- Yes --> P[Sum final_score across all KPIs\n= composite weighted_average]
    P --> Q[Lookup ScoreConfig thresholds\nauto-create if missing]
    Q --> R[Assign rating band]
    R --> S[Persist PerformanceScore rows\nand CompositeScore row]
    S --> T([Return ComputeScoresResponse])
```

---

## 3. Score Status State Machine

```mermaid
stateDiagram-v2
    [*] --> computed : POST /scoring/compute

    computed --> adjusted : PATCH /kpi-score/{id}/adjust\n(manager or hr_admin)

    adjusted --> calibrated : PATCH /calibration/{session_id}/scores/{composite_id}\n(hr_admin via open calibration session)

    computed --> calibrated : (direct calibration without prior adjustment)

    calibrated --> final : POST /scoring/finalise/{cycle_id}\n(hr_admin, cycle must be closed)

    adjusted --> final : POST /scoring/finalise/{cycle_id}\n(hr_admin, cycle must be closed)

    computed --> final : POST /scoring/finalise/{cycle_id}\n(hr_admin, cycle must be closed)

    final --> [*]

    note right of computed
        Immutable KPI scores.
        Composite = sum of weighted KPI scores.
    end note

    note right of adjusted
        One or more KPI scores
        updated by manager.
        Composite recomputed.
    end note

    note right of calibrated
        HR aligned composite score
        via calibration session.
    end note

    note right of final
        Locked. No further changes.
        Visible to employee.
    end note
```

---

## 4. Calibration Session Lifecycle

```mermaid
sequenceDiagram
    actor HR as HR Admin
    participant API as Scoring API
    participant DB as Database

    HR->>API: POST /scoring/calibration\n{review_cycle_id, name, scope_user_ids}
    API->>DB: INSERT CalibrationSession (status=open)
    DB-->>API: CalibrationSession row
    API-->>HR: 201 CalibrationSessionDetail

    loop For each score to calibrate
        HR->>API: PATCH /scoring/calibration/{session_id}/scores/{composite_id}\n{new_score, note}
        API->>DB: CHECK composite.review_cycle_id matches session
        API->>DB: CHECK composite.user_id in scope_user_ids
        API->>DB: UPDATE CompositeScore.final_weighted_average = new_score
        API->>DB: UPDATE CompositeScore.status = calibrated
        API->>DB: UPDATE CompositeScore.rating (re-evaluate)
        DB-->>API: Updated CompositeScore
        API-->>HR: 200 CompositeScoreRead
    end

    HR->>API: POST /scoring/calibration/{session_id}/complete
    API->>DB: UPDATE CalibrationSession.status = completed\nSET completed_at = now()
    DB-->>API: Updated session
    API-->>HR: 200 CalibrationSessionDetail
```

---

## 5. Data Model Entity-Relationship Diagram

```mermaid
erDiagram
    REVIEW_CYCLES ||--o{ SCORE_CONFIGS : "configures"
    REVIEW_CYCLES ||--o{ COMPOSITE_SCORES : "has"
    REVIEW_CYCLES ||--o{ CALIBRATION_SESSIONS : "runs"
    REVIEW_CYCLES ||--o{ PERFORMANCE_SCORES : "contains"

    ORGANISATIONS ||--o{ SCORE_CONFIGS : "owns"

    USERS ||--o{ COMPOSITE_SCORES : "has one per cycle"
    USERS ||--o{ PERFORMANCE_SCORES : "has many"
    USERS ||--o{ CALIBRATION_SESSIONS : "facilitates (HR)"

    TARGETS ||--|| PERFORMANCE_SCORES : "drives one"

    COMPOSITE_SCORES ||--o{ PERFORMANCE_SCORES : "aggregates"
    COMPOSITE_SCORES ||--o{ SCORE_ADJUSTMENTS : "tracks"
    COMPOSITE_SCORES ||--o{ CALIBRATION_SCORE_CHANGES : "records"

    CALIBRATION_SESSIONS ||--o{ CALIBRATION_SCORE_CHANGES : "contains"

    SCORE_CONFIGS {
        uuid id PK
        uuid organisation_id FK
        uuid review_cycle_id FK
        decimal exceptional_min
        decimal exceeds_min
        decimal meets_min
        decimal partially_meets_min
        decimal does_not_meet_min
        boolean allow_manager_adjustment
        decimal max_adjustment_points
        boolean requires_calibration
    }

    PERFORMANCE_SCORES {
        uuid id PK
        uuid user_id FK
        uuid review_cycle_id FK
        uuid target_id FK
        string kpi_code
        decimal achievement_pct
        decimal weight
        decimal weighted_score
        decimal final_score
        string status
        decimal original_score
        datetime computed_at
    }

    COMPOSITE_SCORES {
        uuid id PK
        uuid user_id FK
        uuid review_cycle_id FK
        decimal weighted_average
        decimal final_weighted_average
        string rating
        integer kpi_count
        integer kpis_with_actuals
        string status
        datetime computed_at
        datetime finalised_at
    }

    SCORE_ADJUSTMENTS {
        uuid id PK
        uuid composite_score_id FK
        uuid adjusted_by_id FK
        decimal previous_score
        decimal new_score
        string reason
        datetime adjusted_at
    }

    CALIBRATION_SESSIONS {
        uuid id PK
        uuid review_cycle_id FK
        uuid facilitator_id FK
        string name
        string status
        array scope_user_ids
        text notes
        datetime completed_at
    }
```

---

## 6. Manager Adjustment → Composite Recomputation

```mermaid
sequenceDiagram
    actor MGR as Manager
    participant API as Scoring API
    participant CALC as Calculator
    participant DB as Database

    MGR->>API: PATCH /kpi-score/{perf_score_id}/adjust\n{adjusted_score, reason}

    API->>DB: FETCH PerformanceScore by id
    DB-->>API: PerformanceScore (original_score, user_id, cycle_id)

    API->>DB: VERIFY manager owns composite\n(composite.user_id reports-to manager)

    API->>DB: FETCH ScoreConfig for cycle
    DB-->>API: ScoreConfig (max_adjustment_points)

    API->>CALC: Validate cap:\nnew_score ≤ original_score + max_adjustment_points
    alt Exceeds cap
        CALC-->>API: Reject with 400
        API-->>MGR: 400 Adjustment exceeds allowed cap
    else Within cap
        API->>DB: UPDATE PerformanceScore\n.final_score = adjusted_score\n.status = adjusted
        API->>DB: INSERT ScoreAdjustment record\n(previous, new, reason, adjusted_by)
        API->>DB: FETCH all PerformanceScore rows\nfor (user_id, cycle_id)
        DB-->>API: All KPI scores
        API->>CALC: Recompute composite\nSUM(final_score) → weighted_average
        CALC-->>API: new_weighted_average, new_rating
        API->>DB: UPDATE CompositeScore\n.final_weighted_average = new_weighted_average\n.rating = new_rating\n.status = adjusted
        DB-->>API: Updated CompositeScore
        API-->>MGR: 200 CompositeScoreRead
    end
```

---

## 7. Dashboard Read Path

```mermaid
flowchart TD
    A([Client GET /dashboards/...]) --> B{Endpoint}

    B -- /org/cycle_id --> C[OrgDashboard\nHR Admin / Executive]
    B -- /manager/me/cycle_id --> D[ManagerDashboard\nManager]
    B -- /me/cycle_id --> E[EmployeeDashboard\nEmployee / Manager / HR]
    B -- /kpi-progress/cycle_id --> F[KPIProgressReport\nHR Admin / Executive]
    B -- /leaderboard/cycle_id --> G[Leaderboard\nAll authenticated]

    C --> H[Query CompositeScore\nGROUP BY org]
    D --> I[Query CompositeScore\nfor direct reports only]
    E --> J[Query CompositeScore + PerformanceScore\nfor self only]
    F --> K[Query PerformanceScore\nGROUP BY kpi_code]
    G --> L[Query CompositeScore\nORDER BY final_weighted_average DESC\nLIMIT 20]

    H --> M([Return OrgDashboard JSON])
    I --> N([Return ManagerDashboard JSON])
    J --> O([Return EmployeeDashboard JSON])
    K --> P([Return KPIProgressReport JSON])
    L --> Q([Return Leaderboard JSON])
```
