"""
Pydantic v2 schemas for dashboard response payloads.

These are read-only aggregation views consumed by the React frontend.
They deliberately denormalise data to minimise round-trips.
"""

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.kpis.enums import DepartmentCategory, MeasurementUnit
from app.scoring.enums import RatingLabel, ScoreStatus


# ---------------------------------------------------------------------------
# Shared building blocks
# ---------------------------------------------------------------------------


class UserSummary(BaseModel):
    """Minimal user representation used inside dashboard cards."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    full_name: str
    email: str
    role: str


class ReviewCycleSummary(BaseModel):
    """Slim review cycle representation for dashboard context."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    cycle_type: str
    status: str
    start_date: date
    end_date: date


# ---------------------------------------------------------------------------
# Employee dashboard
# ---------------------------------------------------------------------------


class KPISummaryCard(BaseModel):
    """
    One card on the employee's personal KPI list.

    Combines target, latest actual, computed achievement, and trend
    so the frontend can render a progress bar and risk badge in one pass.
    """

    target_id: UUID
    kpi_id: UUID
    kpi_name: str
    kpi_code: str
    kpi_unit: MeasurementUnit
    target_value: Decimal
    latest_actual: Decimal | None
    achievement_percentage: Decimal | None
    rating: RatingLabel | None
    weight: Decimal
    is_at_risk: bool
    trend: Literal["improving", "declining", "stable", "no_data"]
    next_period_date: date | None


class EmployeeDashboard(BaseModel):
    """
    Everything a single employee needs to render their personal dashboard.

    - kpi_summary lists all assigned KPIs with progress.
    - at_risk_count is a quick-access badge count.
    - pending_actuals_count drives the "missing entry" warning.
    """

    user: UserSummary
    active_cycle: ReviewCycleSummary | None
    kpi_summary: list[KPISummaryCard]
    overall_score: Decimal | None
    overall_rating: RatingLabel | None
    score_status: ScoreStatus | None
    at_risk_count: int
    pending_actuals_count: int


# ---------------------------------------------------------------------------
# Manager dashboard
# ---------------------------------------------------------------------------


class TeamMemberSummary(BaseModel):
    """
    A row in the manager's team overview table.

    Shows each direct report's progress at a glance.
    """

    user: UserSummary
    kpi_count: int
    actuals_submitted: int
    overall_achievement: Decimal | None
    overall_rating: RatingLabel | None
    at_risk_kpis: int
    pending_actuals: int
    score_status: ScoreStatus | None


class ManagerDashboard(BaseModel):
    """
    Manager view: team-level summary.

    team_overview is the main table; team_distribution is the chart data.
    """

    manager: UserSummary
    active_cycle: ReviewCycleSummary | None
    team_size: int
    team_overview: list[TeamMemberSummary]
    at_risk_count: int
    pending_approvals_count: int
    team_average_score: Decimal | None
    team_distribution: dict[str, int]  # RatingLabel.value → count


# ---------------------------------------------------------------------------
# Org dashboard
# ---------------------------------------------------------------------------


class DepartmentSummary(BaseModel):
    """Per-department breakdown on the executive dashboard."""

    department: DepartmentCategory
    employee_count: int
    avg_achievement: Decimal | None
    avg_rating: RatingLabel | None
    at_risk_count: int


class KPIAtRiskSummary(BaseModel):
    """A KPI that has a high number of employees below the at-risk threshold."""

    kpi_id: UUID
    kpi_name: str
    affected_users: int
    avg_achievement: Decimal


class OrgDashboard(BaseModel):
    """
    Executive/HR dashboard: organisation-wide view.

    department_breakdown drives the department comparison chart.
    score_distribution (from compute_score_distribution) drives the bell curve.
    period_progress shows what % of the cycle has elapsed.
    """

    active_cycle: ReviewCycleSummary | None
    total_employees: int
    employees_with_targets: int
    employees_with_actuals: int
    avg_achievement: Decimal | None
    department_breakdown: list[DepartmentSummary]
    top_kpis_at_risk: list[KPIAtRiskSummary]
    score_distribution: dict
    period_progress: Decimal


# ---------------------------------------------------------------------------
# KPI progress (single KPI, all users)
# ---------------------------------------------------------------------------


class ActualDataPoint(BaseModel):
    """One data point in a time-series chart."""

    period_date: date
    actual_value: Decimal | None
    target_value: Decimal
    achievement_percentage: Decimal | None


class UserKPIProgress(BaseModel):
    """One row in the KPI progress table."""

    user: UserSummary
    target_value: Decimal
    latest_actual: Decimal | None
    achievement_percentage: Decimal | None
    rating: RatingLabel | None
    data_points: list[ActualDataPoint]


class KPIProgressReport(BaseModel):
    """Full progress report for a single KPI across all assigned users in a cycle."""

    kpi_id: UUID
    kpi_name: str
    kpi_code: str
    cycle_id: UUID
    cycle_name: str
    total_assigned: int
    submitted_actuals: int
    avg_achievement: Decimal | None
    user_progress: list[UserKPIProgress]


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------


class LeaderboardEntry(BaseModel):
    """One row in the leaderboard."""

    rank: int
    user: UserSummary
    composite_score: Decimal
    rating: RatingLabel
    kpis_completed: int
    kpi_count: int
