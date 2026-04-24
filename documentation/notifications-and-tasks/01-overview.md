# 01 — Module Overview

## Purpose

The Notifications & Background Tasks module is the **communication backbone** of the Performance Management System.  It answers two core questions:

1. **"What should I be paying attention to right now?"** — realtime, per-user in-app notifications driven by data changes.
2. **"What routine work does the system need to do without human intervention?"** — scheduled jobs that assess risk, send reminders, auto-compute values, and maintain data hygiene.

Without this module, every alerting task would require a human to manually check dashboards and every formula-based KPI calculation would require a human to trigger computation at month end.

---

## Where This Module Sits in the System

```
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Application                       │
│                                                             │
│  ┌────────────┐  ┌────────────┐  ┌────────────────────┐   │
│  │  KPIs      │  │  Targets   │  │  Review Cycles     │   │
│  │  Actuals   │  │  Scoring   │  │  Organisations     │   │
│  └─────┬──────┘  └─────┬──────┘  └─────────┬──────────┘   │
│        │               │                   │               │
│        └───────────────┴───────────────────┘               │
│                        │ produces events                    │
│              ┌─────────▼──────────┐                        │
│              │  Notifications     │◄──── User preferences  │
│              │  app/notifications/│                        │
│              └─────────┬──────────┘                        │
│                        │ persists rows                     │
│              ┌─────────▼──────────┐                        │
│              │  PostgreSQL         │                        │
│              │  notifications      │                        │
│              │  notification_prefs │                        │
│              └────────────────────┘                        │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Background Tasks  app/tasks/                        │  │
│  │                                                      │  │
│  │  APScheduler  ──► jobs.py ──► NotificationService    │  │
│  │  registry.py       │          (creates notifications) │  │
│  │  scheduler.py      └──► Database updates             │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐                        │
│  │  Redis       │  │  SMTP Mail   │                        │
│  │  (debounce)  │  │  (email chan)│                        │
│  └──────────────┘  └──────────────┘                        │
└─────────────────────────────────────────────────────────────┘
```

---

## Module Directory Structure

### `app/notifications/`

```
app/notifications/
├── __init__.py               Empty package marker
├── enums.py                  NotificationType (12 values)
│                             NotificationChannel (IN_APP, EMAIL)
│                             NotificationStatus (UNREAD, READ, DISMISSED)
├── models.py                 SQLAlchemy ORM models
│                               Notification — one row per notification event
│                               NotificationPreference — one row per user
├── schemas.py                Pydantic schemas for request / response
│                               NotificationRead, NotificationPreferenceRead,
│                               NotificationPreferenceUpdate, UnreadCountResponse
├── service.py                NotificationService class
│                               Business logic: create, dedup, deliver, preference
├── templates.py              NOTIFICATION_TEMPLATES dict
│                               render_notification(type, context) → title,body,url
└── router.py                 7 HTTP endpoints under /api/v1/notifications/
```

### `app/tasks/`

```
app/tasks/
├── __init__.py               Empty package marker
├── scheduler.py              APScheduler singleton + start_scheduler(app)
├── registry.py               register_jobs() — CronTrigger definitions
├── jobs.py                   6 async job functions + helper _resolve_formula_values
└── router.py                 2 HTTP endpoints under /api/v1/tasks/
```

---

## Data Flow: Notification Lifecycle

```
Job or Service layer event
         │
         ▼
NotificationService.send_notification(db, redis, recipient_id, org_id, type, ctx)
         │
         ├─► Check NotificationPreference for user
         │       (does user want this channel for this type?)
         │
         ├─► Check Redis debounce key
         │       (has an identical alert been sent recently?)
         │
         ├─► Render title + body + action_url from NOTIFICATION_TEMPLATES
         │
         ├─► INSERT notification row  (status=UNREAD, channel=IN_APP)
         │
         └─► [If email enabled] send SMTP email asynchronously
                  │
                  └─► mark channel=EMAIL, status=UNREAD on separate row
```

---

## Design Decisions

### 1. Redis Debounce

One of the most important design decisions is **Redis-backed deduplication** (debouncing).

Without it, background jobs that run every day could spam users with identical
notifications for the same at-risk KPI every morning.  The service stores a Redis
key with a TTL per event:

| Event class | Key pattern | TTL |
|-------------|-------------|-----|
| KPI at risk | `notif:at_risk:{target_id}` | 24 hours |
| Target achieved | `notif:achieved:{target_id}` | 72 hours |
| Entry reminder | `notif:reminder:{target_id}:{period}` | 7 days |
| Period closing | `notif:period_closing:{cycle_id}:{days}` | 24 hours |

If the key exists, `send_notification` silently returns `None` without writing a
new row.  This prevents duplicate rows in the database **and** duplicate alerts in
the user's feed.

### 2. User Preference First

Before creating any notification, the service calls
`get_or_create_preference(db, user_id)`.  If the user has opted out of a channel
for a given notification category, the notification is not created for that channel.
The user always has the final vote on what they receive.

### 3. Jobs Own Their Own Sessions

Each background job opens its own `AsyncSessionLocal()` session and does **not**
share state with the HTTP request context.  This is deliberate — jobs run outside
the HTTP request lifecycle and must be independently transactional.

### 4. Jobs Are Idempotent by Design

All six jobs are designed to be safe to re-run.  Running a job twice in the same
window produces the same outcome as running it once, because:
- Debounce keys prevent duplicate notifications.
- `auto_close_review_cycle_job` uses a `closed=True` guard before updating.
- `cleanup_expired_notifications_job` only deletes records that meet the criteria at run time.

### 5. Scheduler Is Disabled in DEBUG Mode

The scheduler only starts when `settings.DEBUG is False`.  This prevents unwanted
job firing during local development and test execution.

---

## External Dependencies

| Dependency | Purpose | Version |
|------------|---------|---------|
| `apscheduler` | Job scheduling with `AsyncIOScheduler` | 3.11.2 |
| `redis[asyncio]` | Async Redis client for debounce keys | ≥5.0 |
| `fakeredis` | In-memory Redis substitute used in tests | 2.35.1 |
| `smtplib` (stdlib) | Email delivery (email channel) | stdlib |
| `jinja2` | (Optional future) HTML email templating | — |

All other dependencies (SQLAlchemy, FastAPI, asyncpg, etc.) are shared with the
rest of the application.

---

## Integration Points

The notifications module **does not call** other modules via HTTP.  Instead,
other service layers (or the job functions) call `NotificationService` directly as
a Python object.  This keeps it fast (no network round-trip) and simple (no circular HTTP dependency).

The notification router imports `get_redis` from `app.main` so it can obtain the
live `redis.asyncio.Redis` connection that was initialised at application startup.
