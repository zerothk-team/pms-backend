"""
Admin endpoints for background task management.

Access restricted to hr_admin only.  These endpoints allow manual triggering
of background jobs for testing / on-demand re-runs.

Endpoints:
    GET  /tasks/jobs/           → list all registered jobs with next-run time
    POST /tasks/run/{job_id}    → trigger a job immediately (async, fire-and-forget)
"""

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from app.dependencies import get_current_active_user, require_roles
from app.users.models import User

router = APIRouter(prefix="/tasks", tags=["Background Tasks"])
logger = logging.getLogger("pms.tasks")

# Map of known job IDs → their async callables (for manual triggering)
_JOB_REGISTRY: dict[str, str] = {
    "check_at_risk_kpis": "app.tasks.jobs.check_at_risk_kpis_job",
    "entry_reminders": "app.tasks.jobs.send_actual_entry_reminders_job",
    "period_closing_reminders": "app.tasks.jobs.send_period_closing_reminders_job",
    "formula_actuals": "app.tasks.jobs.auto_compute_formula_actuals_job",
    "auto_close_cycle": "app.tasks.jobs.auto_close_cycle_job",
    "cleanup_notifications": "app.tasks.jobs.cleanup_expired_notifications_job",
}


@router.get(
    "/jobs/",
    summary="List all scheduled jobs",
    description="Returns all registered APScheduler jobs with their next scheduled run time.",
)
async def list_jobs(
    current_user: Annotated[User, Depends(require_roles("hr_admin"))],
) -> list[dict]:
    from app.tasks.scheduler import scheduler

    jobs = []
    for job in scheduler.get_jobs():
        next_run = job.next_run_time
        jobs.append(
            {
                "id": job.id,
                "name": job.name,
                "next_run_time": next_run.isoformat() if next_run else None,
                "trigger": str(job.trigger),
            }
        )
    return jobs


@router.post(
    "/run/{job_id}",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Manually trigger a background job",
    description=(
        "Queues the specified job for immediate execution.  "
        "The response is returned immediately — job runs asynchronously in the background.  "
        "Restricted to hr_admin."
    ),
)
async def run_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(require_roles("hr_admin"))],
) -> dict:
    if job_id not in _JOB_REGISTRY:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found. Valid jobs: {list(_JOB_REGISTRY.keys())}",
        )

    module_path, func_name = _JOB_REGISTRY[job_id].rsplit(".", 1)
    import importlib
    module = importlib.import_module(module_path)
    job_fn = getattr(module, func_name)

    async def _run():
        logger.info("Manual job trigger: job_id=%s triggered_by=%s", job_id, current_user.id)
        try:
            await job_fn()
        except Exception:
            logger.exception("Manual job execution failed: job_id=%s", job_id)

    background_tasks.add_task(_run)

    return {
        "accepted": True,
        "job_id": job_id,
        "message": f"Job '{job_id}' queued for immediate execution.",
        "triggered_by": str(current_user.id),
    }
