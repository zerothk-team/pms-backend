# Copilot Prompt — Part 5: Notifications, Alerts & Background Tasks
> **Model**: Claude Sonnet 4.6 | **Depends on**: Parts 1–4 complete

---

## Context

Parts 1–4 are complete. The full KPI lifecycle (define → target → actual → score) is working. Now build the **notification system** and **background task scheduler** that keeps users informed and automates recurring tasks.

---

## What to Build in This Part

```
app/
├── notifications/
│   ├── __init__.py
│   ├── models.py         ← Notification, NotificationPreference
│   ├── schemas.py
│   ├── service.py        ← NotificationService
│   ├── router.py
│   └── templates.py      ← Notification message templates
│
└── tasks/
    ├── __init__.py
    ├── scheduler.py      ← APScheduler setup
    ├── jobs.py           ← All background job functions
    └── registry.py       ← Job registration and management
```

---

## Module A: Notifications

### Enums — `app/notifications/enums.py`

```python
class NotificationType(str, Enum):
    # At-risk alerts
    KPI_AT_RISK = "kpi_at_risk"                     # employee's KPI below threshold
    TEAM_KPI_AT_RISK = "team_kpi_at_risk"           # manager: team member at risk

    # Reminders
    ACTUAL_ENTRY_DUE = "actual_entry_due"           # period entry overdue
    TARGET_ACKNOWLEDGEMENT_DUE = "target_acknowledgement_due"
    PERIOD_CLOSING_SOON = "period_closing_soon"      # cycle closing in N days
    APPROVAL_PENDING = "approval_pending"            # actual awaiting manager review

    # Positive
    TARGET_ACHIEVED = "target_achieved"             # 100% hit
    STRETCH_TARGET_ACHIEVED = "stretch_target_achieved"

    # Admin
    SCORING_COMPLETE = "scoring_complete"
    CALIBRATION_REQUIRED = "calibration_required"
    SCORE_FINALISED = "score_finalised"
    SCORE_ADJUSTED = "score_adjusted"               # manager changed employee's score

class NotificationChannel(str, Enum):
    IN_APP = "in_app"       # stored in DB, shown in UI
    EMAIL = "email"         # sent via SMTP (stubbed with logging in dev)
    # SLACK = "slack"       # future

class NotificationStatus(str, Enum):
    UNREAD = "unread"
    READ = "read"
    DISMISSED = "dismissed"
```

---

### Model: `Notification`

```
Table: notifications
```

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `recipient_id` | UUID FK → users.id | not null |
| `notification_type` | Enum(NotificationType) | not null |
| `channel` | Enum(NotificationChannel) | default IN_APP |
| `status` | Enum(NotificationStatus) | default UNREAD |
| `title` | String(255) | not null |
| `body` | Text | not null |
| `action_url` | String(500) | nullable — deep link for frontend |
| `metadata` | JSON | nullable — arbitrary context (kpi_id, target_id, etc.) |
| `sent_at` | DateTime UTC | nullable — null means not yet dispatched |
| `read_at` | DateTime UTC | nullable |
| `expires_at` | DateTime UTC | nullable — auto-dismiss after date |
| `organisation_id` | UUID FK → organisations.id | |
| `created_at` | DateTime UTC | |

**Index:** `(recipient_id, status)`, `(recipient_id, created_at DESC)`

---

### Model: `NotificationPreference`

```
Table: notification_preferences
```

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK → users.id | unique |
| `organisation_id` | UUID FK | |
| `kpi_at_risk_in_app` | Boolean | default True |
| `kpi_at_risk_email` | Boolean | default True |
| `actual_due_in_app` | Boolean | default True |
| `actual_due_email` | Boolean | default False |
| `target_achieved_in_app` | Boolean | default True |
| `target_achieved_email` | Boolean | default True |
| `period_closing_days_before` | Integer | default 3 — how many days before to alert |
| `email_digest_frequency` | String(20) | "immediate" \| "daily" \| "weekly" |
| `updated_at` | DateTime UTC | |

---

### `app/notifications/templates.py`

Define notification content templates as a dict keyed by `NotificationType`. Each template is a function that accepts context dict and returns `(title: str, body: str, action_url: str | None)`.

```python
NOTIFICATION_TEMPLATES: dict[NotificationType, Callable[[dict], tuple[str, str, str | None]]] = {
    NotificationType.KPI_AT_RISK: lambda ctx: (
        f"⚠️ KPI at risk: {ctx['kpi_name']}",
        f"Your KPI '{ctx['kpi_name']}' is at {ctx['achievement_pct']:.1f}% of target. "
        f"You need {ctx['gap']:.1f} more {ctx['unit']} to reach your target by {ctx['cycle_end_date']}.",
        f"/dashboard/kpis/{ctx['target_id']}"
    ),
    NotificationType.ACTUAL_ENTRY_DUE: lambda ctx: (
        f"Action needed: Enter {ctx['kpi_name']} for {ctx['period_label']}",
        f"Your {ctx['frequency']} entry for '{ctx['kpi_name']}' is due. "
        f"The deadline is {ctx['deadline']}.",
        f"/dashboard/actuals/new?target_id={ctx['target_id']}"
    ),
    NotificationType.TARGET_ACHIEVED: lambda ctx: (
        f"🎉 Target achieved: {ctx['kpi_name']}",
        f"Congratulations! You've reached 100% of your target for '{ctx['kpi_name']}'. "
        f"Current achievement: {ctx['achievement_pct']:.1f}%.",
        f"/dashboard/kpis/{ctx['target_id']}"
    ),
    # ... (generate all types)
}
```

---

### `app/notifications/service.py` — NotificationService

```python
class NotificationService:

    async def create_notification(
        self,
        db,
        recipient_id: UUID,
        org_id: UUID,
        notification_type: NotificationType,
        context: dict,
        channel: NotificationChannel = NotificationChannel.IN_APP,
        metadata: dict | None = None,
        expires_at: datetime | None = None,
    ) -> Notification:
        """
        1. Render title + body from template
        2. Check user's NotificationPreference — skip if disabled for this type+channel
        3. Insert Notification row
        4. If channel=EMAIL: enqueue email send (call send_email() — logs in dev)
        5. Return notification
        """
        ...

    async def notify_kpi_at_risk(
        self, db, target_id: UUID, achievement_pct: Decimal
    ) -> list[Notification]:
        """
        Notify both the employee and their manager.
        Check: was a notification of this type sent for this target in the last 24h?
        If so, skip (debounce). Use Redis key: f"notif:at_risk:{target_id}"
        """
        ...

    async def notify_actual_entry_due(
        self, db, target_id: UUID, period_date: date
    ) -> Notification | None:
        """Check if actual already submitted for period before sending."""
        ...

    async def notify_target_achieved(
        self, db, target_id: UUID, achievement_pct: Decimal
    ) -> list[Notification]:
        """Notify employee. Check: not already notified for this target."""
        ...

    async def notify_period_closing(
        self, db, cycle_id: UUID, days_until_close: int
    ) -> int:
        """
        Bulk notify all users with active targets in the cycle.
        Only notify users whose preferences include period_closing_days_before >= days_until_close.
        Returns count of notifications created.
        """
        ...

    async def mark_read(self, db, notification_id: UUID, user_id: UUID) -> Notification
    async def mark_all_read(self, db, user_id: UUID, org_id: UUID) -> int
    async def dismiss(self, db, notification_id: UUID, user_id: UUID) -> Notification

    async def list_for_user(
        self, db, user_id: UUID, org_id: UUID,
        status: NotificationStatus | None = None,
        limit: int = 50,
        before_id: UUID | None = None,   # cursor-based pagination
    ) -> dict:
        """Returns {"notifications": list, "unread_count": int, "has_more": bool}"""
        ...

    async def get_unread_count(self, db, user_id: UUID) -> int

    async def get_or_create_preference(
        self, db, user_id: UUID, org_id: UUID
    ) -> NotificationPreference

    async def update_preference(
        self, db, user_id: UUID, org_id: UUID, data: dict
    ) -> NotificationPreference


async def send_email(to: str, subject: str, body: str) -> None:
    """
    In development: log to console with [EMAIL] prefix.
    In production: integrate with SMTP via `aiosmtplib` or SendGrid API.
    Read SMTP settings from config (add SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD to Settings).
    """
    ...
```

---

### Router — `app/notifications/router.py`

```
GET    /notifications/                      → list own notifications (paginated, cursor-based)
GET    /notifications/unread-count          → {unread: int}
PATCH  /notifications/{id}/read            → mark single as read
POST   /notifications/read-all             → mark all read
DELETE /notifications/{id}                 → dismiss notification
GET    /notifications/preferences/         → get own preferences
PUT    /notifications/preferences/         → update own preferences
```

---

## Module B: Background Task Scheduler

Use **APScheduler** (`apscheduler>=4.0`) with `AsyncIOScheduler` running inside the FastAPI process. For production, recommend migrating to Celery + Redis beat, but APScheduler is fine for v1.

### Install

Add to `pyproject.toml`:
```toml
apscheduler = "^4.0"
```

---

### `app/tasks/scheduler.py`

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

scheduler = AsyncIOScheduler(timezone="UTC")

def start_scheduler(app):
    """Called from app/main.py on startup."""
    register_jobs(scheduler)
    scheduler.start()
    app.state.scheduler = scheduler

def stop_scheduler(app):
    """Called from app/main.py on shutdown."""
    scheduler.shutdown(wait=False)
```

---

### `app/tasks/jobs.py`

Define all background job functions. Each job creates its own DB session using the session factory directly (not via FastAPI dependency injection):

```python
async def check_at_risk_kpis_job():
    """
    Schedule: every day at 08:00 UTC
    1. Find all ACTIVE review cycles across all organisations
    2. For each cycle, find all LOCKED targets
    3. Load latest approved actual for each target
    4. Compute achievement_percentage
    5. If < 60% and we're past 25% of the cycle duration → trigger notify_kpi_at_risk()
    6. Update target.is_at_risk flag in DB
    Log: total targets checked, at-risk count, notifications sent.
    """
    ...

async def send_actual_entry_reminders_job():
    """
    Schedule: every day at 09:00 UTC (Mon–Fri)
    1. Find all LOCKED targets in ACTIVE cycles
    2. Determine which targets have missing entries for the current period
       (period_date = last expected date based on KPI frequency)
    3. Check if entry is overdue (period_date + grace_days < today)
    4. Send reminder — debounce: max 1 reminder per target per period (use Redis key)
    Log: reminders sent count.
    """
    ...

async def send_period_closing_reminders_job():
    """
    Schedule: every day at 07:00 UTC
    1. Find all ACTIVE cycles
    2. Calculate days_until_close = cycle.end_date - today
    3. If days_until_close in [7, 3, 1]: call notify_period_closing()
    """
    ...

async def auto_compute_formula_actuals_job():
    """
    Schedule: first day of each month at 00:30 UTC
    1. Find all ACTIVE cycles with FORMULA KPIs
    2. For each formula KPI: evaluate formula for the just-closed period
    3. Auto-insert KPIActual with entry_source=AUTO_FORMULA
    4. Log: how many formula actuals created.
    """
    ...

async def auto_close_cycle_job():
    """
    Schedule: every day at 00:00 UTC
    1. Find all ACTIVE cycles where end_date < today
    2. If cycle.actual_entry_deadline < today: update status to CLOSED
    3. Trigger: lock all targets in the cycle
    4. Trigger: compute_scores_for_cycle() (scoring engine)
    5. Notify hr_admin that scoring is complete
    Log: cycles closed, scores computed.
    """
    ...

async def cleanup_expired_notifications_job():
    """
    Schedule: every Sunday at 03:00 UTC
    Delete notifications where expires_at < now() AND status != UNREAD.
    Log: count deleted.
    """
    ...
```

---

### `app/tasks/registry.py`

```python
def register_jobs(scheduler: AsyncIOScheduler):
    scheduler.add_job(
        check_at_risk_kpis_job,
        CronTrigger(hour=8, minute=0),
        id="check_at_risk_kpis",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        send_actual_entry_reminders_job,
        CronTrigger(hour=9, minute=0, day_of_week="mon-fri"),
        id="entry_reminders",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        send_period_closing_reminders_job,
        CronTrigger(hour=7, minute=0),
        id="period_closing_reminders",
        replace_existing=True,
    )
    scheduler.add_job(
        auto_compute_formula_actuals_job,
        CronTrigger(day=1, hour=0, minute=30),
        id="formula_actuals",
        replace_existing=True,
    )
    scheduler.add_job(
        auto_close_cycle_job,
        CronTrigger(hour=0, minute=0),
        id="auto_close_cycle",
        replace_existing=True,
    )
    scheduler.add_job(
        cleanup_expired_notifications_job,
        CronTrigger(day_of_week="sun", hour=3, minute=0),
        id="cleanup_notifications",
        replace_existing=True,
    )
```

---

### Admin Endpoints — `app/tasks/router.py`

```
POST /tasks/run/{job_id}         → manually trigger a job (hr_admin only)
GET  /tasks/jobs/                → list all registered jobs + next run time
GET  /tasks/jobs/{job_id}/logs   → last 50 log lines for a job (stub: return from DB)
```

For manual triggering, use `scheduler.get_job(job_id).func()` called as an async task.

---

## Redis Keys Convention

Document all Redis keys used across the system:

```
# Auth
auth:refresh:{user_id}          → refresh token (TTL = JWT_REFRESH_TOKEN_EXPIRE_DAYS)
auth:blacklist:{jti}            → blacklisted token (TTL = remaining token life)

# Notification debounce
notif:at_risk:{target_id}       → TTL 24h — prevent duplicate at-risk notifications
notif:achieved:{target_id}      → TTL 72h — prevent duplicate achievement notifications
notif:reminder:{target_id}:{period_date} → TTL 7 days — prevent duplicate reminders

# Rate limiting (future)
rate:{user_id}:{endpoint}       → request count per minute

# Caching (optional — add if needed)
cache:org_dashboard:{org_id}:{cycle_id}   → TTL 5 min
cache:employee_dashboard:{user_id}        → TTL 2 min
```

---

## Final Integration: Update `app/main.py`

Add scheduler lifecycle to FastAPI startup/shutdown:

```python
@app.on_event("startup")
async def startup():
    await init_redis_pool()
    if not settings.DEBUG:   # don't run scheduler in test environment
        start_scheduler(app)
    if settings.DEBUG:
        await seed_kpi_templates(...)

@app.on_event("shutdown")
async def shutdown():
    stop_scheduler(app)
    await close_redis_pool()
```

Register all new routers:
```python
app.include_router(notifications_router, prefix=f"{settings.API_V1_PREFIX}/notifications")
app.include_router(tasks_router, prefix=f"{settings.API_V1_PREFIX}/tasks")
```

---

## Alembic Migration

```bash
alembic revision --autogenerate -m "create_notification_tables"
```

Verify: `notifications` and `notification_preferences` tables with all indexes.

---

## Tests — `tests/test_notifications.py` + `tests/test_tasks.py`

```python
# Notifications
test_create_in_app_notification()
test_notification_skipped_when_preference_disabled()
test_at_risk_notification_debounced()              # second call within 24h → skipped
test_mark_notification_read()
test_mark_all_read()
test_list_notifications_unread_only()
test_unread_count()

# Tasks
test_check_at_risk_job_identifies_at_risk_targets()
test_entry_reminder_not_sent_if_actual_exists()
test_entry_reminder_debounced()
test_period_closing_reminder_sent_on_correct_days()
test_auto_close_cycle_triggers_scoring()
```

---

## Completion Checklist

After Part 5, your FastAPI backend is feature-complete for the KPI module. Verify:

- [ ] All 5 parts' tests pass: `pytest tests/ -v`
- [ ] `alembic upgrade head` runs cleanly on a fresh DB
- [ ] OpenAPI docs at `/docs` show all endpoints grouped correctly
- [ ] Docker Compose starts all services: `docker-compose up`
- [ ] Health check `GET /health` returns DB + Redis ping
- [ ] Seed data loads on first `DEBUG=True` startup
- [ ] Scheduler starts and logs first job registrations

---

## What to Build Next

Hand this to the **React Frontend Copilot Prompt series**:
- Frontend Part 1: Vite + React setup, Redux Toolkit, RTK Query, Axios, shadcn/ui, routing
- Frontend Part 2: Auth pages (login, register), protected routes, JWT refresh
- Frontend Part 3: KPI management screens (library, builder, templates)
- Frontend Part 4: Target setting + actuals entry screens
- Frontend Part 5: Dashboard screens (employee, manager, org), charts, heatmap