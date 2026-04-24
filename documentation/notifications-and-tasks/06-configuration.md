# 06 — Configuration Guide

This document covers all environment variables and configuration settings that
affect the Notifications and Background Tasks modules.

---

## Environment Variables

Settings are loaded from the `.env` file (or real environment variables) via
`pydantic-settings`.  The settings class is `app/config.py`.

### Redis

| Variable | Default | Required in prod | Description |
|----------|---------|-----------------|-------------|
| `REDIS_URL` | `redis://localhost:6379/0` | Yes | Full Redis connection URL including DB index |

**Examples**:
```env
# Local development
REDIS_URL=redis://localhost:6379/0

# Redis with auth (production)
REDIS_URL=redis://:yourpassword@redis.example.com:6379/0

# Redis with TLS (production)
REDIS_URL=rediss://:yourpassword@redis.example.com:6380/0

# Upstash Redis (serverless)
REDIS_URL=rediss://default:yourtoken@global.upstash.io:6380/0
```

**How it's used**: The FastAPI lifespan hook in `app/main.py` creates a
`redis.asyncio.Redis` client from this URL.  The client is stored as an
application state variable and injected into `NotificationService` via `get_redis()`.

> **Important**: If `REDIS_URL` is unreachable at startup, the application will
> raise a `RuntimeError` from `get_redis()` on the first notification attempt.
> Redis is NOT required for the application to boot, but IS required for any
> notification functionality to work.

---

### SMTP (Email Notifications)

| Variable | Default | Description |
|----------|---------|-------------|
| `SMTP_HOST` | `localhost` | Hostname of the SMTP relay |
| `SMTP_PORT` | `587` | SMTP port (587 = STARTTLS, 465 = implicit TLS, 25 = plain) |
| `SMTP_USER` | `""` | SMTP authentication username |
| `SMTP_PASSWORD` | `""` | SMTP authentication password |
| `SMTP_USE_TLS` | `True` | Whether to use STARTTLS |
| `SMTP_FROM_ADDRESS` | `noreply@pms.example.com` | Sender address for all outbound email |

**Example production configuration (AWS SES)**:
```env
SMTP_HOST=email-smtp.eu-west-1.amazonaws.com
SMTP_PORT=587
SMTP_USER=AKIAYOURKEY
SMTP_PASSWORD=yourSESsmtpPassword
SMTP_USE_TLS=True
SMTP_FROM_ADDRESS=notifications@yourcompany.com
```

**Example for SendGrid**:
```env
SMTP_HOST=smtp.sendgrid.net
SMTP_PORT=587
SMTP_USER=apikey
SMTP_PASSWORD=SG.yoursendgridapikey
SMTP_USE_TLS=True
SMTP_FROM_ADDRESS=notifications@yourcompany.com
```

**In DEBUG mode**: The email sending function logs the email to the console
instead of sending it via SMTP.  No valid SMTP credentials are needed during
development.

---

### Scheduler

| Variable | Default | Description |
|----------|---------|-------------|
| `DEBUG` | `False` | When `True`, the APScheduler is **not started** |

The scheduler on/off switch is tied to `DEBUG` mode.  This is intentional:
- In local development (`DEBUG=True`), jobs don't fire unexpectedly.
- In testing, `DEBUG=True` ensures jobs never fire during test runs.
- In production, `DEBUG=False` (or omitted) activates the scheduler.

**To run with the scheduler in development** (e.g., to test job logic):
```bash
DEBUG=False uvicorn app.main:app --reload
```

Or set in `.env`:
```env
DEBUG=False
```

> **Warning**: If you set `DEBUG=False` in development and have a real database
> with test data, background jobs will actually run and send notifications/emails.

---

### Database

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://postgres@localhost:5432/pms_db` | Async database URL |

This is used by all modules including jobs, which create their own sessions
via `AsyncSessionLocal`.

---

## Full `.env` Example

```env
# App
APP_NAME="Performance Management System"
APP_VERSION="1.0.0"
DEBUG=False
API_V1_PREFIX=/api/v1

# Database
DATABASE_URL=postgresql+asyncpg://pmsuser:securepassword@db.example.com:5432/pms_db
DATABASE_POOL_SIZE=10
DATABASE_MAX_OVERFLOW=20

# Redis
REDIS_URL=redis://:redispassword@redis.example.com:6379/0

# JWT
JWT_SECRET_KEY=your-256-bit-random-string-here
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7

# CORS
CORS_ORIGINS=["https://app.yourcompany.com", "https://admin.yourcompany.com"]

# SMTP
SMTP_HOST=smtp.sendgrid.net
SMTP_PORT=587
SMTP_USER=apikey
SMTP_PASSWORD=SG.your-sendgrid-api-key
SMTP_USE_TLS=True
SMTP_FROM_ADDRESS=notifications@yourcompany.com
```

---

## Docker / Container Configuration

For container deployments, pass environment variables directly rather than using
`.env` files:

```yaml
# docker-compose.yml
services:
  api:
    image: pms-backend:latest
    environment:
      - DEBUG=False
      - DATABASE_URL=postgresql+asyncpg://pmsuser:pw@postgres:5432/pms_db
      - REDIS_URL=redis://redis:6379/0
      - JWT_SECRET_KEY=${JWT_SECRET_KEY}
      - SMTP_HOST=smtp.sendgrid.net
      - SMTP_PORT=587
      - SMTP_USER=apikey
      - SMTP_PASSWORD=${SENDGRID_API_KEY}
      - SMTP_FROM_ADDRESS=notifications@yourcompany.com
```

---

## Security Considerations

1. **JWT_SECRET_KEY** must be at least 32 random bytes.  Never use the default
   value `"change-me-to-a-long-random-string-in-production"` in production.
   Generate with: `openssl rand -hex 32`

2. **SMTP_PASSWORD** must be stored as a secret, not in `.env` files committed
   to source control.  Use your CI/CD secret manager or secrets vault.

3. **Redis URL** with password — use `rediss://` (double-s) for TLS-encrypted
   connections.  Never send Redis traffic unencrypted over a public network.

4. **CORS_ORIGINS** — restrict to your actual front-end domains.  The wildcard
   `*` must never be used in production.

---

## Changing Job Schedules

Job schedules are defined in `app/tasks/registry.py`.  To change a schedule,
edit the `CronTrigger` arguments and redeploy.

**Example** — run the at-risk check every 4 hours instead of daily:

```python
# app/tasks/registry.py  (before)
scheduler.add_job(
    check_at_risk_kpis_job,
    CronTrigger(hour=8, minute=0),
    id="check_at_risk_kpis",
    ...
)

# app/tasks/registry.py  (after)
scheduler.add_job(
    check_at_risk_kpis_job,
    CronTrigger(hour="8,12,16,20", minute=0),
    id="check_at_risk_kpis",
    ...
)
```

CronTrigger arguments follow standard cron syntax.  See
[APScheduler docs](https://apscheduler.readthedocs.io/en/3.x/modules/triggers/cron.html)
for full details.

---

## Notification Debounce TTLs

Debounce TTLs are constants in `app/notifications/service.py`.  They are not
configurable via environment variables by default but can be changed by editing
the constants:

```python
# app/notifications/service.py
_AT_RISK_DEBOUNCE_TTL = 86400          # 24 hours
_ACHIEVED_DEBOUNCE_TTL = 259200        # 72 hours
_REMINDER_DEBOUNCE_TTL = 604800        # 7 days
_PERIOD_CLOSING_DEBOUNCE_TTL = 86400   # 24 hours
```

> **Tip**: If you want to make TTLs configurable, add them to `Settings` in
> `config.py` and read them in `NotificationService.__init__`.  See
> [Developer Guide](07-extending.md) for how to do this.
