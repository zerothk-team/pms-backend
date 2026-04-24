"""Pydantic v2 schemas for the Notifications module."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.notifications.enums import NotificationChannel, NotificationStatus, NotificationType


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    recipient_id: uuid.UUID
    organisation_id: uuid.UUID
    notification_type: NotificationType
    channel: NotificationChannel
    status: NotificationStatus
    title: str
    body: str
    action_url: Optional[str] = None
    metadata_: Optional[dict] = Field(None, alias="metadata_")
    sent_at: Optional[datetime] = None
    read_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class NotificationListResponse(BaseModel):
    """Cursor-based paginated list with unread count for badge rendering."""

    notifications: list[NotificationRead]
    unread_count: int
    has_more: bool


class UnreadCountResponse(BaseModel):
    unread: int


# ---------------------------------------------------------------------------
# Preference schemas
# ---------------------------------------------------------------------------


class NotificationPreferenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    organisation_id: uuid.UUID

    kpi_at_risk_in_app: bool
    kpi_at_risk_email: bool
    actual_due_in_app: bool
    actual_due_email: bool
    target_achieved_in_app: bool
    target_achieved_email: bool
    period_closing_in_app: bool
    period_closing_email: bool
    score_finalised_in_app: bool
    score_finalised_email: bool
    score_adjusted_in_app: bool
    score_adjusted_email: bool
    period_closing_days_before: int
    email_digest_frequency: str
    updated_at: datetime


class NotificationPreferenceUpdate(BaseModel):
    """All fields optional — PATCH semantics."""

    kpi_at_risk_in_app: Optional[bool] = None
    kpi_at_risk_email: Optional[bool] = None
    actual_due_in_app: Optional[bool] = None
    actual_due_email: Optional[bool] = None
    target_achieved_in_app: Optional[bool] = None
    target_achieved_email: Optional[bool] = None
    period_closing_in_app: Optional[bool] = None
    period_closing_email: Optional[bool] = None
    score_finalised_in_app: Optional[bool] = None
    score_finalised_email: Optional[bool] = None
    score_adjusted_in_app: Optional[bool] = None
    score_adjusted_email: Optional[bool] = None
    period_closing_days_before: Optional[int] = Field(None, ge=0, le=30)
    email_digest_frequency: Optional[str] = Field(
        None, pattern=r"^(immediate|daily|weekly)$"
    )
