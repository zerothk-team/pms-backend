"""
NotificationService — all notification business logic.

Design decisions:
- Debouncing is enforced via Redis keys to prevent flooding users with the
  same alert.  Redis is used rather than a DB flag so that debounce keys expire
  automatically without a cleanup job.
- Preferences are read lazily: if no preference row exists for a user, a
  default one is created on-the-fly.
- send_email() is intentionally stubbed in development (logs to console).
  In production, replace the body with aiosmtplib / SendGrid calls using
  the SMTP settings from app.config.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

import redis.asyncio as aioredis
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ForbiddenException, NotFoundException
from app.notifications.enums import NotificationChannel, NotificationStatus, NotificationType
from app.notifications.models import Notification, NotificationPreference
from app.notifications.templates import render_notification

logger = logging.getLogger("pms.notifications")

# ---------------------------------------------------------------------------
# Redis TTLs for debounce keys (in seconds)
# ---------------------------------------------------------------------------
_DEBOUNCE_AT_RISK_TTL = 86_400        # 24 h
_DEBOUNCE_ACHIEVED_TTL = 259_200      # 72 h
_DEBOUNCE_REMINDER_TTL = 604_800      # 7 days
_DEBOUNCE_PERIOD_CLOSING_TTL = 86_400  # 24 h (per cycle per days_until_close value)


def _redis_key_at_risk(target_id: UUID) -> str:
    return f"notif:at_risk:{target_id}"


def _redis_key_achieved(target_id: UUID) -> str:
    return f"notif:achieved:{target_id}"


def _redis_key_reminder(target_id: UUID, period_date: date) -> str:
    return f"notif:reminder:{target_id}:{period_date.isoformat()}"


def _redis_key_period_closing(cycle_id: UUID, days: int) -> str:
    return f"notif:period_closing:{cycle_id}:{days}"


# ---------------------------------------------------------------------------
# Email stub
# ---------------------------------------------------------------------------


async def send_email(to: str, subject: str, body: str) -> None:
    """
    Send (or stub) an email notification.

    Development: logs to console with an [EMAIL] prefix.
    Production: replace this implementation with aiosmtplib or SendGrid.
    """
    from app.config import settings

    if settings.DEBUG:
        logger.info("[EMAIL] To=%s | Subject=%s | Body=%s", to, subject, body[:120])
        return

    # Production: use aiosmtplib
    try:
        import aiosmtplib
        import email.mime.text as _mime

        message = _mime.MIMEText(body, "plain")
        message["Subject"] = subject
        message["From"] = settings.SMTP_FROM_ADDRESS
        message["To"] = to
        await aiosmtplib.send(
            message,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER or None,
            password=settings.SMTP_PASSWORD or None,
            use_tls=settings.SMTP_USE_TLS,
        )
    except Exception:
        logger.exception("Failed to send email to %s — subject: %s", to, subject)


# ---------------------------------------------------------------------------
# Preference helper
# ---------------------------------------------------------------------------


def _channel_enabled(
    prefs: NotificationPreference,
    notification_type: NotificationType,
    channel: NotificationChannel,
) -> bool:
    """Return True if the user's preference allows this type+channel combination."""
    in_app = channel == NotificationChannel.IN_APP
    mapping: dict[NotificationType, tuple[bool, bool]] = {
        NotificationType.KPI_AT_RISK: (prefs.kpi_at_risk_in_app, prefs.kpi_at_risk_email),
        NotificationType.TEAM_KPI_AT_RISK: (prefs.kpi_at_risk_in_app, prefs.kpi_at_risk_email),
        NotificationType.ACTUAL_ENTRY_DUE: (prefs.actual_due_in_app, prefs.actual_due_email),
        NotificationType.TARGET_ACKNOWLEDGEMENT_DUE: (
            prefs.actual_due_in_app, prefs.actual_due_email
        ),
        NotificationType.PERIOD_CLOSING_SOON: (
            prefs.period_closing_in_app, prefs.period_closing_email
        ),
        NotificationType.APPROVAL_PENDING: (True, False),  # always in-app only
        NotificationType.TARGET_ACHIEVED: (
            prefs.target_achieved_in_app, prefs.target_achieved_email
        ),
        NotificationType.STRETCH_TARGET_ACHIEVED: (
            prefs.target_achieved_in_app, prefs.target_achieved_email
        ),
        NotificationType.SCORING_COMPLETE: (True, False),
        NotificationType.CALIBRATION_REQUIRED: (True, True),
        NotificationType.SCORE_FINALISED: (
            prefs.score_finalised_in_app, prefs.score_finalised_email
        ),
        NotificationType.SCORE_ADJUSTED: (
            prefs.score_adjusted_in_app, prefs.score_adjusted_email
        ),
    }
    pair = mapping.get(notification_type, (True, True))
    return pair[0] if in_app else pair[1]


# ---------------------------------------------------------------------------
# NotificationService
# ---------------------------------------------------------------------------


class NotificationService:
    """Business logic for creating, querying and managing notifications."""

    def __init__(self, redis: aioredis.Redis) -> None:
        self._redis = redis

    # ------------------------------------------------------------------
    # Core create
    # ------------------------------------------------------------------

    async def create_notification(
        self,
        db: AsyncSession,
        recipient_id: UUID,
        org_id: UUID,
        notification_type: NotificationType,
        context: dict,
        channel: NotificationChannel = NotificationChannel.IN_APP,
        metadata: dict | None = None,
        expires_at: datetime | None = None,
    ) -> Notification | None:
        """
        Create and store a notification.

        Steps:
        1. Render title + body + action_url from template.
        2. Load user preferences — skip if this channel is disabled.
        3. Insert Notification row.
        4. If channel=EMAIL, trigger send_email().
        5. Return the notification, or None if skipped.
        """
        # 1. Render content
        title, body, action_url = render_notification(notification_type, context)

        # 2. Check preferences
        prefs = await self.get_or_create_preference(db, recipient_id, org_id)
        if not _channel_enabled(prefs, notification_type, channel):
            logger.debug(
                "Notification suppressed by preference: user=%s type=%s channel=%s",
                recipient_id,
                notification_type,
                channel,
            )
            return None

        # 3. Insert row
        now = datetime.now(timezone.utc)
        notification = Notification(
            recipient_id=recipient_id,
            organisation_id=org_id,
            notification_type=notification_type,
            channel=channel,
            status=NotificationStatus.UNREAD,
            title=title,
            body=body,
            action_url=action_url,
            metadata_=metadata,
            expires_at=expires_at,
            sent_at=now if channel == NotificationChannel.IN_APP else None,
        )
        db.add(notification)
        await db.flush()  # get the id before potential email call

        # 4. Email dispatch
        if channel == NotificationChannel.EMAIL:
            from app.users.models import User

            result = await db.execute(select(User).where(User.id == recipient_id))
            user = result.scalar_one_or_none()
            if user:
                await send_email(user.email, title, body)
            await db.execute(
                update(Notification)
                .where(Notification.id == notification.id)
                .values(sent_at=datetime.now(timezone.utc))
            )
            notification.sent_at = datetime.now(timezone.utc)

        logger.info(
            "Notification created: id=%s type=%s channel=%s recipient=%s",
            notification.id,
            notification_type,
            channel,
            recipient_id,
        )
        return notification

    # ------------------------------------------------------------------
    # Convenience: two-channel create (in-app + optional email)
    # ------------------------------------------------------------------

    async def _create_both_channels(
        self,
        db: AsyncSession,
        recipient_id: UUID,
        org_id: UUID,
        notification_type: NotificationType,
        context: dict,
        metadata: dict | None = None,
        expires_at: datetime | None = None,
    ) -> list[Notification]:
        """Create in-app and optionally email notification for the same event."""
        results: list[Notification] = []
        for channel in (NotificationChannel.IN_APP, NotificationChannel.EMAIL):
            n = await self.create_notification(
                db, recipient_id, org_id, notification_type, context,
                channel=channel, metadata=metadata, expires_at=expires_at,
            )
            if n:
                results.append(n)
        return results

    # ------------------------------------------------------------------
    # Business-event helpers
    # ------------------------------------------------------------------

    async def notify_kpi_at_risk(
        self,
        db: AsyncSession,
        target_id: UUID,
        achievement_pct: Decimal,
    ) -> list[Notification]:
        """
        Notify the employee (KPI_AT_RISK) AND their manager (TEAM_KPI_AT_RISK).

        Debounced: max one at-risk notification per target per 24 h (Redis key).
        """
        debounce_key = _redis_key_at_risk(target_id)
        if await self._redis.exists(debounce_key):
            logger.debug("At-risk notification debounced for target %s", target_id)
            return []

        # Load target with relationships
        from app.targets.models import KPITarget

        result = await db.execute(
            select(KPITarget).where(KPITarget.id == target_id)
        )
        target = result.scalar_one_or_none()
        if not target or not target.assignee_user_id:
            return []

        from app.kpis.models import KPI
        from app.review_cycles.models import ReviewCycle
        from app.users.models import User

        kpi_result = await db.execute(select(KPI).where(KPI.id == target.kpi_id))
        kpi = kpi_result.scalar_one_or_none()
        cycle_result = await db.execute(
            select(ReviewCycle).where(ReviewCycle.id == target.review_cycle_id)
        )
        cycle = cycle_result.scalar_one_or_none()

        if not kpi or not cycle:
            return []

        # Compute gap: how much more is needed to reach target
        actual_value = (
            float(achievement_pct) / 100.0 * float(target.target_value)
        )
        gap = max(float(target.target_value) - actual_value, 0.0)

        employee_result = await db.execute(
            select(User).where(User.id == target.assignee_user_id)
        )
        employee = employee_result.scalar_one_or_none()

        context = {
            "kpi_name": kpi.name,
            "achievement_pct": float(achievement_pct),
            "gap": gap,
            "unit": kpi.unit_label or kpi.unit.value,
            "cycle_end_date": cycle.end_date.strftime("%d %b %Y"),
            "target_id": str(target_id),
        }

        created: list[Notification] = []
        org_id = target.assignee_org_id or cycle.organisation_id

        # Notify employee
        created.extend(
            await self._create_both_channels(
                db, target.assignee_user_id, org_id,
                NotificationType.KPI_AT_RISK, context,
                metadata={"target_id": str(target_id), "kpi_id": str(kpi.id)},
            )
        )

        # Notify manager (if the employee has one)
        if employee and employee.manager_id:
            manager_context = {
                **context,
                "employee_name": employee.full_name,
                "target_id": str(target_id),
            }
            created.extend(
                await self._create_both_channels(
                    db, employee.manager_id, org_id,
                    NotificationType.TEAM_KPI_AT_RISK, manager_context,
                    metadata={"target_id": str(target_id), "kpi_id": str(kpi.id)},
                )
            )

        # Set debounce key
        await self._redis.setex(debounce_key, _DEBOUNCE_AT_RISK_TTL, "1")
        return created

    async def notify_actual_entry_due(
        self,
        db: AsyncSession,
        target_id: UUID,
        period_date: date,
    ) -> Notification | None:
        """
        Remind an employee to submit their actual value for a period.

        Skips if:
        - An actual already exists for this target+period.
        - A reminder was already sent for this target+period (Redis debounce).
        """
        from app.actuals.enums import ActualEntryStatus
        from app.actuals.models import KPIActual

        # Check if actual already submitted for this period
        existing = await db.execute(
            select(KPIActual).where(
                KPIActual.target_id == target_id,
                KPIActual.period_date == period_date,
                KPIActual.status != ActualEntryStatus.SUPERSEDED,
            )
        )
        if existing.scalar_one_or_none():
            return None

        debounce_key = _redis_key_reminder(target_id, period_date)
        if await self._redis.exists(debounce_key):
            logger.debug("Entry reminder debounced for target %s period %s", target_id, period_date)
            return None

        from app.kpis.models import KPI
        from app.review_cycles.models import ReviewCycle
        from app.targets.models import KPITarget

        result = await db.execute(select(KPITarget).where(KPITarget.id == target_id))
        target = result.scalar_one_or_none()
        if not target or not target.assignee_user_id:
            return None

        kpi_result = await db.execute(select(KPI).where(KPI.id == target.kpi_id))
        kpi = kpi_result.scalar_one_or_none()
        cycle_result = await db.execute(
            select(ReviewCycle).where(ReviewCycle.id == target.review_cycle_id)
        )
        cycle = cycle_result.scalar_one_or_none()
        if not kpi or not cycle:
            return None

        deadline = cycle.actual_entry_deadline or cycle.end_date
        context = {
            "kpi_name": kpi.name,
            "period_label": period_date.strftime("%b %Y"),
            "frequency": kpi.frequency.value,
            "deadline": deadline.strftime("%d %b %Y"),
            "target_id": str(target_id),
        }

        org_id = target.assignee_org_id or cycle.organisation_id
        notification = await self.create_notification(
            db, target.assignee_user_id, org_id,
            NotificationType.ACTUAL_ENTRY_DUE, context,
            channel=NotificationChannel.IN_APP,
            metadata={"target_id": str(target_id), "period_date": period_date.isoformat()},
        )
        if notification:
            await self._redis.setex(debounce_key, _DEBOUNCE_REMINDER_TTL, "1")
        return notification

    async def notify_target_achieved(
        self,
        db: AsyncSession,
        target_id: UUID,
        achievement_pct: Decimal,
    ) -> list[Notification]:
        """
        Celebrate 100%+ achievement with the employee.

        Debounced: max one achievement notification per target (72 h).
        """
        debounce_key = _redis_key_achieved(target_id)
        if await self._redis.exists(debounce_key):
            return []

        from app.kpis.models import KPI
        from app.review_cycles.models import ReviewCycle
        from app.targets.models import KPITarget

        result = await db.execute(select(KPITarget).where(KPITarget.id == target_id))
        target = result.scalar_one_or_none()
        if not target or not target.assignee_user_id:
            return []

        kpi_result = await db.execute(select(KPI).where(KPI.id == target.kpi_id))
        kpi = kpi_result.scalar_one_or_none()
        cycle_result = await db.execute(
            select(ReviewCycle).where(ReviewCycle.id == target.review_cycle_id)
        )
        cycle = cycle_result.scalar_one_or_none()
        if not kpi or not cycle:
            return []

        org_id = target.assignee_org_id or cycle.organisation_id
        pct = float(achievement_pct)
        n_type = (
            NotificationType.STRETCH_TARGET_ACHIEVED
            if target.stretch_target_value and pct >= 100.0
            else NotificationType.TARGET_ACHIEVED
        )
        context = {
            "kpi_name": kpi.name,
            "achievement_pct": pct,
            "target_id": str(target_id),
        }
        created = await self._create_both_channels(
            db, target.assignee_user_id, org_id, n_type, context,
            metadata={"target_id": str(target_id), "kpi_id": str(kpi.id)},
        )

        await self._redis.setex(debounce_key, _DEBOUNCE_ACHIEVED_TTL, "1")
        return created

    async def notify_period_closing(
        self,
        db: AsyncSession,
        cycle_id: UUID,
        days_until_close: int,
    ) -> int:
        """
        Bulk-notify all employees with active targets in a cycle.

        Respects period_closing_days_before preference — users who want
        alerts only 1 day before won't be notified on the 7-day warning.

        Returns the count of notifications created.
        """
        debounce_key = _redis_key_period_closing(cycle_id, days_until_close)
        if await self._redis.exists(debounce_key):
            logger.debug("Period closing reminder debounced for cycle %s day=%s", cycle_id, days_until_close)
            return 0

        from app.review_cycles.models import ReviewCycle
        from app.targets.enums import TargetStatus
        from app.targets.models import KPITarget

        cycle_result = await db.execute(
            select(ReviewCycle).where(ReviewCycle.id == cycle_id)
        )
        cycle = cycle_result.scalar_one_or_none()
        if not cycle:
            return 0

        # Get all locked targets with an assignee in this cycle
        targets_result = await db.execute(
            select(KPITarget.assignee_user_id, KPITarget.assignee_org_id).where(
                KPITarget.review_cycle_id == cycle_id,
                KPITarget.status == TargetStatus.LOCKED,
                KPITarget.assignee_user_id.isnot(None),
            ).distinct()
        )
        user_org_pairs: list[tuple[UUID, UUID | None]] = targets_result.all()

        count = 0
        for user_id, assignee_org_id in user_org_pairs:
            org_id = assignee_org_id or cycle.organisation_id

            # Check user preference for closing alerts
            prefs = await self.get_or_create_preference(db, user_id, org_id)
            if prefs.period_closing_days_before < days_until_close:
                # User only wants reminders closer to the deadline
                continue
            if not prefs.period_closing_in_app:
                continue

            context = {
                "cycle_name": cycle.name,
                "days_until_close": days_until_close,
                "cycle_id": str(cycle_id),
            }
            n = await self.create_notification(
                db, user_id, org_id,
                NotificationType.PERIOD_CLOSING_SOON, context,
                channel=NotificationChannel.IN_APP,
                metadata={"cycle_id": str(cycle_id), "days_until_close": days_until_close},
            )
            if n:
                count += 1

        await self._redis.setex(debounce_key, _DEBOUNCE_PERIOD_CLOSING_TTL, "1")
        logger.info("Period closing reminders sent: cycle=%s days=%s count=%s", cycle_id, days_until_close, count)
        return count

    async def notify_score_finalised(
        self,
        db: AsyncSession,
        user_id: UUID,
        org_id: UUID,
        cycle_id: UUID,
        rating: str,
    ) -> list[Notification]:
        """Notify an employee that their final performance score has been locked."""
        from app.review_cycles.models import ReviewCycle

        cycle_result = await db.execute(
            select(ReviewCycle).where(ReviewCycle.id == cycle_id)
        )
        cycle = cycle_result.scalar_one_or_none()
        cycle_name = cycle.name if cycle else "the review cycle"
        context = {
            "cycle_name": cycle_name,
            "rating": rating,
            "cycle_id": str(cycle_id),
        }
        return await self._create_both_channels(
            db, user_id, org_id, NotificationType.SCORE_FINALISED, context,
            metadata={"cycle_id": str(cycle_id)},
        )

    async def notify_score_adjusted(
        self,
        db: AsyncSession,
        user_id: UUID,
        org_id: UUID,
        kpi_name: str,
        before_value: Decimal,
        after_value: Decimal,
        manager_name: str,
        score_id: UUID,
    ) -> list[Notification]:
        """Notify an employee that a manager changed their KPI score."""
        context = {
            "kpi_name": kpi_name,
            "before_value": f"{before_value:.2f}",
            "after_value": f"{after_value:.2f}",
            "manager_name": manager_name,
            "score_id": str(score_id),
        }
        return await self._create_both_channels(
            db, user_id, org_id, NotificationType.SCORE_ADJUSTED, context,
            metadata={"score_id": str(score_id)},
        )

    # ------------------------------------------------------------------
    # Status mutations
    # ------------------------------------------------------------------

    async def mark_read(
        self, db: AsyncSession, notification_id: UUID, user_id: UUID
    ) -> Notification:
        """Mark a single notification as read.  Raises if not owned by user."""
        result = await db.execute(
            select(Notification).where(Notification.id == notification_id)
        )
        notification = result.scalar_one_or_none()
        if not notification:
            raise NotFoundException(f"Notification {notification_id} not found")
        if notification.recipient_id != user_id:
            raise ForbiddenException("Cannot mark another user's notification as read")
        if notification.status == NotificationStatus.UNREAD:
            notification.status = NotificationStatus.READ
            notification.read_at = datetime.now(timezone.utc)
            await db.flush()
        return notification

    async def mark_all_read(
        self, db: AsyncSession, user_id: UUID, org_id: UUID
    ) -> int:
        """Mark all unread notifications for a user as read.  Returns count updated."""
        now = datetime.now(timezone.utc)
        result = await db.execute(
            update(Notification)
            .where(
                Notification.recipient_id == user_id,
                Notification.organisation_id == org_id,
                Notification.status == NotificationStatus.UNREAD,
            )
            .values(status=NotificationStatus.READ, read_at=now)
        )
        return result.rowcount  # type: ignore[return-value]

    async def dismiss(
        self, db: AsyncSession, notification_id: UUID, user_id: UUID
    ) -> Notification:
        """Dismiss (soft-delete) a notification.  Raises if not owned by user."""
        result = await db.execute(
            select(Notification).where(Notification.id == notification_id)
        )
        notification = result.scalar_one_or_none()
        if not notification:
            raise NotFoundException(f"Notification {notification_id} not found")
        if notification.recipient_id != user_id:
            raise ForbiddenException("Cannot dismiss another user's notification")
        notification.status = NotificationStatus.DISMISSED
        await db.flush()
        return notification

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def list_for_user(
        self,
        db: AsyncSession,
        user_id: UUID,
        org_id: UUID,
        status: NotificationStatus | None = None,
        limit: int = 50,
        before_id: UUID | None = None,
    ) -> dict:
        """
        Cursor-based paginated list.

        Returns {"notifications": list, "unread_count": int, "has_more": bool}.
        Sorted newest-first.  before_id is the id of the *last item seen* (the
        cursor) — all notifications created before that notification are returned.
        """
        query = select(Notification).where(
            Notification.recipient_id == user_id,
            Notification.organisation_id == org_id,
            Notification.status != NotificationStatus.DISMISSED,
        )
        if status:
            query = query.where(Notification.status == status)
        if before_id:
            # Resolve cursor to a timestamp
            cursor_result = await db.execute(
                select(Notification.created_at).where(Notification.id == before_id)
            )
            cursor_ts = cursor_result.scalar_one_or_none()
            if cursor_ts:
                query = query.where(Notification.created_at < cursor_ts)

        query = query.order_by(Notification.created_at.desc()).limit(limit + 1)
        items_result = await db.execute(query)
        items = list(items_result.scalars())

        has_more = len(items) > limit
        if has_more:
            items = items[:limit]

        unread_count = await self.get_unread_count(db, user_id)
        return {
            "notifications": items,
            "unread_count": unread_count,
            "has_more": has_more,
        }

    async def get_unread_count(self, db: AsyncSession, user_id: UUID) -> int:
        result = await db.execute(
            select(func.count()).where(
                Notification.recipient_id == user_id,
                Notification.status == NotificationStatus.UNREAD,
            )
        )
        return result.scalar_one() or 0

    # ------------------------------------------------------------------
    # Preferences
    # ------------------------------------------------------------------

    async def get_or_create_preference(
        self, db: AsyncSession, user_id: UUID, org_id: UUID
    ) -> NotificationPreference:
        """Load preference row; create defaults if first time."""
        result = await db.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user_id
            )
        )
        prefs = result.scalar_one_or_none()
        if prefs is None:
            prefs = NotificationPreference(user_id=user_id, organisation_id=org_id)
            db.add(prefs)
            await db.flush()
        return prefs

    async def update_preference(
        self, db: AsyncSession, user_id: UUID, org_id: UUID, data: dict
    ) -> NotificationPreference:
        """Apply a partial update to a user's notification preferences."""
        prefs = await self.get_or_create_preference(db, user_id, org_id)
        for field, value in data.items():
            if value is not None and hasattr(prefs, field):
                setattr(prefs, field, value)
        prefs.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return prefs
