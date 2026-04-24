# 02 — Data Models & Database Schema

## Entity-Relationship Overview

```
users (existing)
  │ 1
  │ ───────────────────────────────────────┐
  │ 1                                      │
  ▼ N                                      ▼ 1
notifications                     notification_preferences
  (one row per                       (one row per user;
   notification event)               created on first access)
```

---

## Table: `notifications`

Stores one row per delivered notification.  If both IN_APP and EMAIL channels are
active for the same event, two rows are written (one per channel).

### Column Reference

| Column | SQLAlchemy type | Python type | Nullable | Default | Notes |
|--------|-----------------|-------------|----------|---------|-------|
| `id` | `UUID` | `uuid.UUID` | No | `uuid4()` | Primary key |
| `recipient_id` | `UUID` | `uuid.UUID` | No | — | FK → `users.id` (cascade delete) |
| `organisation_id` | `UUID` | `uuid.UUID` | No | — | For row-level security / scoping |
| `notification_type` | `SAEnum(NotificationType)` | `NotificationType` | No | — | One of 12 values — see enums below |
| `channel` | `SAEnum(NotificationChannel)` | `NotificationChannel` | No | — | `in_app` or `email` |
| `status` | `SAEnum(NotificationStatus)` | `NotificationStatus` | No | `'unread'` | `unread`, `read`, or `dismissed` |
| `title` | `String(200)` | `str` | No | — | Short display title rendered from template |
| `body` | `Text` | `str` | No | — | Full notification body text rendered from template |
| `action_url` | `String(500)` | `str` | Yes | `NULL` | Optional deep-link URL (e.g. `/targets/abc`) |
| `metadata_` | `JSON` | `dict` | Yes | `NULL` | Arbitrary key-value context data |
| `sent_at` | `DateTime(timezone=True)` | `datetime` | No | `now()` | When the notification was created |
| `read_at` | `DateTime(timezone=True)` | `datetime` | Yes | `NULL` | Set when user reads or marks as read |
| `expires_at` | `DateTime(timezone=True)` | `datetime` | Yes | `NULL` | Cleanup job deletes rows past this date |
| `created_at` | `DateTime(timezone=True)` | `datetime` | No | `now()` | Insert timestamp (immutable) |

### Indexes

| Index name | Columns | Purpose |
|------------|---------|---------|
| `ix_notifications_recipient_id` | `recipient_id` | List feed for a user |
| `ix_notifications_organisation_id` | `organisation_id` | Organisation-scoped queries |
| `ix_notifications_status` | `status` | Filter by `unread` efficiently |

### Constraints

- `recipient_id` has a foreign key to `users.id` with `ON DELETE CASCADE` — deleting a user also deletes all their notifications.
- `notification_type`, `channel`, and `status` are PostgreSQL native ENUM types.

### ORM definition (excerpt)

```python
class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recipient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    organisation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    notification_type: Mapped[NotificationType] = mapped_column(SAEnum(NotificationType, name="notificationtype"), nullable=False)
    channel: Mapped[NotificationChannel] = mapped_column(SAEnum(NotificationChannel, name="notificationchannel"), nullable=False)
    status: Mapped[NotificationStatus] = mapped_column(SAEnum(NotificationStatus, name="notificationstatus"), nullable=False, default=NotificationStatus.UNREAD, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    action_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
```

> **Note on `metadata_`**: The column is named `metadata_` in Python to avoid shadowing SQLAlchemy's internal `metadata` attribute.  The actual database column name is `metadata`.

---

## Table: `notification_preferences`

Stores one row per user (created lazily on first access via `get_or_create_preference`).
All boolean columns default to `True` (all notifications on).

### Column Reference

| Column | SQLAlchemy type | Python type | Nullable | Default | Notes |
|--------|-----------------|-------------|----------|---------|-------|
| `id` | `UUID` | `uuid.UUID` | No | `uuid4()` | Primary key |
| `user_id` | `UUID` | `uuid.UUID` | No | — | FK → `users.id` (cascade delete); unique |
| `in_app_enabled` | `Boolean` | `bool` | No | `True` | Master switch for in-app channel |
| `email_enabled` | `Boolean` | `bool` | No | `True` | Master switch for email channel |
| `kpi_at_risk` | `Boolean` | `bool` | No | `True` | Receive KPI_AT_RISK and TEAM_KPI_AT_RISK |
| `entry_reminders` | `Boolean` | `bool` | No | `True` | Receive ACTUAL_ENTRY_DUE |
| `target_acknowledgement` | `Boolean` | `bool` | No | `True` | Receive TARGET_ACKNOWLEDGEMENT_DUE |
| `period_closing` | `Boolean` | `bool` | No | `True` | Receive PERIOD_CLOSING_SOON |
| `approvals` | `Boolean` | `bool` | No | `True` | Receive APPROVAL_PENDING |
| `achievements` | `Boolean` | `bool` | No | `True` | Receive TARGET_ACHIEVED, STRETCH_TARGET_ACHIEVED |
| `scoring_updates` | `Boolean` | `bool` | No | `True` | Receive SCORING_COMPLETE, SCORE_FINALISED, SCORE_ADJUSTED |
| `calibration` | `Boolean` | `bool` | No | `True` | Receive CALIBRATION_REQUIRED |
| `period_closing_days_before` | `Integer` | `int` | No | `3` | How many days before period end to send closing reminder |
| `email_digest_frequency` | `String(20)` | `str` | No | `'immediate'` | `immediate`, `daily`, or `weekly` |
| `created_at` | `DateTime(timezone=True)` | `datetime` | No | `now()` | Insert timestamp |
| `updated_at` | `DateTime(timezone=True)` | `datetime` | No | `now()` | Updated on every PUT request |

### Constraints

- `user_id` is a **UNIQUE** foreign key to `users.id` with `ON DELETE CASCADE`.
- One row per user, enforced at the database level by the unique constraint.

### ORM definition (excerpt)

```python
class NotificationPreference(Base):
    __tablename__ = "notification_preferences"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    in_app_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    email_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    kpi_at_risk: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    entry_reminders: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # ... (other bool flags)
    period_closing_days_before: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    email_digest_frequency: Mapped[str] = mapped_column(String(20), nullable=False, default="immediate")
```

---

## Enum Types

All three enums live in `app/notifications/enums.py` and map to **PostgreSQL native ENUM** types via Alembic.

### `NotificationType`

```python
class NotificationType(str, Enum):
    KPI_AT_RISK = "kpi_at_risk"
    TEAM_KPI_AT_RISK = "team_kpi_at_risk"
    ACTUAL_ENTRY_DUE = "actual_entry_due"
    TARGET_ACKNOWLEDGEMENT_DUE = "target_acknowledgement_due"
    PERIOD_CLOSING_SOON = "period_closing_soon"
    APPROVAL_PENDING = "approval_pending"
    TARGET_ACHIEVED = "target_achieved"
    STRETCH_TARGET_ACHIEVED = "stretch_target_achieved"
    SCORING_COMPLETE = "scoring_complete"
    CALIBRATION_REQUIRED = "calibration_required"
    SCORE_FINALISED = "score_finalised"
    SCORE_ADJUSTED = "score_adjusted"
```

### `NotificationChannel`

```python
class NotificationChannel(str, Enum):
    IN_APP = "in_app"
    EMAIL = "email"
```

### `NotificationStatus`

```python
class NotificationStatus(str, Enum):
    UNREAD = "unread"
    READ = "read"
    DISMISSED = "dismissed"
```

---

## Alembic Migration

Migration file: `alembic/versions/d4e5f6a7b8c9_create_notification_tables.py`

This migration:
1. Creates PostgreSQL ENUM types: `notificationtype`, `notificationchannel`, `notificationstatus`
2. Creates table `notifications` with all columns and indexes
3. Creates table `notification_preferences` with all columns and unique constraint
4. Chains from migration `c3d4e5f6a7b8_create_scoring_tables.py`

To apply:
```bash
alembic upgrade head
```

To roll back:
```bash
alembic downgrade c3d4e5f6a7b8
```

> **Important**: The `down_revision` is `c3d4e5f6a7b8`, so rolling back notifications also removes both tables and the three ENUM types.

---

## Row Lifecycle

### `notifications` rows

```
INSERT (status=UNREAD, sent_at=now)
        │
        ├── User views feed ──► PATCH /{id}/read  (status=READ, read_at=now)
        │
        ├── User dismisses  ──► DELETE /{id}      (row hard-deleted)
        │
        └── Job runs weekly ──► cleanup job deletes READ/DISMISSED rows
                                older than 30 days, or past expires_at
```

### `notification_preferences` rows

```
First time user calls GET /notifications/preferences/
        │
        └── get_or_create_preference() inserts a row with all defaults
                │
                └── Subsequent PUT /notifications/preferences/ updates the row
```
