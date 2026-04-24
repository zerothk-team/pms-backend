# Notifications & Background Tasks — Documentation Index

> **Version**: Part 5 | **Backend**: FastAPI + SQLAlchemy 2.x async + PostgreSQL + Redis + APScheduler
> **Base URL**: `http://localhost:8000/api/v1`

This is the root navigation page for all documentation covering the **Notifications module** and the **Background Tasks module** of the Performance Management System.

---

## Table of Contents

| # | Document | What it covers |
|---|----------|----------------|
| 1 | [Module Overview](01-overview.md) | Purpose, architecture, module boundaries, file structure, dependencies |
| 2 | [Data Models & Database Schema](02-data-models.md) | `notifications` and `notification_preferences` tables, columns, indexes, enums |
| 3 | [Notification Types](03-notification-types.md) | All 12 types with business purpose, template rendering, debounce behaviour |
| 4 | [API Reference](04-api-reference.md) | All 9 endpoints: method, path, roles, request/response shapes, error codes |
| 5 | [Background Jobs](05-background-jobs.md) | 6 scheduled jobs with cron triggers, business rules, and failure handling |
| 6 | [Configuration Guide](06-configuration.md) | Redis, SMTP, scheduler on/off, environment variables |
| 7 | [Developer Guide — Extending the Module](07-extending.md) | Adding notification types, adding jobs, testing with FakeRedis, manual triggering |

---

## Quick Navigation by Task

### "I want to..."

| Task | Go to |
|------|-------|
| Understand why this module exists and how it fits the system | [01 — Overview](01-overview.md) |
| Understand the database tables and column definitions | [02 — Data Models](02-data-models.md) |
| Know what each of the 12 notification types means and when it fires | [03 — Notification Types](03-notification-types.md) |
| Find exact request/response shapes for the notification API | [04 — API Reference](04-api-reference.md) |
| Understand when and how each background job fires | [05 — Background Jobs](05-background-jobs.md) |
| Configure SMTP, Redis URL or enable/disable the scheduler | [06 — Configuration](06-configuration.md) |
| Add a new notification type or a new scheduled job | [07 — Developer Guide](07-extending.md) |

---

## Roles Referenced Throughout

| Role | Value | Capabilities |
|------|-------|--------------|
| HR Admin | `hr_admin` | Read and manage all notifications for their own account; manually trigger jobs |
| Manager | `manager` | Read and manage notifications for their own account |
| Employee | `employee` | Read and manage notifications for their own account |
| Any (authenticated) | — | Access to all notification CRUD endpoints for own notifications |

> The task management endpoints (`/tasks/`) are **HR Admin only**.

---

## Module Summary

The **Notifications module** (`app/notifications/`) provides an in-app notification feed
and optional email delivery for key system events.  It stores one `Notification` row
per delivery channel per event and respects per-user preferences to opt-out of
specific channels or notification categories.

The **Tasks module** (`app/tasks/`) schedules six background jobs using
**APScheduler** that automate recurring work:
- Proactive at-risk alerts
- Overdue data-entry reminders
- Period-closing warnings
- Auto-computation of formula-based actuals
- Automatic cycle closure and scoring
- Expired notification cleanup

Both modules are designed to be **non-blocking** — all operations are async, all
jobs catch and log exceptions rather than crashing the application.
