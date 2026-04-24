"""
DashboardService — efficient aggregation queries for all dashboard views.

Design principle: prefer SQL-level aggregations over Python loops.
All queries return fully-populated schema objects ready for JSON serialisation.
"""

import csv
import io
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.actuals.enums import ActualEntryStatus
from app.actuals.models import KPIActual
from app.dashboards.schemas import (
    ActualDataPoint,
    DepartmentSummary,
    EmployeeDashboard,
    KPIAtRiskSummary,
    KPIProgressReport,
    KPISummaryCard,
    LeaderboardEntry,
    ManagerDashboard,
    OrgDashboard,
    ReviewCycleSummary,
    TeamMemberSummary,
    UserKPIProgress,
    UserSummary,
)
from app.exceptions import ForbiddenException, NotFoundException
from app.kpis.enums import DepartmentCategory
from app.kpis.models import KPI, KPICategory
from app.review_cycles.enums import CycleStatus
from app.review_cycles.models import ReviewCycle
from app.scoring.calculator import compute_achievement_percentage
from app.scoring.enums import RatingLabel, ScoreStatus
from app.scoring.models import CompositeScore, PerformanceScore
from app.targets.enums import TargetStatus
from app.targets.models import KPITarget
from app.users.models import User

# At-risk threshold: below this achievement % at mid-cycle is flagged
_AT_RISK_THRESHOLD = Decimal("60.0")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _user_summary(user: User) -> UserSummary:
    return UserSummary(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        role=user.role.value,
    )


def _cycle_summary(cycle: ReviewCycle) -> ReviewCycleSummary:
    return ReviewCycleSummary(
        id=cycle.id,
        name=cycle.name,
        cycle_type=cycle.cycle_type.value,
        status=cycle.status.value,
        start_date=cycle.start_date,
        end_date=cycle.end_date,
    )


async def _get_active_cycle(db: AsyncSession, org_id: UUID) -> ReviewCycle | None:
    """Return the currently ACTIVE cycle for the org, or None."""
    result = await db.execute(
        select(ReviewCycle).where(
            ReviewCycle.organisation_id == org_id,
            ReviewCycle.status == CycleStatus.ACTIVE,
        )
        .order_by(ReviewCycle.start_date.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _get_latest_actual_per_target(
    db: AsyncSession, target_ids: list[UUID]
) -> dict[UUID, KPIActual]:
    """Return a mapping of target_id → latest approved actual."""
    if not target_ids:
        return {}

    # Subquery: max period_date per target
    subq = (
        select(
            KPIActual.target_id,
            func.max(KPIActual.period_date).label("max_date"),
        )
        .where(
            KPIActual.target_id.in_(target_ids),
            KPIActual.status == ActualEntryStatus.APPROVED,
        )
        .group_by(KPIActual.target_id)
        .subquery()
    )

    result = await db.execute(
        select(KPIActual).join(
            subq,
            (KPIActual.target_id == subq.c.target_id)
            & (KPIActual.period_date == subq.c.max_date),
        )
        .where(KPIActual.status == ActualEntryStatus.APPROVED)
    )
    actuals = result.scalars().all()
    return {a.target_id: a for a in actuals}


def _compute_trend(actuals: list[KPIActual], kpi_direction: str) -> str:
    """
    Determine trend direction from the last 3 approved actuals.

    Returns one of: "improving", "declining", "stable", "no_data".
    """
    if len(actuals) < 2:
        return "no_data"

    recent = sorted(actuals, key=lambda a: a.period_date)[-3:]
    values = [float(a.actual_value) for a in recent]

    if len(values) < 2:
        return "no_data"

    slope = (values[-1] - values[0]) / len(values)
    threshold = 0.01 * abs(values[0]) if values[0] != 0 else 0.01

    if abs(slope) <= threshold:
        return "stable"

    improving = slope > 0 if kpi_direction == "higher_is_better" else slope < 0
    return "improving" if improving else "declining"


def _is_at_risk(
    achievement_pct: Decimal | None,
    cycle: ReviewCycle,
) -> bool:
    """
    A target is at-risk if achievement < 60 % and the cycle is at least 40 % elapsed.

    This prevents false positives early in a cycle when few actuals have been entered.
    """
    if achievement_pct is None:
        return False
    today = date.today()
    total_days = max((cycle.end_date - cycle.start_date).days, 1)
    elapsed_pct = (today - cycle.start_date).days / total_days
    return elapsed_pct >= 0.40 and achievement_pct < _AT_RISK_THRESHOLD


# ---------------------------------------------------------------------------
# DashboardService
# ---------------------------------------------------------------------------


class DashboardService:

    async def get_employee_dashboard(
        self, db: AsyncSession, user_id: UUID, org_id: UUID
    ) -> EmployeeDashboard:
        """
        Build the personal employee dashboard.

        Single query loads all targets → latest actuals → KPIs.
        Computes at-risk flag, trend, and pending-entry counts in Python.
        """
        user_result = await db.execute(
            select(User).where(User.id == user_id, User.organisation_id == org_id)
        )
        user = user_result.scalar_one_or_none()
        if not user:
            raise NotFoundException(f"User '{user_id}' not found in this organisation.")

        cycle = await _get_active_cycle(db, org_id)
        if cycle is None:
            return EmployeeDashboard(
                user=_user_summary(user),
                active_cycle=None,
                kpi_summary=[],
                overall_score=None,
                overall_rating=None,
                score_status=None,
                at_risk_count=0,
                pending_actuals_count=0,
            )

        # Load targets for this user in the active cycle
        targets_result = await db.execute(
            select(KPITarget)
            .where(
                KPITarget.review_cycle_id == cycle.id,
                KPITarget.assignee_user_id == user_id,
                KPITarget.status == TargetStatus.LOCKED,
            )
            .options(selectinload(KPITarget.kpi))
        )
        targets = targets_result.scalars().all()

        if not targets:
            return EmployeeDashboard(
                user=_user_summary(user),
                active_cycle=_cycle_summary(cycle),
                kpi_summary=[],
                overall_score=None,
                overall_rating=None,
                score_status=None,
                at_risk_count=0,
                pending_actuals_count=0,
            )

        target_ids = [t.id for t in targets]
        latest_actuals = await _get_latest_actual_per_target(db, target_ids)

        # Load all approved actuals (for trend computation)
        all_actuals_result = await db.execute(
            select(KPIActual)
            .where(
                KPIActual.target_id.in_(target_ids),
                KPIActual.status == ActualEntryStatus.APPROVED,
            )
            .order_by(KPIActual.period_date)
        )
        all_actuals = all_actuals_result.scalars().all()
        actuals_by_target: dict[UUID, list[KPIActual]] = {}
        for a in all_actuals:
            actuals_by_target.setdefault(a.target_id, []).append(a)

        # Load composite score (if scoring has run)
        composite_result = await db.execute(
            select(CompositeScore).where(
                CompositeScore.user_id == user_id,
                CompositeScore.review_cycle_id == cycle.id,
            )
        )
        composite = composite_result.scalar_one_or_none()

        kpi_cards: list[KPISummaryCard] = []
        at_risk_count = 0
        pending_count = 0

        for target in targets:
            kpi = target.kpi
            latest = latest_actuals.get(target.id)
            target_actuals = actuals_by_target.get(target.id, [])

            achievement_pct: Decimal | None = None
            if latest:
                achievement_pct = compute_achievement_percentage(
                    actual_value=latest.actual_value,
                    target_value=target.target_value,
                    scoring_direction=kpi.scoring_direction,
                    minimum_value=target.minimum_value,
                )
            else:
                pending_count += 1

            trend = _compute_trend(target_actuals, kpi.scoring_direction.value)
            at_risk = _is_at_risk(achievement_pct, cycle)
            if at_risk:
                at_risk_count += 1

            # Determine rating from composite KPI score if available
            kpi_rating: RatingLabel | None = None
            if composite:
                perf_result = await db.execute(
                    select(PerformanceScore).where(
                        PerformanceScore.target_id == target.id,
                        PerformanceScore.review_cycle_id == cycle.id,
                    )
                )
                perf = perf_result.scalar_one_or_none()
                if perf:
                    kpi_rating = perf.rating

            # Next expected period date (simplified: first day of next month)
            from app.utils import get_period_start_dates

            remaining_periods = get_period_start_dates(
                date.today(), cycle.end_date, kpi.frequency
            )
            next_period = remaining_periods[0] if remaining_periods else None

            kpi_cards.append(
                KPISummaryCard(
                    target_id=target.id,
                    kpi_id=kpi.id,
                    kpi_name=kpi.name,
                    kpi_code=kpi.code,
                    kpi_unit=kpi.unit,
                    target_value=target.target_value,
                    latest_actual=latest.actual_value if latest else None,
                    achievement_percentage=achievement_pct,
                    rating=kpi_rating,
                    weight=target.weight,
                    is_at_risk=at_risk,
                    trend=trend,
                    next_period_date=next_period,
                )
            )

        return EmployeeDashboard(
            user=_user_summary(user),
            active_cycle=_cycle_summary(cycle),
            kpi_summary=kpi_cards,
            overall_score=composite.final_weighted_average if composite else None,
            overall_rating=composite.rating if composite else None,
            score_status=composite.status if composite else None,
            at_risk_count=at_risk_count,
            pending_actuals_count=pending_count,
        )

    async def get_manager_dashboard(
        self, db: AsyncSession, manager_id: UUID, org_id: UUID
    ) -> ManagerDashboard:
        """
        Build the manager's team view.

        Loads all direct reports → their targets in the active cycle
        → latest actuals → KPI scores.
        """
        manager_result = await db.execute(
            select(User).where(User.id == manager_id, User.organisation_id == org_id)
        )
        manager = manager_result.scalar_one_or_none()
        if not manager:
            raise NotFoundException(f"Manager '{manager_id}' not found.")

        cycle = await _get_active_cycle(db, org_id)

        # Get direct reports
        reports_result = await db.execute(
            select(User).where(
                User.manager_id == manager_id,
                User.organisation_id == org_id,
                User.is_active.is_(True),
            )
        )
        reports = list(reports_result.scalars().all())

        # Count pending approvals (actuals the manager needs to review)
        pending_approvals = 0
        if reports and cycle:
            report_ids = [r.id for r in reports]
            pending_result = await db.execute(
                select(func.count(KPIActual.id))
                .join(KPITarget, KPIActual.target_id == KPITarget.id)
                .where(
                    KPITarget.review_cycle_id == cycle.id,
                    KPITarget.assignee_user_id.in_(report_ids),
                    KPIActual.status == ActualEntryStatus.PENDING_APPROVAL,
                )
            )
            pending_approvals = pending_result.scalar_one() or 0

        team_overview: list[TeamMemberSummary] = []
        at_risk_count = 0
        total_weighted_scores: list[Decimal] = []

        for report in reports:
            member_summary = await self._build_team_member_summary(
                db, report, cycle, org_id
            )
            team_overview.append(member_summary)
            at_risk_count += member_summary.at_risk_kpis

            if member_summary.overall_achievement is not None:
                total_weighted_scores.append(member_summary.overall_achievement)

        # Team distribution from composite scores
        distribution: dict[str, int] = {r.value: 0 for r in RatingLabel}
        if reports and cycle:
            comp_result = await db.execute(
                select(CompositeScore).where(
                    CompositeScore.review_cycle_id == cycle.id,
                    CompositeScore.organisation_id == org_id,
                    CompositeScore.user_id.in_([r.id for r in reports]),
                )
            )
            for cs in comp_result.scalars().all():
                distribution[cs.rating.value] = distribution.get(cs.rating.value, 0) + 1

        avg_score: Decimal | None = None
        if total_weighted_scores:
            avg_score = Decimal(
                str(sum(float(s) for s in total_weighted_scores) / len(total_weighted_scores))
            ).quantize(Decimal("0.01"))

        return ManagerDashboard(
            manager=_user_summary(manager),
            active_cycle=_cycle_summary(cycle) if cycle else None,
            team_size=len(reports),
            team_overview=team_overview,
            at_risk_count=at_risk_count,
            pending_approvals_count=pending_approvals,
            team_average_score=avg_score,
            team_distribution=distribution,
        )

    async def _build_team_member_summary(
        self,
        db: AsyncSession,
        user: User,
        cycle: ReviewCycle | None,
        org_id: UUID,
    ) -> TeamMemberSummary:
        """Compute the summary row for one team member."""
        score_status: ScoreStatus | None = None
        overall_rating: RatingLabel | None = None
        overall_achievement: Decimal | None = None
        kpi_count = 0
        actuals_submitted = 0
        at_risk_kpis = 0
        pending_actuals = 0

        if cycle:
            targets_result = await db.execute(
                select(KPITarget)
                .where(
                    KPITarget.review_cycle_id == cycle.id,
                    KPITarget.assignee_user_id == user.id,
                    KPITarget.status == TargetStatus.LOCKED,
                )
                .options(selectinload(KPITarget.kpi))
            )
            targets = targets_result.scalars().all()
            kpi_count = len(targets)

            if targets:
                target_ids = [t.id for t in targets]
                latest_actuals = await _get_latest_actual_per_target(db, target_ids)
                actuals_submitted = len(latest_actuals)
                pending_actuals = kpi_count - actuals_submitted

                for target in targets:
                    latest = latest_actuals.get(target.id)
                    if latest:
                        ach = compute_achievement_percentage(
                            actual_value=latest.actual_value,
                            target_value=target.target_value,
                            scoring_direction=target.kpi.scoring_direction,
                            minimum_value=target.minimum_value,
                        )
                        if _is_at_risk(ach, cycle):
                            at_risk_kpis += 1

            # Get composite score
            comp_result = await db.execute(
                select(CompositeScore).where(
                    CompositeScore.user_id == user.id,
                    CompositeScore.review_cycle_id == cycle.id,
                )
            )
            composite = comp_result.scalar_one_or_none()
            if composite:
                overall_achievement = composite.final_weighted_average
                overall_rating = composite.rating
                score_status = composite.status

        return TeamMemberSummary(
            user=_user_summary(user),
            kpi_count=kpi_count,
            actuals_submitted=actuals_submitted,
            overall_achievement=overall_achievement,
            overall_rating=overall_rating,
            at_risk_kpis=at_risk_kpis,
            pending_actuals=pending_actuals,
            score_status=score_status,
        )

    async def get_org_dashboard(
        self,
        db: AsyncSession,
        org_id: UUID,
        cycle_id: UUID | None = None,
    ) -> OrgDashboard:
        """
        Build the executive/HR organisation-wide dashboard.

        Uses SQL aggregations (COUNT, AVG) rather than Python loops where
        possible to support large organisations efficiently.
        """
        if cycle_id:
            cycle_result = await db.execute(
                select(ReviewCycle).where(
                    ReviewCycle.id == cycle_id,
                    ReviewCycle.organisation_id == org_id,
                )
            )
            cycle = cycle_result.scalar_one_or_none()
            if not cycle:
                raise NotFoundException(f"Review cycle '{cycle_id}' not found.")
        else:
            cycle = await _get_active_cycle(db, org_id)

        # Total employees in org
        emp_count_result = await db.execute(
            select(func.count(User.id)).where(
                User.organisation_id == org_id, User.is_active.is_(True)
            )
        )
        total_employees = emp_count_result.scalar_one() or 0

        employees_with_targets = 0
        employees_with_actuals = 0
        avg_achievement: Decimal | None = None
        department_breakdown: list[DepartmentSummary] = []
        top_at_risk: list[KPIAtRiskSummary] = []
        score_distribution: dict = {}
        period_progress = Decimal("0.00")

        if cycle:
            # Period progress
            today = date.today()
            total_days = max((cycle.end_date - cycle.start_date).days, 1)
            elapsed = (today - cycle.start_date).days
            period_progress = Decimal(
                str(min(max(elapsed / total_days * 100, 0), 100))
            ).quantize(Decimal("0.01"))

            # Employees with targets in this cycle
            with_tgt_result = await db.execute(
                select(func.count(distinct(KPITarget.assignee_user_id))).where(
                    KPITarget.review_cycle_id == cycle.id,
                    KPITarget.assignee_user_id.isnot(None),
                )
            )
            employees_with_targets = with_tgt_result.scalar_one() or 0

            # Employees who have submitted at least one actual
            with_actual_result = await db.execute(
                select(func.count(distinct(KPITarget.assignee_user_id)))
                .join(KPIActual, KPIActual.target_id == KPITarget.id)
                .where(
                    KPITarget.review_cycle_id == cycle.id,
                    KPITarget.assignee_user_id.isnot(None),
                    KPIActual.status == ActualEntryStatus.APPROVED,
                )
            )
            employees_with_actuals = with_actual_result.scalar_one() or 0

            # Avg composite score
            avg_result = await db.execute(
                select(func.avg(CompositeScore.final_weighted_average)).where(
                    CompositeScore.review_cycle_id == cycle.id,
                    CompositeScore.organisation_id == org_id,
                )
            )
            avg_val = avg_result.scalar_one()
            if avg_val is not None:
                avg_achievement = Decimal(str(avg_val)).quantize(Decimal("0.01"))

            # Department breakdown: group users by KPI category department
            dept_scores = await self._department_breakdown(db, cycle.id, org_id)
            department_breakdown = dept_scores

            # Top at-risk KPIs
            top_at_risk = await self._top_kpis_at_risk(db, cycle.id, org_id)

            # Score distribution
            all_composites_result = await db.execute(
                select(CompositeScore.final_weighted_average).where(
                    CompositeScore.review_cycle_id == cycle.id,
                    CompositeScore.organisation_id == org_id,
                )
            )
            all_scores = [
                Decimal(str(row[0]))
                for row in all_composites_result.all()
                if row[0] is not None
            ]
            from app.scoring.calculator import compute_score_distribution

            score_distribution = compute_score_distribution(all_scores)

        return OrgDashboard(
            active_cycle=_cycle_summary(cycle) if cycle else None,
            total_employees=total_employees,
            employees_with_targets=employees_with_targets,
            employees_with_actuals=employees_with_actuals,
            avg_achievement=avg_achievement,
            department_breakdown=department_breakdown,
            top_kpis_at_risk=top_at_risk,
            score_distribution=score_distribution,
            period_progress=period_progress,
        )

    async def _department_breakdown(
        self, db: AsyncSession, cycle_id: UUID, org_id: UUID
    ) -> list[DepartmentSummary]:
        """
        Compute per-department summary using KPI category → department mapping.

        An employee can appear in multiple departments if they have KPIs across
        departments.  For simplicity, each (user × department) combination is
        counted once.
        """
        # Load all composite scores for the cycle
        composites_result = await db.execute(
            select(CompositeScore)
            .where(
                CompositeScore.review_cycle_id == cycle_id,
                CompositeScore.organisation_id == org_id,
            )
            .options(selectinload(CompositeScore.user))
        )
        composites = composites_result.scalars().all()

        # Map user_id → composite score for at-risk calc
        score_by_user: dict[UUID, CompositeScore] = {c.user_id: c for c in composites}

        # Load targets → KPI → category → department groupings
        targets_result = await db.execute(
            select(KPITarget)
            .where(
                KPITarget.review_cycle_id == cycle_id,
                KPITarget.assignee_user_id.isnot(None),
            )
            .options(
                selectinload(KPITarget.kpi).selectinload(KPI.category)
            )
        )
        targets = targets_result.scalars().all()

        # Aggregate by department
        dept_data: dict[DepartmentCategory, dict] = {}
        for target in targets:
            kpi = target.kpi
            dept = None
            if kpi.category:
                dept = kpi.category.department
            if dept is None:
                continue

            if dept not in dept_data:
                dept_data[dept] = {
                    "user_ids": set(),
                    "scores": [],
                    "at_risk": 0,
                }

            uid = target.assignee_user_id
            dept_data[dept]["user_ids"].add(uid)
            if uid in score_by_user:
                dept_data[dept]["scores"].append(
                    float(score_by_user[uid].final_weighted_average)
                )
                if score_by_user[uid].rating in (
                    RatingLabel.DOES_NOT_MEET,
                    RatingLabel.PARTIALLY_MEETS,
                ):
                    # Count only once per user per dept
                    if uid not in dept_data[dept].get("at_risk_users", set()):
                        dept_data[dept]["at_risk"] += 1
                        dept_data[dept].setdefault("at_risk_users", set()).add(uid)

        summaries: list[DepartmentSummary] = []
        for dept, data in dept_data.items():
            avg = None
            if data["scores"]:
                avg = Decimal(
                    str(sum(data["scores"]) / len(data["scores"]))
                ).quantize(Decimal("0.01"))

            summaries.append(
                DepartmentSummary(
                    department=dept,
                    employee_count=len(data["user_ids"]),
                    avg_achievement=avg,
                    avg_rating=None,  # Derived from avg score on the frontend
                    at_risk_count=data["at_risk"],
                )
            )

        return sorted(summaries, key=lambda s: s.department.value)

    async def _top_kpis_at_risk(
        self, db: AsyncSession, cycle_id: UUID, org_id: UUID, limit: int = 5
    ) -> list[KPIAtRiskSummary]:
        """
        Find the KPIs with the most employees below the 60% achievement threshold.
        """
        targets_result = await db.execute(
            select(KPITarget)
            .where(
                KPITarget.review_cycle_id == cycle_id,
                KPITarget.assignee_user_id.isnot(None),
                KPITarget.status == TargetStatus.LOCKED,
            )
            .options(selectinload(KPITarget.kpi))
        )
        targets = targets_result.scalars().all()
        target_ids = [t.id for t in targets]

        latest_actuals_map = await _get_latest_actual_per_target(db, target_ids)

        # Count at-risk per KPI
        kpi_at_risk: dict[UUID, dict] = {}
        for target in targets:
            kpi = target.kpi
            latest = latest_actuals_map.get(target.id)
            if latest:
                ach = compute_achievement_percentage(
                    actual_value=latest.actual_value,
                    target_value=target.target_value,
                    scoring_direction=kpi.scoring_direction,
                    minimum_value=target.minimum_value,
                )
            else:
                ach = Decimal("0")

            if ach < _AT_RISK_THRESHOLD:
                if kpi.id not in kpi_at_risk:
                    kpi_at_risk[kpi.id] = {
                        "kpi_name": kpi.name,
                        "affected": 0,
                        "total_ach": Decimal("0"),
                    }
                kpi_at_risk[kpi.id]["affected"] += 1
                kpi_at_risk[kpi.id]["total_ach"] += ach

        top = sorted(kpi_at_risk.items(), key=lambda x: x[1]["affected"], reverse=True)[:limit]
        return [
            KPIAtRiskSummary(
                kpi_id=kpi_id,
                kpi_name=data["kpi_name"],
                affected_users=data["affected"],
                avg_achievement=(
                    data["total_ach"] / data["affected"] if data["affected"] else Decimal("0")
                ).quantize(Decimal("0.01")),
            )
            for kpi_id, data in top
        ]

    async def get_kpi_progress_report(
        self, db: AsyncSession, kpi_id: UUID, cycle_id: UUID, org_id: UUID
    ) -> KPIProgressReport:
        """
        Full progress report for a single KPI across all assigned users.

        Returns target values, latest actuals, time series, and per-user ratings.
        """
        # Verify KPI exists in org
        kpi_result = await db.execute(
            select(KPI).where(KPI.id == kpi_id, KPI.organisation_id == org_id)
        )
        kpi = kpi_result.scalar_one_or_none()
        if not kpi:
            raise NotFoundException(f"KPI '{kpi_id}' not found.")

        cycle_result = await db.execute(
            select(ReviewCycle).where(
                ReviewCycle.id == cycle_id,
                ReviewCycle.organisation_id == org_id,
            )
        )
        cycle = cycle_result.scalar_one_or_none()
        if not cycle:
            raise NotFoundException(f"Review cycle '{cycle_id}' not found.")

        # Load all individual targets for this KPI in this cycle
        targets_result = await db.execute(
            select(KPITarget)
            .where(
                KPITarget.kpi_id == kpi_id,
                KPITarget.review_cycle_id == cycle_id,
                KPITarget.assignee_user_id.isnot(None),
            )
            .options(selectinload(KPITarget.assignee_user))
        )
        targets = targets_result.scalars().all()

        target_ids = [t.id for t in targets]
        latest_actuals = await _get_latest_actual_per_target(db, target_ids)

        # Load all actuals for time-series
        all_actuals_result = await db.execute(
            select(KPIActual)
            .where(
                KPIActual.target_id.in_(target_ids),
                KPIActual.status == ActualEntryStatus.APPROVED,
            )
            .order_by(KPIActual.period_date)
        )
        all_actuals = all_actuals_result.scalars().all()
        actuals_by_target: dict[UUID, list[KPIActual]] = {}
        for a in all_actuals:
            actuals_by_target.setdefault(a.target_id, []).append(a)

        submitted_count = len(latest_actuals)
        total_ach_sum = Decimal("0")
        avg_achievement: Decimal | None = None

        user_progress: list[UserKPIProgress] = []
        for target in targets:
            user = target.assignee_user
            latest = latest_actuals.get(target.id)
            target_actuals = actuals_by_target.get(target.id, [])

            ach: Decimal | None = None
            if latest:
                ach = compute_achievement_percentage(
                    actual_value=latest.actual_value,
                    target_value=target.target_value,
                    scoring_direction=kpi.scoring_direction,
                    minimum_value=target.minimum_value,
                )
                total_ach_sum += ach

            # KPI-level rating from PerformanceScore if available
            kpi_rating: RatingLabel | None = None
            perf_result = await db.execute(
                select(PerformanceScore).where(
                    PerformanceScore.target_id == target.id,
                    PerformanceScore.review_cycle_id == cycle_id,
                )
            )
            perf = perf_result.scalar_one_or_none()
            if perf:
                kpi_rating = perf.rating

            # Build time series data points
            data_points = [
                ActualDataPoint(
                    period_date=a.period_date,
                    actual_value=a.actual_value,
                    target_value=target.target_value,
                    achievement_percentage=compute_achievement_percentage(
                        actual_value=a.actual_value,
                        target_value=target.target_value,
                        scoring_direction=kpi.scoring_direction,
                        minimum_value=target.minimum_value,
                    ),
                )
                for a in target_actuals
            ]

            user_progress.append(
                UserKPIProgress(
                    user=_user_summary(user),
                    target_value=target.target_value,
                    latest_actual=latest.actual_value if latest else None,
                    achievement_percentage=ach,
                    rating=kpi_rating,
                    data_points=data_points,
                )
            )

        if submitted_count > 0:
            avg_achievement = (total_ach_sum / submitted_count).quantize(Decimal("0.01"))

        return KPIProgressReport(
            kpi_id=kpi.id,
            kpi_name=kpi.name,
            kpi_code=kpi.code,
            cycle_id=cycle.id,
            cycle_name=cycle.name,
            total_assigned=len(targets),
            submitted_actuals=submitted_count,
            avg_achievement=avg_achievement,
            user_progress=user_progress,
        )

    async def get_leaderboard(
        self,
        db: AsyncSession,
        cycle_id: UUID,
        org_id: UUID,
        department: str | None = None,
        manager_id: UUID | None = None,
        limit: int = 10,
    ) -> list[LeaderboardEntry]:
        """
        Top performers by composite score.

        - hr_admin / executive: full org leaderboard.
        - manager: limited to their direct reports (passed as manager_id).
        - Only shows employees with at least one actual submitted.
        """
        query = (
            select(CompositeScore)
            .where(
                CompositeScore.review_cycle_id == cycle_id,
                CompositeScore.organisation_id == org_id,
                CompositeScore.kpis_with_actuals > 0,
            )
            .order_by(CompositeScore.final_weighted_average.desc())
            .options(selectinload(CompositeScore.user))
        )

        if manager_id:
            # Subquery: direct reports of manager
            reports_subq = (
                select(User.id)
                .where(User.manager_id == manager_id, User.organisation_id == org_id)
                .scalar_subquery()
            )
            query = query.where(CompositeScore.user_id.in_(reports_subq))

        query = query.limit(limit)
        result = await db.execute(query)
        composites = result.scalars().all()

        entries: list[LeaderboardEntry] = []
        for rank, composite in enumerate(composites, start=1):
            entries.append(
                LeaderboardEntry(
                    rank=rank,
                    user=_user_summary(composite.user),
                    composite_score=composite.final_weighted_average,
                    rating=composite.rating,
                    kpis_completed=composite.kpis_with_actuals,
                    kpi_count=composite.kpi_count,
                )
            )

        return entries

    async def export_scores_csv(
        self, db: AsyncSession, cycle_id: UUID, org_id: UUID
    ) -> str:
        """
        Build a CSV string of all performance scores for the given cycle.

        Columns:
            employee_name, email, manager_name, kpi_code, kpi_name,
            target_value, final_actual, achievement_pct, weighted_score,
            composite_score, rating, score_status
        """
        # Load all performance scores for the cycle
        scores_result = await db.execute(
            select(PerformanceScore)
            .where(
                PerformanceScore.review_cycle_id == cycle_id,
            )
            .join(
                CompositeScore,
                (CompositeScore.user_id == PerformanceScore.user_id)
                & (CompositeScore.review_cycle_id == PerformanceScore.review_cycle_id),
                isouter=True,
            )
            .options(
                selectinload(PerformanceScore.user).selectinload(User.manager),
                selectinload(PerformanceScore.kpi),
                selectinload(PerformanceScore.target),
            )
            .order_by(PerformanceScore.user_id)
        )
        perf_scores = scores_result.scalars().all()

        # Map user → composite
        composite_result = await db.execute(
            select(CompositeScore).where(
                CompositeScore.review_cycle_id == cycle_id,
                CompositeScore.organisation_id == org_id,
            )
        )
        composites_map = {c.user_id: c for c in composite_result.scalars().all()}

        # Build latest actuals map
        target_ids = [ps.target_id for ps in perf_scores]
        latest_actuals = await _get_latest_actual_per_target(db, target_ids)

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "employee_name",
                "email",
                "manager_name",
                "kpi_code",
                "kpi_name",
                "target_value",
                "final_actual",
                "achievement_pct",
                "weighted_score",
                "composite_score",
                "rating",
                "score_status",
            ]
        )

        for ps in perf_scores:
            user = ps.user
            if user.organisation_id != org_id:
                continue  # Security: only export own org
            kpi = ps.kpi
            target = ps.target
            composite = composites_map.get(ps.user_id)
            latest = latest_actuals.get(ps.target_id)

            manager_name = user.manager.full_name if user.manager else ""
            final_actual = str(latest.actual_value) if latest else ""
            composite_score = (
                str(composite.final_weighted_average) if composite else ""
            )
            composite_rating = composite.rating.value if composite else ""

            writer.writerow(
                [
                    user.full_name,
                    user.email,
                    manager_name,
                    kpi.code if kpi else "",
                    kpi.name if kpi else "",
                    str(target.target_value) if target else "",
                    final_actual,
                    str(ps.achievement_percentage),
                    str(ps.weighted_score),
                    composite_score,
                    composite_rating,
                    ps.status.value,
                ]
            )

        return output.getvalue()
