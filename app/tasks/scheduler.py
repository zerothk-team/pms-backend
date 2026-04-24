"""
APScheduler setup for background jobs.

Uses APScheduler 3.x AsyncIOScheduler so all jobs run in the same event loop
as FastAPI.  Jobs are registered via registry.py and the scheduler lifecycle
is managed from app/main.py.

Production recommendation:
- Migrate to Celery + Redis Beat for distributed deployments.
- APScheduler is sufficient for a single-process deployment.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger("pms.scheduler")

# Shared scheduler instance — initialised once, reused across the process.
scheduler = AsyncIOScheduler(timezone="UTC")


def start_scheduler(app) -> None:
    """
    Register all jobs and start the scheduler.

    Called from app/main.py lifespan on startup when not in DEBUG/test mode.
    The scheduler instance is stored on app.state for easy access.
    """
    from app.tasks.registry import register_jobs

    register_jobs(scheduler)
    scheduler.start()
    app.state.scheduler = scheduler
    logger.info("Scheduler started — %d job(s) registered", len(scheduler.get_jobs()))


def stop_scheduler(app) -> None:
    """
    Gracefully stop the scheduler.

    Called from app/main.py lifespan on shutdown.
    wait=False means in-flight jobs are not waited on (acceptable for I/O jobs).
    """
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
