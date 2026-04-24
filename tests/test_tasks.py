"""
Tests for the Background Tasks module.

Part A — HTTP endpoint tests:
    GET  /tasks/jobs/           → list all scheduled jobs (hr_admin only)
    POST /tasks/run/{job_id}    → manual trigger (hr_admin only)

Part B — Job function unit tests:
    cleanup_expired_notifications_job   → deletes expired READ/DISMISSED rows
    check_at_risk_kpis_job              → at-risk targets trigger notifications
    send_actual_entry_reminders_job     → skips if actual already submitted

All integration tests use the shared in-memory SQLite fixture from conftest.py.
Job functions are called directly with the test DB patched in and a FakeRedis
instance substituted for the production Redis connection.
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import fakeredis.aioredis
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.utils import hash_password
from app.notifications.enums import NotificationStatus, NotificationType
from app.notifications.models import Notification
from app.notifications.service import NotificationService
from app.users.models import User, UserRole


# =============================================================================
# Shared helpers
# =============================================================================


def _reg(suffix: str, role: str = "hr_admin") -> dict:
    return {
        "user": {
            "username": f"{suffix}_user",
            "email": f"{suffix}@tasks-test.example",
            "full_name": f"{suffix.title()} Tasks User",
            "role": role,
            "password": "testpass123",
        },
        "organisation": {
            "name": f"{suffix.title()} Tasks Org",
            "slug": f"{suffix}-tasks-org",
        },
    }


async def _register_and_login(client: AsyncClient, payload: dict) -> str:
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def fake_redis():
    r = fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()


# =============================================================================
# Part A — HTTP endpoint tests
# =============================================================================


@pytest.mark.asyncio
async def test_list_jobs_returns_200_for_hr_admin(async_client: AsyncClient) -> None:
    """
    GET /tasks/jobs/ returns 200 (a JSON array) for an hr_admin.
    The list may be empty if the scheduler has not started (test mode),
    or contain up to 6 jobs if the scheduler started with the app.
    """
    import fakeredis.aioredis as _fkr

    token = await _register_and_login(async_client, _reg("tj_list1"))
    fake_redis = _fkr.FakeRedis()

    with patch("app.main.get_redis", return_value=fake_redis):
        resp = await async_client.get(
            "/api/v1/tasks/jobs/",
            headers=_auth(token),
        )
    await fake_redis.aclose()

    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_list_jobs_returns_403_for_employee(async_client: AsyncClient) -> None:
    """
    GET /tasks/jobs/ is restricted to hr_admin — employees receive 403.
    """
    import fakeredis.aioredis as _fkr

    token = await _register_and_login(
        async_client, _reg("tj_emp1", role="employee")
    )
    fake_redis = _fkr.FakeRedis()

    with patch("app.main.get_redis", return_value=fake_redis):
        resp = await async_client.get(
            "/api/v1/tasks/jobs/",
            headers=_auth(token),
        )
    await fake_redis.aclose()

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_trigger_known_job_returns_202(async_client: AsyncClient) -> None:
    """
    POST /tasks/run/{job_id} accepts a known job ID and returns 202 Accepted.
    The job runs asynchronously — this test only checks the HTTP contract.
    """
    import fakeredis.aioredis as _fkr

    token = await _register_and_login(async_client, _reg("tj_run1"))
    fake_redis = _fkr.FakeRedis()

    # Patch both the Redis singleton and the DB session factory so the job
    # doesn't try to connect to an unavailable production PostgreSQL instance.
    from tests.conftest import TestSessionLocal

    with (
        patch("app.main.get_redis", return_value=fake_redis),
        patch("app.database.AsyncSessionLocal", new=TestSessionLocal),
    ):
        resp = await async_client.post(
            "/api/v1/tasks/run/cleanup_notifications",
            headers=_auth(token),
        )

    await fake_redis.aclose()
    assert resp.status_code == 202


@pytest.mark.asyncio
async def test_trigger_unknown_job_returns_404(async_client: AsyncClient) -> None:
    """POST /tasks/run/{job_id} returns 404 for an unrecognised job ID."""
    import fakeredis.aioredis as _fkr

    token = await _register_and_login(async_client, _reg("tj_404"))
    fake_redis = _fkr.FakeRedis()

    with patch("app.main.get_redis", return_value=fake_redis):
        resp = await async_client.post(
            "/api/v1/tasks/run/nonexistent_job_xyz",
            headers=_auth(token),
        )
    await fake_redis.aclose()

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_trigger_job_requires_auth(async_client: AsyncClient) -> None:
    """POST /tasks/run/{job_id} without an auth token returns 401."""
    resp = await async_client.post("/api/v1/tasks/run/cleanup_notifications")
    assert resp.status_code == 401


# =============================================================================
# Part B — Job function unit tests
# =============================================================================


async def _make_user(
    db: AsyncSession,
    *,
    role: UserRole = UserRole.employee,
    org_id: uuid.UUID | None = None,
) -> User:
    """Insert a minimal User row directly into the test DB."""
    user = User(
        username=f"job_{uuid.uuid4().hex[:10]}",
        email=f"job_{uuid.uuid4().hex[:10]}@example.test",
        full_name="Job Test User",
        role=role,
        hashed_password=hash_password("pass"),
        is_active=True,
        organisation_id=org_id or uuid.uuid4(),
    )
    db.add(user)
    await db.flush()
    return user


@pytest.mark.asyncio
async def test_cleanup_expired_notifications_deletes_old_read_rows(
    db_session: AsyncSession,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """
    Business rule: cleanup_expired_notifications_job deletes READ/DISMISSED
    notifications whose expires_at is in the past.  UNREAD notifications are
    never deleted automatically even if expired.
    """
    from app.tasks.jobs import cleanup_expired_notifications_job
    from tests.conftest import TestSessionLocal

    user = await _make_user(db_session)
    await db_session.commit()

    org_id = user.organisation_id
    now = datetime.now(timezone.utc)
    past = now - timedelta(days=2)

    # 1. An expired READ notification — should be deleted
    expired_read = Notification(
        recipient_id=user.id,
        organisation_id=org_id,
        notification_type=NotificationType.SCORING_COMPLETE,
        status=NotificationStatus.READ,
        title="Expired Read",
        body="body",
        expires_at=past,
    )
    # 2. An expired DISMISSED notification — should be deleted
    expired_dismissed = Notification(
        recipient_id=user.id,
        organisation_id=org_id,
        notification_type=NotificationType.SCORING_COMPLETE,
        status=NotificationStatus.DISMISSED,
        title="Expired Dismissed",
        body="body",
        expires_at=past,
    )
    # 3. An expired UNREAD notification — must NOT be deleted
    expired_unread = Notification(
        recipient_id=user.id,
        organisation_id=org_id,
        notification_type=NotificationType.SCORING_COMPLETE,
        status=NotificationStatus.UNREAD,
        title="Expired Unread",
        body="body",
        expires_at=past,
    )
    # 4. A non-expired READ notification — must NOT be deleted
    fresh_read = Notification(
        recipient_id=user.id,
        organisation_id=org_id,
        notification_type=NotificationType.SCORING_COMPLETE,
        status=NotificationStatus.READ,
        title="Fresh Read",
        body="body",
        expires_at=now + timedelta(days=30),
    )
    db_session.add_all([expired_read, expired_dismissed, expired_unread, fresh_read])
    await db_session.commit()

    # Run the job with the test session factory patched in
    with (
        patch("app.database.AsyncSessionLocal", new=TestSessionLocal),
        patch("app.main.get_redis", return_value=fake_redis),
    ):
        await cleanup_expired_notifications_job()

    # Verify: expired READ and DISMISSED are gone
    remaining = (
        await db_session.execute(
            select(Notification).where(
                Notification.recipient_id == user.id
            )
        )
    ).scalars().all()

    remaining_ids = {n.id for n in remaining}
    assert expired_read.id not in remaining_ids, "Expired READ should be deleted"
    assert expired_dismissed.id not in remaining_ids, "Expired DISMISSED should be deleted"
    assert expired_unread.id in remaining_ids, "Expired UNREAD must be preserved"
    assert fresh_read.id in remaining_ids, "Non-expired READ must be preserved"


@pytest.mark.asyncio
async def test_cleanup_expired_notifications_no_op_when_none_expired(
    db_session: AsyncSession,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """
    cleanup_expired_notifications_job completes without error when there is
    nothing to delete (empty table or all notifications are still fresh).
    """
    from app.tasks.jobs import cleanup_expired_notifications_job
    from tests.conftest import TestSessionLocal

    with (
        patch("app.database.AsyncSessionLocal", new=TestSessionLocal),
        patch("app.main.get_redis", return_value=fake_redis),
    ):
        # Should not raise
        await cleanup_expired_notifications_job()


@pytest.mark.asyncio
async def test_check_at_risk_kpis_job_triggers_notification(
    async_client: AsyncClient,
    db_session: AsyncSession,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """
    Business rule: check_at_risk_kpis_job sends a KPI_AT_RISK notification
    when a locked target has an approved actual below 60% of target value,
    and more than 25% of the cycle has elapsed.

    This test sets up real data via the HTTP API (KPI, cycle, target, actual)
    then calls the job directly, patching the DB session to use the test DB.
    """
    from tests.conftest import TestSessionLocal

    # ---------- Set up data via the HTTP API ----------
    token = await _register_and_login(async_client, _reg("tj_atrisk1"))

    with patch("app.main.get_redis", return_value=fake_redis):
        me_resp = await async_client.get("/api/v1/users/me", headers=_auth(token))
    user_id = uuid.UUID(me_resp.json()["id"])
    org_id = uuid.UUID(me_resp.json()["organisation_id"])

    with patch("app.main.get_redis", return_value=fake_redis):
        # Create KPI
        kpi_resp = await async_client.post(
            "/api/v1/kpis/",
            json={
                "name": "At-Risk KPI",
                "code": f"ATRISK_{uuid.uuid4().hex[:6].upper()}",
                "unit": "percentage",
                "frequency": "monthly",
                "data_source": "manual",
                "scoring_direction": "higher_is_better",
            },
            headers=_auth(token),
        )
        assert kpi_resp.status_code == 201, kpi_resp.text
        kpi_id = kpi_resp.json()["id"]

        # Activate KPI
        await async_client.patch(
            f"/api/v1/kpis/{kpi_id}/status",
            json={"status": "active"},
            headers=_auth(token),
        )

        # Create cycle starting well in the past so >25% has elapsed
        cycle_resp = await async_client.post(
            "/api/v1/review-cycles/",
            json={
                "name": "At-Risk Cycle",
                "cycle_type": "annual",
                "start_date": "2025-01-01",
                "end_date": "2025-12-31",
            },
            headers=_auth(token),
        )
        assert cycle_resp.status_code == 201, cycle_resp.text
        cycle_id = cycle_resp.json()["id"]

        # Activate cycle (transitions targets to LOCKED)
        await async_client.patch(
            f"/api/v1/review-cycles/{cycle_id}/status",
            json={"status": "active"},
            headers=_auth(token),
        )

        # Create a target for this user
        target_resp = await async_client.post(
            "/api/v1/targets/",
            json={
                "kpi_id": kpi_id,
                "review_cycle_id": cycle_id,
                "assignee_type": "individual",
                "assignee_user_id": str(user_id),
                "target_value": "100.00",
                "weight": "100.00",
            },
            headers=_auth(token),
        )
        assert target_resp.status_code == 201, target_resp.text
        target_id = target_resp.json()["id"]

        # Submit a low actual (40% of target → at risk)
        actual_resp = await async_client.post(
            "/api/v1/actuals/",
            json={
                "target_id": target_id,
                "period_date": "2025-04-01",
                "actual_value": "40.00",
                "notes": "Below target",
            },
            headers=_auth(token),
        )
        assert actual_resp.status_code == 201, actual_resp.text
        actual_id = actual_resp.json()["id"]

        # Approve the actual
        await async_client.patch(
            f"/api/v1/actuals/{actual_id}/status",
            json={"status": "approved"},
            headers=_auth(token),
        )

    # ---------- Run the job with test DB ----------
    with (
        patch("app.database.AsyncSessionLocal", new=TestSessionLocal),
        patch("app.main.get_redis", return_value=fake_redis),
    ):
        from app.tasks.jobs import check_at_risk_kpis_job
        await check_at_risk_kpis_job()

    # ---------- Verify at least one KPI_AT_RISK notification was created ----------
    notifications = (
        await db_session.execute(
            select(Notification).where(
                Notification.recipient_id == user_id,
                Notification.notification_type == NotificationType.KPI_AT_RISK,
            )
        )
    ).scalars().all()

    assert len(notifications) >= 1, (
        "Expected at least one KPI_AT_RISK notification for the at-risk target"
    )


@pytest.mark.asyncio
async def test_entry_reminder_not_sent_if_actual_already_submitted(
    async_client: AsyncClient,
    db_session: AsyncSession,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """
    Business rule: send_actual_entry_reminders_job skips periods for which an
    approved actual has already been submitted.  No ACTUAL_ENTRY_DUE notification
    should be created.
    """
    from tests.conftest import TestSessionLocal

    # Register user and set up data via API
    token = await _register_and_login(async_client, _reg("tj_remind1"))

    with patch("app.main.get_redis", return_value=fake_redis):
        me_resp = await async_client.get("/api/v1/users/me", headers=_auth(token))
    user_id = uuid.UUID(me_resp.json()["id"])

    with patch("app.main.get_redis", return_value=fake_redis):
        kpi_resp = await async_client.post(
            "/api/v1/kpis/",
            json={
                "name": "Reminder KPI",
                "code": f"REM_{uuid.uuid4().hex[:6].upper()}",
                "unit": "count",
                "frequency": "monthly",
                "data_source": "manual",
                "scoring_direction": "higher_is_better",
            },
            headers=_auth(token),
        )
        kpi_id = kpi_resp.json()["id"]

        await async_client.patch(
            f"/api/v1/kpis/{kpi_id}/status",
            json={"status": "active"},
            headers=_auth(token),
        )

        cycle_resp = await async_client.post(
            "/api/v1/review-cycles/",
            json={
                "name": "Reminder Cycle",
                "cycle_type": "annual",
                "start_date": "2025-01-01",
                "end_date": "2025-12-31",
            },
            headers=_auth(token),
        )
        cycle_id = cycle_resp.json()["id"]

        await async_client.patch(
            f"/api/v1/review-cycles/{cycle_id}/status",
            json={"status": "active"},
            headers=_auth(token),
        )

        target_resp = await async_client.post(
            "/api/v1/targets/",
            json={
                "kpi_id": kpi_id,
                "review_cycle_id": cycle_id,
                "assignee_type": "individual",
                "assignee_user_id": str(user_id),
                "target_value": "100.00",
                "weight": "100.00",
            },
            headers=_auth(token),
        )
        target_id = target_resp.json()["id"]

        # Submit and approve an actual for January — the reminder should be skipped
        actual_resp = await async_client.post(
            "/api/v1/actuals/",
            json={
                "target_id": target_id,
                "period_date": "2025-01-01",
                "actual_value": "90.00",
            },
            headers=_auth(token),
        )
        actual_id = actual_resp.json()["id"]

        await async_client.patch(
            f"/api/v1/actuals/{actual_id}/status",
            json={"status": "approved"},
            headers=_auth(token),
        )

    # Run the reminder job
    with (
        patch("app.database.AsyncSessionLocal", new=TestSessionLocal),
        patch("app.main.get_redis", return_value=fake_redis),
    ):
        from app.tasks.jobs import send_actual_entry_reminders_job
        await send_actual_entry_reminders_job()

    # Verify no ACTUAL_ENTRY_DUE notification for the January period that was submitted
    notifs = (
        await db_session.execute(
            select(Notification).where(
                Notification.recipient_id == user_id,
                Notification.notification_type == NotificationType.ACTUAL_ENTRY_DUE,
            )
        )
    ).scalars().all()

    # All existing notifs should NOT relate to the period with a submitted actual.
    # The simplest business-level check: the service skipped Jan 2025 because an
    # approved actual exists for that date.
    jan_notifs = [n for n in notifs if "Jan 2025" in n.body]
    assert len(jan_notifs) == 0, (
        "Reminder must not be sent for periods with an approved actual"
    )


@pytest.mark.asyncio
async def test_period_closing_reminder_debounced(
    db_session: AsyncSession,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """
    Business rule: notify_period_closing is debounced per (cycle, days) pair.
    When the Redis debounce key is already set, calling the method returns 0.
    """
    svc = NotificationService(fake_redis)
    cycle_id = uuid.uuid4()
    days = 7

    # Pre-set the debounce key as if the reminder was already sent today
    debounce_key = f"notif:period_closing:{cycle_id}:{days}"
    await fake_redis.setex(debounce_key, 86400, "1")

    count = await svc.notify_period_closing(db_session, cycle_id, days)
    assert count == 0, "Period closing reminder must be suppressed by the debounce key"


@pytest.mark.asyncio
async def test_send_period_closing_reminders_job_runs_without_error(
    db_session: AsyncSession,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """
    send_period_closing_reminders_job should complete without raising even
    when there are no active cycles in the database.
    """
    from tests.conftest import TestSessionLocal
    from app.tasks.jobs import send_period_closing_reminders_job

    with (
        patch("app.database.AsyncSessionLocal", new=TestSessionLocal),
        patch("app.main.get_redis", return_value=fake_redis),
    ):
        await send_period_closing_reminders_job()
