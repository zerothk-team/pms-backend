"""
Tests for the Notifications module.

Part A — Service layer (direct service instantiation, in-memory DB + FakeRedis).
Part B — HTTP endpoint tests (AsyncClient with patched Redis).

All tests use the shared in-memory SQLite fixture from conftest.py.
Each test registers its own user+org (HTTP tests) or inserts directly into the
DB (service tests) to stay isolated.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import fakeredis.aioredis
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.utils import hash_password
from app.notifications.enums import NotificationChannel, NotificationStatus, NotificationType
from app.notifications.models import Notification, NotificationPreference
from app.notifications.service import NotificationService
from app.users.models import User, UserRole


# =============================================================================
# Fixtures
# =============================================================================


@pytest_asyncio.fixture
async def fake_redis():
    """In-process FakeRedis that behaves like a real Redis client."""
    r = fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()


@pytest_asyncio.fixture
async def notif_user(db_session: AsyncSession) -> User:
    """
    A minimal User row for service-layer tests.

    SQLite does not enforce FK constraints, so we use a random UUID for
    organisation_id without inserting an Organisation row.
    """
    user = User(
        username=f"notif_{uuid.uuid4().hex[:8]}",
        email=f"notif_{uuid.uuid4().hex[:8]}@test.example",
        full_name="Notification Test User",
        role=UserRole.employee,
        hashed_password=hash_password("testpass"),
        is_active=True,
        organisation_id=uuid.uuid4(),  # FK not enforced by SQLite
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


# ---------------------------------------------------------------------------
# HTTP helpers (same pattern as other test files)
# ---------------------------------------------------------------------------


def _reg(suffix: str, role: str = "hr_admin") -> dict:
    return {
        "user": {
            "username": f"{suffix}_user",
            "email": f"{suffix}@notif-test.example",
            "full_name": f"{suffix.title()} User",
            "role": role,
            "password": "testpass123",
        },
        "organisation": {
            "name": f"{suffix.title()} Notif Org",
            "slug": f"{suffix}-notif-org",
        },
    }


async def _register_and_login(client: AsyncClient, payload: dict) -> str:
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _ctx_scoring(cycle_name: str = "Q1 2025", count: int = 5) -> dict:
    """Minimal context for a SCORING_COMPLETE notification."""
    return {
        "cycle_name": cycle_name,
        "employee_count": count,
        "cycle_id": str(uuid.uuid4()),
    }


# =============================================================================
# Part A — Service layer tests
# =============================================================================


@pytest.mark.asyncio
async def test_create_in_app_notification_stores_row(
    db_session: AsyncSession,
    notif_user: User,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """
    Business rule: create_notification persists a SCORING_COMPLETE notification
    with status=UNREAD and channel=IN_APP, and the rendered title/body reference
    the cycle name supplied in the context dict.
    """
    svc = NotificationService(fake_redis)

    notif = await svc.create_notification(
        db=db_session,
        recipient_id=notif_user.id,
        org_id=notif_user.organisation_id,
        notification_type=NotificationType.SCORING_COMPLETE,
        context=_ctx_scoring("Q4 2024"),
    )
    await db_session.commit()

    assert notif is not None
    assert notif.status == NotificationStatus.UNREAD
    assert notif.channel == NotificationChannel.IN_APP
    assert notif.recipient_id == notif_user.id
    assert notif.organisation_id == notif_user.organisation_id
    # Template must include the cycle name somewhere in title or body
    assert "Q4 2024" in notif.title or "Q4 2024" in notif.body
    assert notif.created_at is not None


@pytest.mark.asyncio
async def test_email_notification_skipped_when_preference_disabled(
    db_session: AsyncSession,
    notif_user: User,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """
    Business rule: when the user disables email for score_finalised, calling
    create_notification with channel=EMAIL returns None (notification not stored).
    """
    svc = NotificationService(fake_redis)

    # Get or create preference and disable email for score finalised
    prefs = await svc.get_or_create_preference(
        db_session, notif_user.id, notif_user.organisation_id
    )
    prefs.score_finalised_email = False
    await db_session.commit()

    notif = await svc.create_notification(
        db=db_session,
        recipient_id=notif_user.id,
        org_id=notif_user.organisation_id,
        notification_type=NotificationType.SCORE_FINALISED,
        context={
            "cycle_name": "Q1 2025",
            "score": 85.0,
            "rating": "Exceeds Expectations",
            "cycle_id": str(uuid.uuid4()),
        },
        channel=NotificationChannel.EMAIL,
    )

    assert notif is None, "Email notification should be suppressed when preference is off"


@pytest.mark.asyncio
async def test_in_app_channel_goes_through_regardless_of_email_preference(
    db_session: AsyncSession,
    notif_user: User,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """
    Business rule: disabling email does not suppress in-app notifications
    for the same type.
    """
    svc = NotificationService(fake_redis)

    prefs = await svc.get_or_create_preference(
        db_session, notif_user.id, notif_user.organisation_id
    )
    prefs.score_finalised_email = False
    prefs.score_finalised_in_app = True
    await db_session.commit()

    notif = await svc.create_notification(
        db=db_session,
        recipient_id=notif_user.id,
        org_id=notif_user.organisation_id,
        notification_type=NotificationType.SCORE_FINALISED,
        context={
            "cycle_name": "Q1 2025",
            "score": 85.0,
            "rating": "Exceeds Expectations",
            "cycle_id": str(uuid.uuid4()),
        },
        channel=NotificationChannel.IN_APP,
    )
    await db_session.commit()

    assert notif is not None
    assert notif.channel == NotificationChannel.IN_APP


@pytest.mark.asyncio
async def test_mark_notification_read_changes_status_and_sets_timestamp(
    db_session: AsyncSession,
    notif_user: User,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """
    Business rule: mark_read flips status from UNREAD to READ and records
    read_at timestamp.
    """
    svc = NotificationService(fake_redis)

    notif = await svc.create_notification(
        db=db_session,
        recipient_id=notif_user.id,
        org_id=notif_user.organisation_id,
        notification_type=NotificationType.SCORING_COMPLETE,
        context=_ctx_scoring(),
    )
    await db_session.commit()

    read_notif = await svc.mark_read(db_session, notif.id, notif_user.id)
    await db_session.commit()

    assert read_notif.status == NotificationStatus.READ
    assert read_notif.read_at is not None


@pytest.mark.asyncio
async def test_mark_read_is_idempotent(
    db_session: AsyncSession,
    notif_user: User,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """Calling mark_read on an already-read notification does not raise."""
    svc = NotificationService(fake_redis)

    notif = await svc.create_notification(
        db=db_session,
        recipient_id=notif_user.id,
        org_id=notif_user.organisation_id,
        notification_type=NotificationType.SCORING_COMPLETE,
        context=_ctx_scoring(),
    )
    await db_session.commit()

    await svc.mark_read(db_session, notif.id, notif_user.id)
    await db_session.commit()
    # Second call is idempotent
    result = await svc.mark_read(db_session, notif.id, notif_user.id)
    assert result.status == NotificationStatus.READ


@pytest.mark.asyncio
async def test_mark_all_read_returns_count_and_clears_unread(
    db_session: AsyncSession,
    notif_user: User,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """
    Business rule: mark_all_read moves all UNREAD notifications to READ and
    returns the exact count of rows updated.
    """
    svc = NotificationService(fake_redis)

    for _ in range(3):
        await svc.create_notification(
            db=db_session,
            recipient_id=notif_user.id,
            org_id=notif_user.organisation_id,
            notification_type=NotificationType.SCORING_COMPLETE,
            context=_ctx_scoring(),
        )
    await db_session.commit()

    count = await svc.mark_all_read(
        db_session, notif_user.id, notif_user.organisation_id
    )
    await db_session.commit()

    assert count == 3
    # Unread count should now be zero
    unread = await svc.get_unread_count(db_session, notif_user.id)
    assert unread == 0


@pytest.mark.asyncio
async def test_dismiss_notification_sets_dismissed_status(
    db_session: AsyncSession,
    notif_user: User,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """
    Business rule: dismiss sets status to DISMISSED and the notification no
    longer appears in list_for_user filters.
    """
    svc = NotificationService(fake_redis)

    notif = await svc.create_notification(
        db=db_session,
        recipient_id=notif_user.id,
        org_id=notif_user.organisation_id,
        notification_type=NotificationType.SCORING_COMPLETE,
        context=_ctx_scoring(),
    )
    await db_session.commit()

    await svc.dismiss(db_session, notif.id, notif_user.id)
    await db_session.commit()

    # Verify directly in DB
    result = await db_session.execute(
        select(Notification).where(Notification.id == notif.id)
    )
    updated = result.scalar_one()
    assert updated.status == NotificationStatus.DISMISSED


@pytest.mark.asyncio
async def test_list_notifications_with_unread_filter(
    db_session: AsyncSession,
    notif_user: User,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """
    Business rule: list_for_user with status=UNREAD only returns unread
    notifications; notifications marked as read are excluded.
    """
    svc = NotificationService(fake_redis)

    n1 = await svc.create_notification(
        db=db_session,
        recipient_id=notif_user.id,
        org_id=notif_user.organisation_id,
        notification_type=NotificationType.SCORING_COMPLETE,
        context=_ctx_scoring("Cycle A"),
    )
    await svc.create_notification(
        db=db_session,
        recipient_id=notif_user.id,
        org_id=notif_user.organisation_id,
        notification_type=NotificationType.SCORING_COMPLETE,
        context=_ctx_scoring("Cycle B"),
    )
    await db_session.commit()

    # Mark the first one as read
    await svc.mark_read(db_session, n1.id, notif_user.id)
    await db_session.commit()

    result = await svc.list_for_user(
        db_session,
        user_id=notif_user.id,
        org_id=notif_user.organisation_id,
        status=NotificationStatus.UNREAD,
    )

    assert result["unread_count"] == 1
    for n in result["notifications"]:
        assert n.status == NotificationStatus.UNREAD


@pytest.mark.asyncio
async def test_get_unread_count_increments(
    db_session: AsyncSession,
    notif_user: User,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """get_unread_count returns the exact number of UNREAD notifications."""
    svc = NotificationService(fake_redis)

    initial = await svc.get_unread_count(db_session, notif_user.id)

    for _ in range(2):
        await svc.create_notification(
            db=db_session,
            recipient_id=notif_user.id,
            org_id=notif_user.organisation_id,
            notification_type=NotificationType.SCORING_COMPLETE,
            context=_ctx_scoring(),
        )
    await db_session.commit()

    count = await svc.get_unread_count(db_session, notif_user.id)
    assert count == initial + 2


@pytest.mark.asyncio
async def test_get_or_create_preference_returns_defaults(
    db_session: AsyncSession,
    notif_user: User,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """
    Business rule: first call to get_or_create_preference creates a row with
    all boolean fields defaulting to True (opt-in by default).
    """
    svc = NotificationService(fake_redis)

    prefs = await svc.get_or_create_preference(
        db_session, notif_user.id, notif_user.organisation_id
    )
    await db_session.commit()

    assert prefs is not None
    assert prefs.user_id == notif_user.id
    assert prefs.kpi_at_risk_in_app is True
    assert prefs.kpi_at_risk_email is True
    assert prefs.period_closing_days_before == 3  # default


@pytest.mark.asyncio
async def test_update_preference_persists_changes(
    db_session: AsyncSession,
    notif_user: User,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """update_preference partial-updates the user's notification preferences."""
    svc = NotificationService(fake_redis)

    updated = await svc.update_preference(
        db_session,
        notif_user.id,
        notif_user.organisation_id,
        {"kpi_at_risk_email": False, "period_closing_days_before": 7},
    )
    await db_session.commit()

    assert updated.kpi_at_risk_email is False
    assert updated.period_closing_days_before == 7
    # Non-updated fields keep their defaults
    assert updated.kpi_at_risk_in_app is True


@pytest.mark.asyncio
async def test_at_risk_debounce_prevents_duplicate_notification(
    db_session: AsyncSession,
    notif_user: User,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """
    Business rule: notify_kpi_at_risk is debounced per target for 24 h.
    A second call within the debounce window returns an empty list.

    We test this at the Redis level — once the debounce key is set, the
    method returns [] without hitting the DB for KPITarget.
    """
    svc = NotificationService(fake_redis)

    target_id = uuid.uuid4()
    debounce_key = f"notif:at_risk:{target_id}"

    # Manually set the debounce key as if a notification was already sent
    await fake_redis.setex(debounce_key, 86400, "1")

    from decimal import Decimal

    result = await svc.notify_kpi_at_risk(db_session, target_id, Decimal("45.0"))

    assert result == [], "Debounced call should return empty list"


@pytest.mark.asyncio
async def test_notify_actual_entry_due_debounce(
    db_session: AsyncSession,
    notif_user: User,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """
    Business rule: notify_actual_entry_due is debounced per (target, period).
    A second call within 7 days returns None.
    """
    from datetime import date

    svc = NotificationService(fake_redis)

    target_id = uuid.uuid4()
    period = date(2025, 1, 1)
    debounce_key = f"notif:reminder:{target_id}:{period.isoformat()}"

    await fake_redis.setex(debounce_key, 604800, "1")

    result = await svc.notify_actual_entry_due(db_session, target_id, period)
    assert result is None, "Debounced reminder should return None"


# =============================================================================
# Part B — HTTP endpoint tests
# =============================================================================


@pytest.mark.asyncio
async def test_list_notifications_returns_empty_for_new_user(
    async_client: AsyncClient,
) -> None:
    """GET /notifications/ returns 200 with empty list for a user with no notifications."""
    import fakeredis.aioredis as _fkr

    token = await _register_and_login(async_client, _reg("ne_list1"))
    fake_redis = _fkr.FakeRedis()

    with patch("app.main.get_redis", return_value=fake_redis):
        resp = await async_client.get(
            "/api/v1/notifications/", headers=_auth(token)
        )
    await fake_redis.aclose()

    assert resp.status_code == 200
    data = resp.json()
    assert data["notifications"] == []
    assert data["unread_count"] == 0
    assert data["has_more"] is False


@pytest.mark.asyncio
async def test_unread_count_endpoint_returns_zero(async_client: AsyncClient) -> None:
    """GET /notifications/unread-count returns {unread: 0} for a new user."""
    import fakeredis.aioredis as _fkr

    token = await _register_and_login(async_client, _reg("ne_cnt1"))
    fake_redis = _fkr.FakeRedis()

    with patch("app.main.get_redis", return_value=fake_redis):
        resp = await async_client.get(
            "/api/v1/notifications/unread-count", headers=_auth(token)
        )
    await fake_redis.aclose()

    assert resp.status_code == 200
    assert resp.json() == {"unread": 0}


@pytest.mark.asyncio
async def test_mark_notification_read_via_http(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """PATCH /notifications/{id}/read transitions status to 'read'."""
    import fakeredis.aioredis as _fkr

    token = await _register_and_login(async_client, _reg("ne_read1"))
    fake_redis = _fkr.FakeRedis()

    # Get user IDs from the profile endpoint
    with patch("app.main.get_redis", return_value=fake_redis):
        me_resp = await async_client.get(
            "/api/v1/users/me", headers=_auth(token)
        )
    user_id = uuid.UUID(me_resp.json()["id"])
    org_id = uuid.UUID(me_resp.json()["organisation_id"])

    # Insert a notification directly via the service
    svc = NotificationService(fake_redis)
    notif = await svc.create_notification(
        db=db_session,
        recipient_id=user_id,
        org_id=org_id,
        notification_type=NotificationType.SCORING_COMPLETE,
        context=_ctx_scoring("Mark-Read Cycle"),
    )
    await db_session.commit()

    with patch("app.main.get_redis", return_value=fake_redis):
        resp = await async_client.patch(
            f"/api/v1/notifications/{notif.id}/read",
            headers=_auth(token),
        )
    await fake_redis.aclose()

    assert resp.status_code == 200
    assert resp.json()["status"] == "read"


@pytest.mark.asyncio
async def test_dismiss_notification_via_http(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """DELETE /notifications/{id} returns 204 and sets DISMISSED status."""
    import fakeredis.aioredis as _fkr

    token = await _register_and_login(async_client, _reg("ne_dis1"))
    fake_redis = _fkr.FakeRedis()

    with patch("app.main.get_redis", return_value=fake_redis):
        me_resp = await async_client.get("/api/v1/users/me", headers=_auth(token))
    user_id = uuid.UUID(me_resp.json()["id"])
    org_id = uuid.UUID(me_resp.json()["organisation_id"])

    svc = NotificationService(fake_redis)
    notif = await svc.create_notification(
        db=db_session,
        recipient_id=user_id,
        org_id=org_id,
        notification_type=NotificationType.SCORING_COMPLETE,
        context=_ctx_scoring("Dismiss Cycle"),
    )
    await db_session.commit()

    with patch("app.main.get_redis", return_value=fake_redis):
        resp = await async_client.delete(
            f"/api/v1/notifications/{notif.id}",
            headers=_auth(token),
        )
    await fake_redis.aclose()

    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_mark_all_read_via_http(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """POST /notifications/read-all marks all UNREAD notifications as READ."""
    import fakeredis.aioredis as _fkr

    token = await _register_and_login(async_client, _reg("ne_all1"))
    fake_redis = _fkr.FakeRedis()

    with patch("app.main.get_redis", return_value=fake_redis):
        me_resp = await async_client.get("/api/v1/users/me", headers=_auth(token))
    user_id = uuid.UUID(me_resp.json()["id"])
    org_id = uuid.UUID(me_resp.json()["organisation_id"])

    svc = NotificationService(fake_redis)
    for _ in range(3):
        await svc.create_notification(
            db=db_session,
            recipient_id=user_id,
            org_id=org_id,
            notification_type=NotificationType.SCORING_COMPLETE,
            context=_ctx_scoring(),
        )
    await db_session.commit()

    with patch("app.main.get_redis", return_value=fake_redis):
        resp = await async_client.post(
            "/api/v1/notifications/read-all",
            headers=_auth(token),
        )
    await fake_redis.aclose()

    assert resp.status_code == 200
    assert resp.json()["marked_read"] == 3


@pytest.mark.asyncio
async def test_get_preferences_returns_defaults(async_client: AsyncClient) -> None:
    """GET /notifications/preferences/ auto-creates and returns default preferences."""
    import fakeredis.aioredis as _fkr

    token = await _register_and_login(async_client, _reg("ne_pref1"))
    fake_redis = _fkr.FakeRedis()

    with patch("app.main.get_redis", return_value=fake_redis):
        resp = await async_client.get(
            "/api/v1/notifications/preferences/",
            headers=_auth(token),
        )
    await fake_redis.aclose()

    assert resp.status_code == 200
    data = resp.json()
    assert "kpi_at_risk_in_app" in data
    assert "kpi_at_risk_email" in data
    assert "email_digest_frequency" in data
    # All booleans default to True
    assert data["kpi_at_risk_in_app"] is True
    assert data["kpi_at_risk_email"] is True


@pytest.mark.asyncio
async def test_update_preferences_via_http(async_client: AsyncClient) -> None:
    """PUT /notifications/preferences/ persists partial updates."""
    import fakeredis.aioredis as _fkr

    token = await _register_and_login(async_client, _reg("ne_pref2"))
    fake_redis = _fkr.FakeRedis()

    with patch("app.main.get_redis", return_value=fake_redis):
        resp = await async_client.put(
            "/api/v1/notifications/preferences/",
            json={"kpi_at_risk_email": False, "period_closing_days_before": 7},
            headers=_auth(token),
        )
    await fake_redis.aclose()

    assert resp.status_code == 200
    data = resp.json()
    assert data["kpi_at_risk_email"] is False
    assert data["period_closing_days_before"] == 7
    # Non-changed fields should still be at their default
    assert data["kpi_at_risk_in_app"] is True


@pytest.mark.asyncio
async def test_list_notifications_requires_auth(async_client: AsyncClient) -> None:
    """GET /notifications/ without an auth token returns 401."""
    resp = await async_client.get("/api/v1/notifications/")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_mark_read_returns_403_for_wrong_owner(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """
    Business rule: a user cannot mark another user's notification as read.
    The endpoint returns 403 Forbidden.
    """
    import fakeredis.aioredis as _fkr

    token_a = await _register_and_login(async_client, _reg("ne_own_a"))
    token_b = await _register_and_login(async_client, _reg("ne_own_b"))
    fake_redis = _fkr.FakeRedis()

    with patch("app.main.get_redis", return_value=fake_redis):
        me_resp = await async_client.get("/api/v1/users/me", headers=_auth(token_a))
    user_a_id = uuid.UUID(me_resp.json()["id"])
    org_a_id = uuid.UUID(me_resp.json()["organisation_id"])

    svc = NotificationService(fake_redis)
    notif = await svc.create_notification(
        db=db_session,
        recipient_id=user_a_id,
        org_id=org_a_id,
        notification_type=NotificationType.SCORING_COMPLETE,
        context=_ctx_scoring("Ownership Test"),
    )
    await db_session.commit()

    # User B tries to mark User A's notification as read
    with patch("app.main.get_redis", return_value=fake_redis):
        resp = await async_client.patch(
            f"/api/v1/notifications/{notif.id}/read",
            headers=_auth(token_b),
        )
    await fake_redis.aclose()

    assert resp.status_code == 403
