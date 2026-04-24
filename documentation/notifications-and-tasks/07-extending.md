# 07 — Developer Guide: Extending the Module

This guide explains how to:
1. Add a new notification type
2. Add a new background job
3. Write tests for notifications and jobs
4. Disable specific jobs in development
5. Manually trigger jobs from the console

---

## Adding a New Notification Type

### Step 1: Add the enum value

Edit `app/notifications/enums.py`:

```python
class NotificationType(str, Enum):
    # ... existing values ...
    REVIEW_MEETING_SCHEDULED = "review_meeting_scheduled"  # ← new
```

### Step 2: Add the template

Edit `app/notifications/templates.py`:

```python
NOTIFICATION_TEMPLATES: dict[NotificationType, _TemplateFn] = {
    # ... existing entries ...

    NotificationType.REVIEW_MEETING_SCHEDULED: lambda ctx: (
        "Performance Review Meeting Scheduled",
        (
            f"Your performance review for {ctx.get('cycle_name', 'the current cycle')} "
            f"is scheduled for {ctx.get('meeting_date', 'soon')}. "
            f"Please come prepared to discuss your KPI results."
        ),
        f"/review-cycles/{ctx.get('cycle_id')}",
    ),
}
```

### Step 3: Add the preference flag (if user-configurable)

Edit `app/notifications/models.py` — add a Boolean column:

```python
class NotificationPreference(Base):
    # ... existing columns ...
    review_meetings_in_app: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    review_meetings_email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
```

Edit `app/notifications/schemas.py` — add to `NotificationPreferenceRead` and
`NotificationPreferenceUpdate`:

```python
class NotificationPreferenceRead(BaseModel):
    # ... existing fields ...
    review_meetings_in_app: bool
    review_meetings_email: bool

class NotificationPreferenceUpdate(BaseModel):
    # ... existing fields ...
    review_meetings_in_app: Optional[bool] = None
    review_meetings_email: Optional[bool] = None
```

Edit `app/notifications/service.py` — add the type to the `_channel_enabled` mapping:

```python
mapping: dict[NotificationType, tuple[bool, bool]] = {
    # ... existing entries ...
    NotificationType.REVIEW_MEETING_SCHEDULED: (
        prefs.review_meetings_in_app,
        prefs.review_meetings_email,
    ),
}
```

### Step 4: Create an Alembic migration

```bash
alembic revision --autogenerate -m "add_review_meeting_notification_type"
```

Verify the generated migration file looks correct, then:

```bash
alembic upgrade head
```

> **Note**: Adding a value to a PostgreSQL ENUM requires `ALTER TYPE ... ADD VALUE`.
> SQLAlchemy's autogenerate will NOT detect this — you must write the SQL manually
> in the migration:
> ```python
> # In the generated migration file:
> def upgrade() -> None:
>     op.execute("ALTER TYPE notificationtype ADD VALUE 'review_meeting_scheduled'")
>     op.add_column('notification_preferences',
>         sa.Column('review_meetings_in_app', sa.Boolean(), nullable=False, server_default='true'))
>     op.add_column('notification_preferences',
>         sa.Column('review_meetings_email', sa.Boolean(), nullable=False, server_default='true'))
>
> def downgrade() -> None:
>     op.drop_column('notification_preferences', 'review_meetings_in_app')
>     op.drop_column('notification_preferences', 'review_meetings_email')
>     # NOTE: PostgreSQL does not support removing ENUM values.
>     # To fully roll back, you must recreate the enum without this value.
> ```

### Step 5: Call `create_notification` where the event occurs

From a service layer or job:

```python
from app.notifications.enums import NotificationType
from app.notifications.service import NotificationService

svc = NotificationService(redis_client)
await svc.create_notification(
    db=db,
    recipient_id=employee_id,
    org_id=org_id,
    notification_type=NotificationType.REVIEW_MEETING_SCHEDULED,
    context={
        "cycle_name": cycle.name,
        "cycle_id": str(cycle.id),
        "meeting_date": "2025-04-10 14:00 UTC",
    },
)
```

### Step 6: Add tests

```python
# tests/test_notifications.py  (add to Part A)
async def test_review_meeting_notification_created(db_session, fake_redis, notif_user):
    svc = NotificationService(fake_redis)
    notif = await svc.create_notification(
        db_session,
        recipient_id=notif_user.id,
        org_id=notif_user.organisation_id,
        notification_type=NotificationType.REVIEW_MEETING_SCHEDULED,
        context={"cycle_name": "Q1 2025", "cycle_id": "fake-id", "meeting_date": "2025-04-10"},
    )
    assert notif is not None
    assert notif.notification_type == NotificationType.REVIEW_MEETING_SCHEDULED
    assert "Q1 2025" in notif.title or "Q1 2025" in notif.body
```

---

## Adding a New Background Job

### Step 1: Write the job function

Add to `app/tasks/jobs.py`:

```python
async def send_review_meeting_reminders_job() -> None:
    """
    Remind employees of upcoming review meetings.
    """
    from sqlalchemy import select
    from app.reviews.models import ReviewMeeting  # hypothetical model

    SessionLocal = _get_session_factory()
    svc = _get_notification_service()
    today = date.today()

    try:
        async with SessionLocal() as db:
            # Fetch meetings scheduled for tomorrow
            from datetime import timedelta
            tomorrow = today + timedelta(days=1)
            meetings_result = await db.execute(
                select(ReviewMeeting).where(ReviewMeeting.scheduled_date == tomorrow)
            )
            meetings = meetings_result.scalars().all()

            for meeting in meetings:
                await svc.create_notification(
                    db,
                    recipient_id=meeting.employee_id,
                    org_id=meeting.organisation_id,
                    notification_type=NotificationType.REVIEW_MEETING_SCHEDULED,
                    context={...},
                )

            await db.commit()

        logger.info("send_review_meeting_reminders_job: meetings_notified=%d", len(meetings))

    except Exception:
        logger.exception("send_review_meeting_reminders_job failed")
```

**Required pattern checklist for every new job**:
- [ ] Uses `_get_session_factory()` and `_get_notification_service()` helpers
- [ ] Opens its own `AsyncSessionLocal()` session with `async with`
- [ ] Calls `await db.commit()` inside the try block after all writes
- [ ] Wraps everything in `try: ... except Exception: logger.exception(...)`
- [ ] Logs a summary metric line after a successful run
- [ ] Does NOT take any arguments (APScheduler calls it with no arguments)

### Step 2: Register the job

Edit `app/tasks/registry.py`:

```python
from app.tasks.jobs import (
    # ... existing imports ...
    send_review_meeting_reminders_job,  # ← new
)

def register_jobs(scheduler: AsyncIOScheduler) -> None:
    # ... existing jobs ...

    scheduler.add_job(
        send_review_meeting_reminders_job,
        CronTrigger(hour=8, minute=0),           # Daily at 08:00 UTC
        id="review_meeting_reminders",
        name="Review Meeting Reminders",
        replace_existing=True,
        misfire_grace_time=3600,
    )
```

### Step 3: Add to the task router's registry

Edit `app/tasks/router.py`:

```python
_JOB_REGISTRY: dict[str, str] = {
    # ... existing entries ...
    "review_meeting_reminders": "app.tasks.jobs.send_review_meeting_reminders_job",
}
```

This makes the job manually triggerable via `POST /api/v1/tasks/run/review_meeting_reminders`.

### Step 4: Add tests

```python
# tests/test_tasks.py  (add to Part B)
async def test_review_meeting_reminder_job(db_session, fake_redis):
    with patch("app.tasks.jobs._get_redis", return_value=fake_redis), \
         patch("app.database.AsyncSessionLocal", new=TestSessionLocal):
        await send_review_meeting_reminders_job()
    # Assert: check that the relevant notifications were created
    from sqlalchemy import select
    async with TestSessionLocal() as db:
        result = await db.execute(select(Notification))
        notifs = result.scalars().all()
    # ... assertions ...
```

---

## Testing Guide

### Test Setup Overview

The test suite uses:
- **SQLite (via `aiosqlite`)** with a **named shared-memory URI** so that the
  `setup_db` session-scoped fixture and per-test function-scoped sessions share
  the same in-memory database.
- **`fakeredis.aioredis.FakeRedis()`** as a drop-in replacement for Redis.
- The `patch("app.main.get_redis", return_value=fake_redis)` pattern for HTTP
  endpoint tests.
- The `patch("app.database.AsyncSessionLocal", new=TestSessionLocal)` pattern
  for job unit tests.

### Running the Tests

```bash
# Run all tests
cd pms-backend
python -m pytest tests/ -v

# Run only notification tests
python -m pytest tests/test_notifications.py -v

# Run only task tests
python -m pytest tests/test_tasks.py -v

# Run with coverage
python -m pytest tests/ --cov=app --cov-report=term-missing
```

### Writing a New Notification Test (Part A — Service)

```python
import uuid
import pytest
import fakeredis.aioredis
from app.notifications.enums import NotificationType
from app.notifications.service import NotificationService

@pytest.fixture
def fake_redis():
    return fakeredis.aioredis.FakeRedis()

@pytest.fixture
async def notif_user(db_session):
    """Create a test user with no FK constraint on organisation_id."""
    from app.users.models import User, UserRole
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex[:8]}@test.com",
        full_name="Test User",
        role=UserRole.employee,
        organisation_id=uuid.uuid4(),  # SQLite doesn't enforce FK
        hashed_password="x",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user

async def test_create_my_notification(db_session, fake_redis, notif_user):
    svc = NotificationService(fake_redis)
    notif = await svc.create_notification(
        db_session,
        recipient_id=notif_user.id,
        org_id=notif_user.organisation_id,
        notification_type=NotificationType.SCORE_FINALISED,
        context={"cycle_name": "Q1", "cycle_id": "some-id"},
    )
    assert notif.notification_type == NotificationType.SCORE_FINALISED
    assert notif.status.value == "unread"
```

### Writing a New Notification Test (Part B — HTTP)

```python
@pytest.mark.asyncio
async def test_my_endpoint(async_client, test_user_token, fake_redis):
    with patch("app.main.get_redis", return_value=fake_redis):
        response = await async_client.get(
            "/api/v1/notifications/",
            headers={"Authorization": f"Bearer {test_user_token}"},
        )
    assert response.status_code == 200
```

### Writing a New Job Test

```python
@pytest.mark.asyncio
async def test_my_job_does_something(db_session, fake_redis):
    # 1. Seed the database
    # ...

    # 2. Run the job with patched dependencies
    with patch("app.tasks.jobs._get_redis", return_value=fake_redis), \
         patch("app.database.AsyncSessionLocal", new=TestSessionLocal):
        await my_new_job()

    # 3. Assert side effects
    async with TestSessionLocal() as db:
        result = await db.execute(select(SomeModel).where(...))
        assert result.scalar_one_or_none() is not None
```

---

## Disabling Specific Jobs in Development

To prevent a specific job from running without removing it from the registry,
you can use the APScheduler `pause_job` method:

```python
# In app/tasks/scheduler.py or a startup hook:
from app.tasks.scheduler import scheduler

scheduler.pause_job("formula_actuals")  # Prevents this job from running
```

Or conditionally in `register_jobs`:

```python
import os

def register_jobs(scheduler: AsyncIOScheduler) -> None:
    # ... add all jobs first ...

    # Disable specific jobs in development
    if os.getenv("DISABLE_JOBS", "").split(","):
        for job_id in os.getenv("DISABLE_JOBS", "").split(","):
            try:
                scheduler.pause_job(job_id.strip())
            except Exception:
                pass
```

Then set in `.env`:
```env
DISABLE_JOBS=formula_actuals,auto_close_cycle
```

---

## Triggering Jobs from a Python Script

Useful for one-off manual runs in production without going through the HTTP API:

```python
# scripts/run_job.py
import asyncio
import sys

async def main():
    job_name = sys.argv[1]
    from app.tasks import jobs
    fn = getattr(jobs, job_name)
    await fn()

if __name__ == "__main__":
    asyncio.run(main())
```

Run:
```bash
cd pms-backend
python scripts/run_job.py cleanup_expired_notifications_job
```

> **Note**: This script will read the real `DATABASE_URL` and `REDIS_URL` from
> the environment.  Ensure you have the correct `.env` file loaded before running.

---

## Making Debounce TTLs Configurable

Currently the TTLs are hardcoded constants.  To make them configurable via
environment variables:

**1. Add to `app/config.py`**:

```python
class Settings(BaseSettings):
    # ... existing ...
    NOTIF_AT_RISK_DEBOUNCE_HOURS: int = 24
    NOTIF_ACHIEVED_DEBOUNCE_HOURS: int = 72
    NOTIF_REMINDER_DEBOUNCE_DAYS: int = 7
    NOTIF_PERIOD_CLOSING_DEBOUNCE_HOURS: int = 24
```

**2. Update `app/notifications/service.py`**:

```python
class NotificationService:
    def __init__(self, redis: aioredis.Redis) -> None:
        self._redis = redis
        from app.config import get_settings
        s = get_settings()
        self._at_risk_ttl = s.NOTIF_AT_RISK_DEBOUNCE_HOURS * 3600
        self._achieved_ttl = s.NOTIF_ACHIEVED_DEBOUNCE_HOURS * 3600
        self._reminder_ttl = s.NOTIF_REMINDER_DEBOUNCE_DAYS * 86400
        self._period_closing_ttl = s.NOTIF_PERIOD_CLOSING_DEBOUNCE_HOURS * 3600
```

Then replace the module-level constants with `self._at_risk_ttl` etc.

---

## Module File Quick Reference

| File | What to edit | When |
|------|-------------|------|
| `app/notifications/enums.py` | Add enum values | Every new notification type |
| `app/notifications/templates.py` | Add template lambda | Every new notification type |
| `app/notifications/models.py` | Add preference columns | New configurable notification types |
| `app/notifications/schemas.py` | Add schema fields | After every model change |
| `app/notifications/service.py` | Update `_channel_enabled` mapping | After every new type |
| `app/tasks/jobs.py` | Add job function | Every new background job |
| `app/tasks/registry.py` | Register with APScheduler | Every new background job |
| `app/tasks/router.py` | Add to `_JOB_REGISTRY` | Every new background job |
| `alembic/versions/` | New migration file | After any model change |
| `tests/test_notifications.py` | Add tests | After every change |
| `tests/test_tasks.py` | Add tests | After every new job |
