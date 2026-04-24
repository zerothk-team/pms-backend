"""FastAPI router for the Notifications module.

All endpoints require authentication.  Users can only access their own
notifications — the service layer enforces ownership.

Endpoints:
    GET    /notifications/                → list (cursor-based, filters)
    GET    /notifications/unread-count    → badge count
    PATCH  /notifications/{id}/read       → mark single read
    POST   /notifications/read-all        → mark all read
    DELETE /notifications/{id}            → dismiss
    GET    /notifications/preferences/    → get own preferences
    PUT    /notifications/preferences/    → update own preferences
"""

from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_active_user
from app.exceptions import NotFoundException
from app.notifications.enums import NotificationStatus
from app.notifications.schemas import (
    NotificationListResponse,
    NotificationPreferenceRead,
    NotificationPreferenceUpdate,
    NotificationRead,
    UnreadCountResponse,
)
from app.notifications.service import NotificationService
from app.users.models import User

router = APIRouter(prefix="/notifications", tags=["Notifications"])


def _get_notification_service() -> NotificationService:
    """Resolve a NotificationService with the app-level Redis connection."""
    from app.main import get_redis

    return NotificationService(get_redis())


# ---------------------------------------------------------------------------
# Listing & counts
# ---------------------------------------------------------------------------


@router.get(
    "/",
    response_model=NotificationListResponse,
    summary="List my notifications",
    description=(
        "Returns up to `limit` notifications for the authenticated user, "
        "newest-first.  Use `before_id` (the `id` of the last notification "
        "you received) as a cursor to paginate."
    ),
)
async def list_notifications(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    status: Optional[NotificationStatus] = None,
    limit: int = 50,
    before_id: Optional[UUID] = None,
) -> NotificationListResponse:
    svc = _get_notification_service()
    result = await svc.list_for_user(
        db,
        user_id=current_user.id,
        org_id=current_user.organisation_id,
        status=status,
        limit=min(limit, 100),
        before_id=before_id,
    )
    return NotificationListResponse(
        notifications=result["notifications"],
        unread_count=result["unread_count"],
        has_more=result["has_more"],
    )


@router.get(
    "/unread-count",
    response_model=UnreadCountResponse,
    summary="Get unread notification count",
    description="Lightweight endpoint for the notification badge in the UI.",
)
async def get_unread_count(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> UnreadCountResponse:
    svc = _get_notification_service()
    count = await svc.get_unread_count(db, current_user.id)
    return UnreadCountResponse(unread=count)


# ---------------------------------------------------------------------------
# Status mutations
# ---------------------------------------------------------------------------


@router.patch(
    "/{notification_id}/read",
    response_model=NotificationRead,
    summary="Mark notification as read",
)
async def mark_notification_read(
    notification_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> NotificationRead:
    svc = _get_notification_service()
    notification = await svc.mark_read(db, notification_id, current_user.id)
    return notification


@router.post(
    "/read-all",
    summary="Mark all notifications as read",
    description="Marks every UNREAD notification for the authenticated user as READ.",
)
async def mark_all_read(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict:
    svc = _get_notification_service()
    count = await svc.mark_all_read(db, current_user.id, current_user.organisation_id)
    return {"marked_read": count}


@router.delete(
    "/{notification_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Dismiss notification",
    description="Marks a notification as DISMISSED (soft delete).  It will no longer appear in polls.",
)
async def dismiss_notification(
    notification_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> None:
    svc = _get_notification_service()
    await svc.dismiss(db, notification_id, current_user.id)


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------


@router.get(
    "/preferences/",
    response_model=NotificationPreferenceRead,
    summary="Get my notification preferences",
)
async def get_preferences(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> NotificationPreferenceRead:
    svc = _get_notification_service()
    prefs = await svc.get_or_create_preference(
        db, current_user.id, current_user.organisation_id
    )
    return prefs


@router.put(
    "/preferences/",
    response_model=NotificationPreferenceRead,
    summary="Update my notification preferences",
    description=(
        "Partial update — only include fields you want to change.  "
        "Use `period_closing_days_before=0` to disable cycle-closing alerts."
    ),
)
async def update_preferences(
    data: NotificationPreferenceUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> NotificationPreferenceRead:
    svc = _get_notification_service()
    prefs = await svc.update_preference(
        db,
        current_user.id,
        current_user.organisation_id,
        data.model_dump(exclude_none=True),
    )
    return prefs
