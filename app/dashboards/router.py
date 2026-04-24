"""
Dashboards router — all endpoints under /api/v1/dashboards.

Prefix: /dashboards
Tags:   Dashboards

These are read-only aggregation endpoints optimised for frontend consumption.
"""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.dashboards.schemas import (
    EmployeeDashboard,
    KPIProgressReport,
    LeaderboardEntry,
    ManagerDashboard,
    OrgDashboard,
)
from app.dashboards.service import DashboardService
from app.database import get_db
from app.dependencies import get_current_active_user, require_roles
from app.exceptions import ForbiddenException
from app.users.models import User, UserRole

router = APIRouter(prefix="/dashboards", tags=["Dashboards"])
_service = DashboardService()


def _org_id(user: User) -> UUID:
    if not user.organisation_id:
        raise ForbiddenException("User is not associated with an organisation.")
    return user.organisation_id


# ---------------------------------------------------------------------------
# Employee dashboard
# ---------------------------------------------------------------------------


@router.get(
    "/me",
    response_model=EmployeeDashboard,
    summary="Employee personal dashboard",
    description=(
        "Returns the full personal performance dashboard for the requesting employee. "
        "Includes: active cycle info, all KPI targets with latest actuals, achievement "
        "percentages, risk flags, trend direction, and composite score (if scoring has run). "
        "Any authenticated user can access their own dashboard."
    ),
)
async def employee_dashboard(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> EmployeeDashboard:
    """Personal KPI performance dashboard."""
    return await _service.get_employee_dashboard(db, current_user.id, _org_id(current_user))


# ---------------------------------------------------------------------------
# Manager dashboard
# ---------------------------------------------------------------------------


@router.get(
    "/team",
    response_model=ManagerDashboard,
    summary="Manager team dashboard",
    description=(
        "Returns the team performance summary for the requesting manager. "
        "Shows each direct report's KPI count, actuals submitted, overall achievement, "
        "at-risk KPI count, and composite score. "
        "Also shows pending approval counts and team rating distribution. "
        "Managers, executives, and HR admins can access this."
    ),
)
async def manager_dashboard(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> ManagerDashboard:
    """Team performance dashboard for managers."""
    if current_user.role not in {UserRole.manager, UserRole.hr_admin, UserRole.executive}:
        raise ForbiddenException("Only managers, executives, and HR admins can view team dashboards.")
    return await _service.get_manager_dashboard(db, current_user.id, _org_id(current_user))


# ---------------------------------------------------------------------------
# Org dashboard
# ---------------------------------------------------------------------------


@router.get(
    "/org",
    response_model=OrgDashboard,
    summary="Organisation overview dashboard (active cycle)",
    description=(
        "Returns the organisation-wide performance overview using the currently ACTIVE cycle. "
        "Includes: employee coverage stats, average achievement, department breakdown, "
        "top at-risk KPIs, score distribution (bell curve data), and cycle progress %. "
        "Executives and HR admins only."
    ),
)
async def org_dashboard(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles("hr_admin", "executive"))],
) -> OrgDashboard:
    """Organisation-wide performance dashboard (active cycle)."""
    return await _service.get_org_dashboard(db, _org_id(current_user))


@router.get(
    "/org/{cycle_id}",
    response_model=OrgDashboard,
    summary="Organisation dashboard for a specific cycle",
    description=(
        "Same as /dashboards/org but for a specific past (or current) review cycle. "
        "Useful for reviewing historical performance. "
        "Executives and HR admins only."
    ),
)
async def org_dashboard_for_cycle(
    cycle_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles("hr_admin", "executive"))],
) -> OrgDashboard:
    """Organisation dashboard for a specific review cycle."""
    return await _service.get_org_dashboard(db, _org_id(current_user), cycle_id=cycle_id)


# ---------------------------------------------------------------------------
# KPI progress report
# ---------------------------------------------------------------------------


@router.get(
    "/kpi/{kpi_id}/progress",
    response_model=KPIProgressReport,
    summary="KPI progress report (active cycle)",
    description=(
        "Reports on a single KPI across all assigned employees in the active cycle. "
        "Shows each user's target, latest actual, achievement %, and time-series data. "
        "Useful for identifying which employees are on track vs. at risk for a given KPI. "
        "HR admins, executives, and managers can access this."
    ),
)
async def kpi_progress(
    kpi_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> KPIProgressReport:
    """KPI progress report using the active cycle."""
    if current_user.role == UserRole.employee:
        raise ForbiddenException("Employees cannot view KPI progress across the org.")

    from app.dashboards.service import _get_active_cycle
    from app.exceptions import NotFoundException

    org_id = _org_id(current_user)
    cycle = await _get_active_cycle(db, org_id)
    if not cycle:
        raise NotFoundException("No active review cycle found.")
    return await _service.get_kpi_progress_report(db, kpi_id, cycle.id, org_id)


@router.get(
    "/kpi/{kpi_id}/progress/{cycle_id}",
    response_model=KPIProgressReport,
    summary="KPI progress report for a specific cycle",
    description=(
        "Same as /dashboards/kpi/{kpi_id}/progress but for a specific review cycle. "
        "Enables historical KPI analysis."
    ),
)
async def kpi_progress_for_cycle(
    kpi_id: UUID,
    cycle_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> KPIProgressReport:
    """KPI progress report for a specific cycle."""
    if current_user.role == UserRole.employee:
        raise ForbiddenException("Employees cannot view KPI progress across the org.")
    return await _service.get_kpi_progress_report(
        db, kpi_id, cycle_id, _org_id(current_user)
    )


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------


@router.get(
    "/leaderboard/{cycle_id}",
    response_model=list[LeaderboardEntry],
    summary="Performance leaderboard",
    description=(
        "Returns the top performers by composite score for the given cycle. "
        "HR admins and executives see the full org. "
        "Managers see only their direct reports. "
        "Employees cannot access the leaderboard. "
        "Only employees with at least one approved actual are included."
    ),
)
async def leaderboard(
    cycle_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    limit: int = Query(default=10, ge=1, le=50),
) -> list[LeaderboardEntry]:
    """Top performers for a review cycle."""
    if current_user.role == UserRole.employee:
        raise ForbiddenException("Employees cannot access the leaderboard.")

    org_id = _org_id(current_user)
    manager_id: UUID | None = None
    if current_user.role == UserRole.manager:
        manager_id = current_user.id

    return await _service.get_leaderboard(
        db, cycle_id, org_id, manager_id=manager_id, limit=limit
    )


# ---------------------------------------------------------------------------
# CSV Export
# ---------------------------------------------------------------------------


@router.get(
    "/export/{cycle_id}",
    response_class=StreamingResponse,
    summary="Export all scores to CSV",
    description=(
        "Downloads a CSV file with all performance scores for the given review cycle. "
        "Columns: employee_name, email, manager_name, kpi_code, kpi_name, target_value, "
        "final_actual, achievement_pct, weighted_score, composite_score, rating, score_status. "
        "HR admins only."
    ),
)
async def export_scores_csv(
    cycle_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles("hr_admin"))],
) -> StreamingResponse:
    """Stream a CSV export of all scores for the cycle."""
    import io

    csv_content = await _service.export_scores_csv(db, cycle_id, _org_id(current_user))
    filename = f"scores_{cycle_id}_{date.today().isoformat()}.csv"

    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
