# 05 — Background Jobs

The task module (`app/tasks/`) provides six scheduled jobs managed by
**APScheduler 3.x** (`AsyncIOScheduler`).  All jobs run in the same Python
event loop as the FastAPI application.

---

## Scheduler Architecture

```
Application startup (lifespan)
        │
        ├── settings.DEBUG == True  →  scheduler NOT started (dev / test safety)
        │
        └── settings.DEBUG == False →  start_scheduler(app)
                                             │
                                             ├── register_jobs(scheduler)
                                             │     (adds 6 CronTrigger jobs)
                                             │
                                             └── scheduler.start()

Application shutdown (lifespan)
        │
        └── scheduler.shutdown(wait=False)
```

The scheduler singleton is created at **module import time** in `app/tasks/scheduler.py`:

```python
scheduler = AsyncIOScheduler(timezone="UTC")
```

This means it can always be inspected via `from app.tasks.scheduler import scheduler`
without starting it.

### Missed Run Handling (`misfire_grace_time`)

Each job has `misfire_grace_time` set:
- Most jobs: **3600 seconds** (1 hour) — if the server was down and comes back
  within 1 hour of the scheduled time, APScheduler will run the missed job immediately.
- Long-running jobs (formula actuals, cleanup): **7200 seconds** (2 hours).

If a job is missed by more than the grace window, it is skipped and will run
at the next scheduled time.

---

## Job Summary Table

| Job ID | Function | Schedule | Grace | Purpose |
|--------|----------|----------|-------|---------|
| `check_at_risk_kpis` | `check_at_risk_kpis_job` | Daily 08:00 UTC | 1 h | Flag at-risk KPIs and notify owners |
| `entry_reminders` | `send_actual_entry_reminders_job` | Mon–Fri 09:00 UTC | 1 h | Remind employees of overdue data entry |
| `period_closing_reminders` | `send_period_closing_reminders_job` | Daily 07:00 UTC | 1 h | Warn users when cycle period is ending |
| `formula_actuals` | `auto_compute_formula_actuals_job` | 1st of month 00:30 UTC | 2 h | Auto-compute formula-based KPI actuals |
| `auto_close_cycle` | `auto_close_cycle_job` | Daily 00:00 UTC | 1 h | Close expired cycles and run scoring |
| `cleanup_notifications` | `cleanup_expired_notifications_job` | Sunday 03:00 UTC | 2 h | Delete old READ/DISMISSED notifications |

---

## Job 1: `check_at_risk_kpis`

**Schedule**: Daily at **08:00 UTC** (Monday–Sunday)

**Function**: `check_at_risk_kpis_job`

### What it does

1. Fetches all **ACTIVE** review cycles from the database.
2. For each cycle, checks if enough time has elapsed to make the check meaningful:
   - Skips if less than **25%** of the cycle duration has passed.
   - This prevents false alarms at the very start of a cycle when no data is expected yet.
3. For each **LOCKED** target with an assigned user:
   - Finds the most recent **APPROVED** actual.
   - Computes the achievement percentage using the scoring engine's formula.
   - If achievement < **60%**, calls `notify_kpi_at_risk(db, target_id, achievement_pct)`.
4. The notification service handles debouncing (24 h TTL per target).

### Business reasoning

"At risk" is defined as **less than 60% achievement**.  This threshold means:
- The KPI is meaningfully below target (not just slightly off).
- There is still time for corrective action.

If the actual is missing, the job skips the target — the **entry reminders job**
handles missing data separately.

### Side effects

- Writes `Notification` rows for `KPI_AT_RISK` and optionally `TEAM_KPI_AT_RISK`.
- Writes Redis debounce keys.
- Calls `db.commit()`.

### Metrics logged

```
check_at_risk_kpis_job: checked=47 at_risk=5 notifications_sent=6
```

### Failure behaviour

If an exception occurs, the job logs the traceback and returns without crashing
the application.  The scheduler will retry at the next scheduled time.

---

## Job 2: `entry_reminders`

**Schedule**: Weekdays (**Mon–Fri**) at **09:00 UTC**

**Function**: `send_actual_entry_reminders_job`

### What it does

1. Fetches all **ACTIVE** review cycles.
2. For each cycle, fetches **LOCKED** targets with an assigned user.
3. For each target:
   - Looks up the KPI's measurement frequency.
   - Calls `ReviewCycleService.get_current_measurement_periods()` to get the list
     of expected period dates within the cycle up to today.
   - For each expected period with a **2-day grace period** past its deadline:
     - Checks if an approved actual exists for that period.
     - If no actual exists, calls `notify_actual_entry_due(db, target_id, period_date)`.
4. The notification service handles debouncing (7-day TTL per target + period).

### Business reasoning

The **2-day grace period** prevents false urgency — data entry on exactly the
period end date is normal and should not trigger a reminder immediately.  Only
data that is at least 2 days overdue warrants a reminder.

The job only runs on **weekdays** because reminders sent on weekends are unlikely
to be seen promptly and may be annoying.

### Side effects

- Writes `Notification` rows for `ACTUAL_ENTRY_DUE`.
- Writes Redis debounce keys.
- Calls `db.commit()`.

### Metrics logged

```
send_actual_entry_reminders_job: reminders_sent=12
```

---

## Job 3: `period_closing_reminders`

**Schedule**: Daily at **07:00 UTC**

**Function**: `send_period_closing_reminders_job`

### What it does

1. Fetches all **ACTIVE** review cycles.
2. For each cycle, computes `days_left = cycle.end_date - today`.
3. If `days_left` matches one of the defined alert thresholds (`[7, 3, 1]`):
   - Calls `notify_period_closing(db, cycle_id, days_left)`.
   - The notification service sends to **all active users** in the organisation.
4. The notification service handles debouncing (24 h per cycle + days-remaining combination).

### Business reasoning

Three alert points (7 days, 3 days, 1 day) provide:
- **7 days**: Enough time to plan and submit all actuals.
- **3 days**: A clear "deadline approaching" reminder.
- **1 day**: A final urgency alert.

Users can configure `period_closing_days_before` in their preferences to receive
the alert at a different threshold if they want earlier or later warnings.

### Side effects

- Writes `Notification` rows for `PERIOD_CLOSING_SOON`.
- Writes Redis debounce keys.
- Calls `db.commit()`.

### Metrics logged

```
send_period_closing_reminders_job: notifications_sent=15
```

---

## Job 4: `formula_actuals`

**Schedule**: **1st of every month** at **00:30 UTC**

**Function**: `auto_compute_formula_actuals_job`

### What it does

1. Determines the **previous calendar month** as the target period.
   (e.g., when running on 1st March, the period is February)
2. Fetches all **ACTIVE** cycles.
3. For each cycle, fetches **LOCKED** targets where:
   - The KPI has `data_source = FORMULA`.
4. For each formula target:
   - Skips if an approved actual already exists for this period (idempotency).
   - Calls `_resolve_formula_values(db, kpi, period_date)` to look up
     dependency KPI actuals.
   - Evaluates the formula using `FormulaEvaluator`.
   - Inserts a new `KPIActual` row with:
     - `entry_source = AUTO_FORMULA`
     - `status = APPROVED` (system entries are pre-approved)
     - `notes = "Auto-computed from formula: <expression>"`

### The `_resolve_formula_values` helper

This private helper performs dependency resolution:
1. Uses `FormulaParser.extract_kpi_references()` to find all KPI codes referenced
   by the formula expression.
2. For each referenced code, finds the matching KPI in the same organisation.
3. Looks up the most recent **APPROVED** actual for that KPI up to and including
   the period date.
4. Returns `dict[kpi_code, float_value]` for use by `FormulaEvaluator`.

**Example**: formula `SALES_REVENUE / SALES_CALLS` with actual values
`{"SALES_REVENUE": 50000.0, "SALES_CALLS": 200.0}` → evaluates to `250.0`.

### Business reasoning

Formula-based KPIs (e.g., "Revenue per Employee = Total Revenue / Headcount") should
not require manual data entry.  By auto-computing them on the 1st of each month for
the previous month, the system ensures these values are available for scoring without
human intervention.

### Side effects

- Inserts `KPIActual` rows.
- Calls `db.commit()`.
- Does **not** send notifications.

### Metrics logged

```
auto_compute_formula_actuals_job: created=8 period=2025-02-01
```

---

## Job 5: `auto_close_cycle`

**Schedule**: Daily at **00:00 UTC**

**Function**: `auto_close_cycle_job`

### What it does

1. Fetches all **ACTIVE** review cycles.
2. For each cycle where `actual_entry_deadline` (or `end_date`) is in the past:
   a. Sets `cycle.status = CLOSED`.
   b. Calls `ReviewCycleService._lock_targets_for_cycle(db, cycle.id)` to
      lock all remaining targets.
   c. Calls `ScoringEngine.compute_scores_for_cycle(db, cycle.id, org_id)`
      to run the scoring engine.
   d. Sends a `SCORING_COMPLETE` notification to all HR admins in the organisation.

### Business reasoning

Review cycles must close consistently and on schedule regardless of whether
HR admins are available to close them manually.  Automatic closure ensures:
- Employees can't submit actuals after the deadline.
- Scoring runs on the correct data snapshot.
- HR admins are immediately notified so they can review scores.

The job uses `actual_entry_deadline` rather than `end_date` because some
organisations may allow a data entry window that extends slightly beyond the
formal cycle end date.

### Idempotency

The job only processes `ACTIVE` cycles — once a cycle is `CLOSED`, it will not
be processed again.  If the scoring engine fails, the cycle is still closed
(preventing late entries) but scoring must be retried manually.

### Side effects

- Updates `ReviewCycle.status`.
- Locks targets (updates target states).
- Inserts scoring records.
- Sends `SCORING_COMPLETE` notifications to HR admins.
- Calls `db.commit()`.

### Metrics logged

```
auto_close_cycle_job: cycles_closed=1 scores_computed=23
```

---

## Job 6: `cleanup_notifications`

**Schedule**: Every **Sunday at 03:00 UTC**

**Function**: `cleanup_expired_notifications_job`

### What it does

1. Computes `now = datetime.now(UTC)`.
2. Executes a single `DELETE` statement targeting `Notification` rows where:
   - `expires_at < now` (past their expiry time)
   - `status != UNREAD` (only `READ` or `DISMISSED`)
3. Logs the number of rows deleted.

### Business reasoning

Keeping years of old notifications wastes database storage.  However:
- **UNREAD** notifications are never auto-deleted, because the user hasn't
  had a chance to see them — deleting them silently would be a poor user experience.
- **READ** and **DISMISSED** notifications are candidates for cleanup once
  they're past their `expires_at` date.
- The job runs weekly on Sunday at 03:00 (off-peak) to minimise impact on production load.

`expires_at` is set when notifications are created.  Typical expiry is 30–90 days
depending on the notification type.

### Designed to be safe to skip

If the job is missed for several weeks, the next run will delete all eligible rows
in one pass.  There is no risk of data loss for unread messages.

### Side effects

- Hard-deletes `Notification` rows.
- Calls `db.commit()`.
- Does **not** send notifications.

### Metrics logged

```
cleanup_expired_notifications_job: deleted=143
```

---

## Error Handling Pattern

All six jobs follow the same error handling pattern:

```python
try:
    async with SessionLocal() as db:
        # ... job business logic ...
        await db.commit()
    logger.info("job_name: key=value key2=value2")
except Exception:
    logger.exception("job_name failed")
```

Key design choices:
- `except Exception` at the **outermost** level catches all errors so
  APScheduler does not mark the job as crashed and does not suppress future runs.
- All metrics are logged **after** a successful commit, so log entries indicate
  real work done.
- Jobs use `logger.exception()` which automatically includes the full traceback.
- Each job creates and manages its own `AsyncSessionLocal()` session — there is
  no shared session state between jobs or between a job and an HTTP request.

---

## Manual Triggering

Jobs can be triggered manually via the admin API:

```bash
# Trigger the at-risk check immediately
curl -X POST \
  -H "Authorization: Bearer $HR_ADMIN_TOKEN" \
  "http://localhost:8000/api/v1/tasks/run/check_at_risk_kpis"
```

The job runs in the background (fire-and-forget).  Monitor the server logs
for completion status.  See [API Reference](04-api-reference.md) for full details.

---

## Monitoring & Observability

All jobs emit structured log lines with key=value pairs for easy parsing by
log aggregation tools (e.g., Datadog, CloudWatch, Loki).

| Job | Log pattern |
|-----|-------------|
| `check_at_risk_kpis` | `checked=N at_risk=N notifications_sent=N` |
| `entry_reminders` | `reminders_sent=N` |
| `period_closing_reminders` | `notifications_sent=N` |
| `formula_actuals` | `created=N period=YYYY-MM-DD` |
| `auto_close_cycle` | `cycles_closed=N scores_computed=N` |
| `cleanup_notifications` | `deleted=N` |

All logs use the logger name `pms.jobs` for easy log-level filtering:

```python
import logging
logging.getLogger("pms.jobs").setLevel(logging.INFO)
```
