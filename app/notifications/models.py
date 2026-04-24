"""SQLAlchemy ORM models for the Notifications module."""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.notifications.enums import NotificationChannel, NotificationStatus, NotificationType


class Notification(Base):
    """
    A single notification sent to one user.

    Notifications are scoped to an organisation and carry a type that drives
    template rendering on the frontend.  They are created by the
    NotificationService (from business events) and by background jobs.

    Lifecycle:  UNREAD → READ  (normal)
                UNREAD → DISMISSED  (user closes without reading)
    Expired notifications (expires_at < now) are pruned by the weekly cleanup job.
    """

    __tablename__ = "notifications"

    __table_args__ = (
        Index("ix_notif_recipient_status", "recipient_id", "status"),
        Index("ix_notif_recipient_created", "recipient_id", "created_at"),
        Index("ix_notif_organisation", "organisation_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
    )
    notification_type: Mapped[NotificationType] = mapped_column(
        SAEnum(NotificationType, name="notificationtype"), nullable=False
    )
    channel: Mapped[NotificationChannel] = mapped_column(
        SAEnum(NotificationChannel, name="notificationchannel"),
        nullable=False,
        default=NotificationChannel.IN_APP,
    )
    status: Mapped[NotificationStatus] = mapped_column(
        SAEnum(NotificationStatus, name="notificationstatus"),
        nullable=False,
        default=NotificationStatus.UNREAD,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Deep link for the frontend SPA — e.g. /dashboard/kpis/{target_id}
    action_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # Arbitrary JSON context stored alongside the notification for debugging /
    # future rendering (kpi_id, target_id, cycle_id …).
    # Uses sqlalchemy.JSON which maps to JSONB on PostgreSQL and TEXT on SQLite.
    metadata_: Mapped[Optional[dict]] = mapped_column(
        "metadata", JSON, nullable=True
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    read_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    recipient = relationship("User", foreign_keys=[recipient_id], lazy="raise")

    def __repr__(self) -> str:
        return (
            f"<Notification id={self.id} type={self.notification_type} "
            f"status={self.status} recipient={self.recipient_id}>"
        )


class NotificationPreference(Base):
    """
    Per-user notification channel preferences.

    One row per user — created lazily on first access via
    NotificationService.get_or_create_preference().

    The boolean flags control which channel (in-app / email) is used for each
    notification category.  The email_digest_frequency field is reserved for
    future batch email delivery; currently all emails are sent immediately.
    """

    __tablename__ = "notification_preferences"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
    )

    # --- Channel preferences per notification category ----------------------
    kpi_at_risk_in_app: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    kpi_at_risk_email: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    actual_due_in_app: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    actual_due_email: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    target_achieved_in_app: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    target_achieved_email: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    period_closing_in_app: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    period_closing_email: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    score_finalised_in_app: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    score_finalised_email: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    score_adjusted_in_app: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    score_adjusted_email: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # How many days before cycle end to send the closing-soon alert (0 = disabled)
    period_closing_days_before: Mapped[int] = mapped_column(Integer, default=3, nullable=False)

    # "immediate" | "daily" | "weekly" — reserved for future digest batching
    email_digest_frequency: Mapped[str] = mapped_column(
        String(20), default="immediate", nullable=False
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    user = relationship("User", foreign_keys=[user_id], lazy="raise")

    def __repr__(self) -> str:
        return f"<NotificationPreference user={self.user_id}>"
