"""
Job registration — maps job IDs to their functions and triggers.

All cron expressions use UTC.  misfire_grace_time=3600 means if the job
was missed (e.g. server was down) and the missed run is within 1 hour,
APScheduler will run it immediately on restart.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger("pms.scheduler")


def register_jobs(scheduler: AsyncIOScheduler) -> None:
    """Register all background jobs with the scheduler."""
    from app.tasks.jobs import (
        auto_close_cycle_job,
        auto_compute_formula_actuals_job,
        check_at_risk_kpis_job,
        cleanup_expired_notifications_job,
        send_actual_entry_reminders_job,
        send_period_closing_reminders_job,
    )

    scheduler.add_job(
        check_at_risk_kpis_job,
        CronTrigger(hour=8, minute=0),
        id="check_at_risk_kpis",
        name="Check At-Risk KPIs",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        send_actual_entry_reminders_job,
        CronTrigger(hour=9, minute=0, day_of_week="mon-fri"),
        id="entry_reminders",
        name="Actual Entry Reminders",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        send_period_closing_reminders_job,
        CronTrigger(hour=7, minute=0),
        id="period_closing_reminders",
        name="Period Closing Reminders",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        auto_compute_formula_actuals_job,
        CronTrigger(day=1, hour=0, minute=30),
        id="formula_actuals",
        name="Auto-Compute Formula Actuals",
        replace_existing=True,
        misfire_grace_time=7200,
    )

    scheduler.add_job(
        auto_close_cycle_job,
        CronTrigger(hour=0, minute=0),
        id="auto_close_cycle",
        name="Auto-Close Expired Review Cycles",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        cleanup_expired_notifications_job,
        CronTrigger(day_of_week="sun", hour=3, minute=0),
        id="cleanup_notifications",
        name="Cleanup Expired Notifications",
        replace_existing=True,
        misfire_grace_time=7200,
    )

    logger.info(
        "Registered %d background jobs: %s",
        len(scheduler.get_jobs()),
        [j.id for j in scheduler.get_jobs()],
    )
