"""
Background job functions.

Each job is a standalone async function that:
1. Creates its own DB session (not via FastAPI DI).
2. Creates its own NotificationService with the global Redis connection.
3. Commits/rolls back its own transaction.
4. Emits structured log lines for monitoring.

Error handling: each job catches and logs exceptions so a failure in one job
does not prevent other jobs from running.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

logger = logging.getLogger("pms.jobs")


def _get_session_factory():
    from app.database import AsyncSessionLocal
    return AsyncSessionLocal


def _get_redis():
    from app.main import get_redis
    return get_redis()


def _get_notification_service():
    from app.notifications.service import NotificationService
    return NotificationService(_get_redis())


# ---------------------------------------------------------------------------
# Job 1: Check at-risk KPIs  (daily 08:00 UTC)
# ---------------------------------------------------------------------------


async def check_at_risk_kpis_job() -> None:
    """
    Check all locked targets in active cycles and flag at-risk KPIs.

    A target is considered "at risk" when:
    - The review cycle is ACTIVE.
    - The target is LOCKED.
    - Achievement percentage < 60%.
    - We are past 25% of the cycle duration (gives users time to submit data).

    For each at-risk target:
    - Sets target.is_at_risk = True in the DB.
    - Triggers notify_kpi_at_risk() (debounced per target per 24 h).
    """
    from decimal import Decimal

    from sqlalchemy import select

    from app.actuals.enums import ActualEntryStatus
    from app.actuals.models import KPIActual
    from app.kpis.models import KPI
    from app.review_cycles.enums import CycleStatus
    from app.review_cycles.models import ReviewCycle
    from app.scoring.calculator import compute_achievement_percentage
    from app.targets.enums import TargetStatus
    from app.targets.models import KPITarget

    SessionLocal = _get_session_factory()
    svc = _get_notification_service()
    today = date.today()

    checked = 0
    at_risk = 0
    notified = 0

    try:
        async with SessionLocal() as db:
            # Load all ACTIVE cycles
            cycles_result = await db.execute(
                select(ReviewCycle).where(ReviewCycle.status == CycleStatus.ACTIVE)
            )
            cycles = cycles_result.scalars().all()

            for cycle in cycles:
                # Only start alerting once 25% of the cycle has elapsed
                cycle_days = (cycle.end_date - cycle.start_date).days
                elapsed_days = (today - cycle.start_date).days
                if cycle_days == 0 or elapsed_days / cycle_days < 0.25:
                    continue

                # Load locked individual targets for this cycle
                targets_result = await db.execute(
                    select(KPITarget).where(
                        KPITarget.review_cycle_id == cycle.id,
                        KPITarget.status == TargetStatus.LOCKED,
                        KPITarget.assignee_user_id.isnot(None),
                    )
                )
                targets = targets_result.scalars().all()

                for target in targets:
                    checked += 1

                    # Latest approved actual
                    actual_result = await db.execute(
                        select(KPIActual)
                        .where(
                            KPIActual.target_id == target.id,
                            KPIActual.status == ActualEntryStatus.APPROVED,
                        )
                        .order_by(KPIActual.period_date.desc())
                        .limit(1)
                    )
                    actual = actual_result.scalar_one_or_none()
                    if not actual:
                        # No data yet — entry reminders job handles this case
                        continue

                    kpi_result = await db.execute(
                        select(KPI).where(KPI.id == target.kpi_id)
                    )
                    kpi = kpi_result.scalar_one_or_none()
                    if not kpi:
                        continue

                    achievement_pct = compute_achievement_percentage(
                        actual.actual_value,
                        target.target_value,
                        kpi.scoring_direction,
                        target.minimum_value,
                    )

                    if achievement_pct < Decimal("60"):
                        at_risk += 1
                        notifications = await svc.notify_kpi_at_risk(
                            db, target.id, achievement_pct
                        )
                        notified += len(notifications)

            await db.commit()

        logger.info(
            "check_at_risk_kpis_job: checked=%d at_risk=%d notifications_sent=%d",
            checked, at_risk, notified,
        )

    except Exception:
        logger.exception("check_at_risk_kpis_job failed")


# ---------------------------------------------------------------------------
# Job 2: Send actual entry reminders  (Mon–Fri 09:00 UTC)
# ---------------------------------------------------------------------------


async def send_actual_entry_reminders_job() -> None:
    """
    Remind employees to submit overdue actual entries.

    For each locked target in an active cycle, determine the expected period
    dates based on the KPI's measurement frequency.  If there is missing data
    for a period whose deadline has passed, send a reminder.

    Grace period: 2 days after period end before sending the reminder.
    """
    from sqlalchemy import select

    from app.actuals.enums import ActualEntryStatus
    from app.actuals.models import KPIActual
    from app.kpis.models import KPI
    from app.review_cycles.enums import CycleStatus
    from app.review_cycles.models import ReviewCycle
    from app.targets.enums import TargetStatus
    from app.targets.models import KPITarget

    GRACE_DAYS = 2
    SessionLocal = _get_session_factory()
    svc = _get_notification_service()
    today = date.today()
    reminders_sent = 0

    try:
        async with SessionLocal() as db:
            cycles_result = await db.execute(
                select(ReviewCycle).where(ReviewCycle.status == CycleStatus.ACTIVE)
            )
            cycles = cycles_result.scalars().all()

            for cycle in cycles:
                targets_result = await db.execute(
                    select(KPITarget).where(
                        KPITarget.review_cycle_id == cycle.id,
                        KPITarget.status == TargetStatus.LOCKED,
                        KPITarget.assignee_user_id.isnot(None),
                    )
                )
                targets = targets_result.scalars().all()

                for target in targets:
                    kpi_result = await db.execute(
                        select(KPI).where(KPI.id == target.kpi_id)
                    )
                    kpi = kpi_result.scalar_one_or_none()
                    if not kpi:
                        continue

                    # Determine expected period dates within the cycle up to today
                    from app.review_cycles.service import ReviewCycleService
                    cycle_svc = ReviewCycleService()
                    expected_periods = cycle_svc.get_current_measurement_periods(
                        cycle, kpi.frequency
                    )

                    for period_date in expected_periods:
                        # Only remind for periods that are past the grace period
                        from datetime import timedelta
                        grace_deadline = period_date + timedelta(days=GRACE_DAYS)
                        if grace_deadline > today:
                            continue  # Not yet overdue

                        # Check if actual exists and is not superseded
                        actual_result = await db.execute(
                            select(KPIActual).where(
                                KPIActual.target_id == target.id,
                                KPIActual.period_date == period_date,
                                KPIActual.status != ActualEntryStatus.SUPERSEDED,
                            )
                        )
                        if actual_result.scalar_one_or_none():
                            continue  # Already submitted

                        n = await svc.notify_actual_entry_due(db, target.id, period_date)
                        if n:
                            reminders_sent += 1

            await db.commit()

        logger.info("send_actual_entry_reminders_job: reminders_sent=%d", reminders_sent)

    except Exception:
        logger.exception("send_actual_entry_reminders_job failed")


# ---------------------------------------------------------------------------
# Job 3: Period closing reminders  (daily 07:00 UTC)
# ---------------------------------------------------------------------------


async def send_period_closing_reminders_job() -> None:
    """
    Send closing-soon alerts at 7, 3 and 1 day(s) before cycle end.

    Each combination of (cycle_id, days_until_close) is debounced for 24 h
    so users are only alerted once per threshold.
    """
    from sqlalchemy import select

    from app.review_cycles.enums import CycleStatus
    from app.review_cycles.models import ReviewCycle

    ALERT_THRESHOLDS = [7, 3, 1]
    SessionLocal = _get_session_factory()
    svc = _get_notification_service()
    today = date.today()
    total_sent = 0

    try:
        async with SessionLocal() as db:
            cycles_result = await db.execute(
                select(ReviewCycle).where(ReviewCycle.status == CycleStatus.ACTIVE)
            )
            cycles = cycles_result.scalars().all()

            for cycle in cycles:
                days_left = (cycle.end_date - today).days
                if days_left in ALERT_THRESHOLDS:
                    count = await svc.notify_period_closing(db, cycle.id, days_left)
                    total_sent += count

            await db.commit()

        logger.info("send_period_closing_reminders_job: notifications_sent=%d", total_sent)

    except Exception:
        logger.exception("send_period_closing_reminders_job failed")


# ---------------------------------------------------------------------------
# Job 4: Auto-compute formula actuals  (1st of month 00:30 UTC)
# ---------------------------------------------------------------------------


async def auto_compute_formula_actuals_job() -> None:
    """
    Auto-generate KPIActual rows for formula-based KPIs.

    Runs on the first of each month and inserts actuals for the just-closed
    calendar month.  Uses FormulaEvaluator to resolve the formula value.
    Entry source is set to AUTO_FORMULA.
    """
    from decimal import Decimal as _Decimal

    from sqlalchemy import select

    from app.actuals.enums import ActualEntrySource, ActualEntryStatus
    from app.actuals.models import KPIActual
    from app.kpis.enums import DataSourceType
    from app.kpis.formula import FormulaEvaluator
    from app.kpis.models import KPI
    from app.review_cycles.enums import CycleStatus
    from app.review_cycles.models import ReviewCycle
    from app.targets.enums import TargetStatus
    from app.targets.models import KPITarget

    SessionLocal = _get_session_factory()
    today = date.today()
    # Period = previous calendar month
    if today.month == 1:
        period_year = today.year - 1
        period_month = 12
    else:
        period_year = today.year
        period_month = today.month - 1
    period_date = date(period_year, period_month, 1)

    created_count = 0

    try:
        async with SessionLocal() as db:
            # Only interested in FORMULA KPIs in ACTIVE cycles
            cycles_result = await db.execute(
                select(ReviewCycle).where(ReviewCycle.status == CycleStatus.ACTIVE)
            )
            cycles = cycles_result.scalars().all()
            evaluator = FormulaEvaluator()

            for cycle in cycles:
                targets_result = await db.execute(
                    select(KPITarget)
                    .join(KPI, KPI.id == KPITarget.kpi_id)
                    .where(
                        KPITarget.review_cycle_id == cycle.id,
                        KPITarget.status == TargetStatus.LOCKED,
                        KPI.data_source == DataSourceType.FORMULA,
                        KPITarget.assignee_user_id.isnot(None),
                    )
                )
                targets = targets_result.scalars().all()

                for target in targets:
                    kpi_result = await db.execute(
                        select(KPI).where(KPI.id == target.kpi_id)
                    )
                    kpi = kpi_result.scalar_one_or_none()
                    if not kpi or not kpi.formula_expression:
                        continue

                    # Skip if already exists for this period
                    existing = await db.execute(
                        select(KPIActual).where(
                            KPIActual.target_id == target.id,
                            KPIActual.period_date == period_date,
                            KPIActual.status != ActualEntryStatus.SUPERSEDED,
                        )
                    )
                    if existing.scalar_one_or_none():
                        continue

                    try:
                        # Resolve dependency KPI actuals for this period
                        kpi_values = await _resolve_formula_values(
                            db, kpi, period_date
                        )
                        raw_value = evaluator.evaluate(kpi.formula_expression, kpi_values)
                        value = _Decimal(str(raw_value))
                    except Exception as e:
                        logger.warning(
                            "Formula eval failed for kpi=%s period=%s: %s",
                            kpi.id, period_date, e,
                        )
                        continue

                    actual = KPIActual(
                        target_id=target.id,
                        kpi_id=kpi.id,
                        period_date=period_date,
                        period_label=period_date.strftime("%b %Y"),
                        actual_value=value,
                        entry_source=ActualEntrySource.AUTO_FORMULA,
                        status=ActualEntryStatus.APPROVED,
                        submitted_by_id=target.set_by_id,
                        notes=f"Auto-computed from formula: {kpi.formula_expression}",
                    )
                    db.add(actual)
                    created_count += 1

            await db.commit()

        logger.info(
            "auto_compute_formula_actuals_job: created=%d period=%s",
            created_count, period_date,
        )

    except Exception:
        logger.exception("auto_compute_formula_actuals_job failed")


async def _resolve_formula_values(db, kpi, period_date: date) -> dict[str, float]:
    """
    Resolve the dependency KPI codes to their actual values for the given period.

    For each code referenced in the KPI's formula, look up the most recent
    approved actual up to and including the period_date.
    """
    from sqlalchemy import select

    from app.actuals.enums import ActualEntryStatus
    from app.actuals.models import KPIActual
    from app.kpis.formula import FormulaParser
    from app.kpis.models import KPI

    parser = FormulaParser()
    refs = parser.extract_kpi_references(kpi.formula_expression or "")

    kpi_values: dict[str, float] = {}
    for code in refs:
        # Find the KPI with this code in the same org
        dep_result = await db.execute(
            select(KPI).where(
                KPI.code == code,
                KPI.organisation_id == kpi.organisation_id,
            )
        )
        dep_kpi = dep_result.scalar_one_or_none()
        if not dep_kpi:
            continue

        # Find the most recent approved actual for this dependency KPI
        actual_result = await db.execute(
            select(KPIActual)
            .where(
                KPIActual.kpi_id == dep_kpi.id,
                KPIActual.period_date <= period_date,
                KPIActual.status == ActualEntryStatus.APPROVED,
            )
            .order_by(KPIActual.period_date.desc())
            .limit(1)
        )
        actual = actual_result.scalar_one_or_none()
        if actual:
            kpi_values[code] = float(actual.actual_value)

    return kpi_values


# ---------------------------------------------------------------------------
# Job 5: Auto-close expired cycles  (daily 00:00 UTC)
# ---------------------------------------------------------------------------


async def auto_close_cycle_job() -> None:
    """
    Close review cycles whose end date has passed and compute scores.

    Transition: ACTIVE → CLOSED
    Triggers:
    1. Lock all targets in the cycle.
    2. Run the scoring engine.
    3. Notify HR admins that scoring is complete.
    """
    from sqlalchemy import select

    from app.review_cycles.enums import CycleStatus
    from app.review_cycles.models import ReviewCycle
    from app.scoring.service import ScoringEngine

    SessionLocal = _get_session_factory()
    svc = _get_notification_service()
    today = date.today()
    cycles_closed = 0
    scores_computed = 0

    try:
        async with SessionLocal() as db:
            # Find ACTIVE cycles whose actual_entry_deadline (or end_date) has passed
            cycles_result = await db.execute(
                select(ReviewCycle).where(ReviewCycle.status == CycleStatus.ACTIVE)
            )
            cycles = cycles_result.scalars().all()

            for cycle in cycles:
                deadline = cycle.actual_entry_deadline or cycle.end_date
                if deadline >= today:
                    continue

                # 1. Close the cycle
                cycle.status = CycleStatus.CLOSED
                cycle.updated_at = datetime.now(timezone.utc)
                cycles_closed += 1

                # 2. Lock all targets in this cycle
                from app.review_cycles.service import ReviewCycleService
                cycle_svc = ReviewCycleService()
                locked = await cycle_svc._lock_targets_for_cycle(db, cycle.id)
                logger.info("Locked %d targets for cycle %s", locked, cycle.id)

                # 3. Compute scores
                try:
                    engine = ScoringEngine()
                    score_result = await engine.compute_scores_for_cycle(
                        db, cycle.id, cycle.organisation_id
                    )
                    scores_computed += score_result.get("employees_scored", 0)

                    # 4. Notify HR admins
                    from app.notifications.enums import NotificationType
                    from app.users.models import User, UserRole
                    admins_result = await db.execute(
                        select(User).where(
                            User.organisation_id == cycle.organisation_id,
                            User.role == UserRole.hr_admin,
                            User.is_active == True,
                        )
                    )
                    admins = admins_result.scalars().all()
                    for admin in admins:
                        await svc.create_notification(
                            db,
                            recipient_id=admin.id,
                            org_id=cycle.organisation_id,
                            notification_type=NotificationType.SCORING_COMPLETE,
                            context={
                                "cycle_name": cycle.name,
                                "cycle_id": str(cycle.id),
                                "employee_count": score_result.get("employees_scored", 0),
                            },
                        )

                except Exception:
                    logger.exception("Score computation failed for cycle %s", cycle.id)

            await db.commit()

        logger.info(
            "auto_close_cycle_job: cycles_closed=%d scores_computed=%d",
            cycles_closed, scores_computed,
        )

    except Exception:
        logger.exception("auto_close_cycle_job failed")


# ---------------------------------------------------------------------------
# Job 6: Cleanup expired notifications  (Sunday 03:00 UTC)
# ---------------------------------------------------------------------------


async def cleanup_expired_notifications_job() -> None:
    """
    Delete READ/DISMISSED notifications whose expires_at has passed.

    UNREAD notifications are never deleted automatically — they expire visually
    in the UI but remain in the DB for audit.
    """
    from sqlalchemy import delete

    from app.notifications.enums import NotificationStatus
    from app.notifications.models import Notification

    SessionLocal = _get_session_factory()
    now = datetime.now(timezone.utc)
    deleted = 0

    try:
        async with SessionLocal() as db:
            result = await db.execute(
                delete(Notification).where(
                    Notification.expires_at < now,
                    Notification.status != NotificationStatus.UNREAD,
                )
            )
            deleted = result.rowcount  # type: ignore[assignment]
            await db.commit()

        logger.info("cleanup_expired_notifications_job: deleted=%d", deleted)

    except Exception:
        logger.exception("cleanup_expired_notifications_job failed")
