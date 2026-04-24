"""
ActualService — all business logic for actuals (data entry) module.

Actuals are the real values entered against KPI targets over time.
They form the raw input for scoring (Part 4) and reporting.
"""

from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.actuals.enums import ActualEntrySource, ActualEntryStatus
from app.actuals.models import ActualEvidence, KPIActual
from app.actuals.schemas import (
    ActualTimeSeries,
    ActualTimeSeriesPoint,
    KPIActualBulkCreate,
    KPIActualCreate,
    KPIActualReview,
    KPIActualUpdate,
)
from app.exceptions import (
    BadRequestException,
    ForbiddenException,
    NotFoundException,
)
from app.kpis.enums import MeasurementUnit, ScoringDirection
from app.review_cycles.enums import CycleStatus
from app.review_cycles.models import ReviewCycle
from app.targets.enums import TargetStatus
from app.targets.models import KPITarget
from app.users.models import User, UserRole
from app.utils import generate_period_label, get_period_start_dates


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _actual_load_options():
    return [
        selectinload(KPIActual.evidence_attachments),
    ]


async def _get_actual_or_404(
    db: AsyncSession, actual_id: UUID, org_id: UUID
) -> KPIActual:
    result = await db.execute(
        select(KPIActual)
        .join(KPITarget, KPIActual.target_id == KPITarget.id)
        .join(ReviewCycle, KPITarget.review_cycle_id == ReviewCycle.id)
        .where(
            KPIActual.id == actual_id,
            ReviewCycle.organisation_id == org_id,
        )
        .options(*_actual_load_options())
    )
    actual = result.scalar_one_or_none()
    if not actual:
        raise NotFoundException(f"Actual '{actual_id}' not found")
    return actual


async def _get_target_with_cycle(
    db: AsyncSession, target_id: UUID, org_id: UUID
) -> tuple[KPITarget, ReviewCycle]:
    """Return (target, cycle) after verifying the target belongs to the org."""
    result = await db.execute(
        select(KPITarget, ReviewCycle)
        .join(ReviewCycle, KPITarget.review_cycle_id == ReviewCycle.id)
        .where(
            KPITarget.id == target_id,
            ReviewCycle.organisation_id == org_id,
        )
        .options(selectinload(KPITarget.kpi))
    )
    row = result.first()
    if not row:
        raise NotFoundException(f"Target '{target_id}' not found")
    return row[0], row[1]


def _assert_can_submit_actual(
    current_user: User, target: KPITarget
) -> None:
    """
    Verify the caller may submit an actual for this target.

    Rules:
    - hr_admin / executive: always allowed
    - manager: allowed (manages team's data)
    - employee: only for their own individual target
    """
    if current_user.role in {UserRole.hr_admin, UserRole.executive, UserRole.manager}:
        return
    if (
        target.assignee_user_id is not None
        and target.assignee_user_id == current_user.id
    ):
        return
    raise ForbiddenException(
        "You do not have permission to submit actuals for this target."
    )


def _compute_achievement(
    actual_value: Decimal,
    target_value: Decimal,
    scoring_direction: ScoringDirection,
) -> Decimal | None:
    if target_value == 0:
        return None
    if scoring_direction == ScoringDirection.LOWER_IS_BETTER:
        if actual_value == 0:
            return Decimal("100")
        pct = (target_value / actual_value) * 100
    else:
        pct = (actual_value / target_value) * 100
    return pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _validate_period_date(
    period_date: date, kpi_frequency, cycle: ReviewCycle
) -> None:
    """
    Verify period_date:
    1. Falls within cycle.start_date – cycle.end_date inclusive.
    2. Aligns to the expected period boundaries for the KPI frequency.
    """
    if not (cycle.start_date <= period_date <= cycle.end_date):
        raise BadRequestException(
            f"period_date {period_date} is outside the review cycle range "
            f"({cycle.start_date} – {cycle.end_date})."
        )

    expected_periods = get_period_start_dates(
        cycle.start_date, cycle.end_date, kpi_frequency
    )
    if period_date not in expected_periods:
        raise BadRequestException(
            f"period_date {period_date} does not align to the expected "
            f"{kpi_frequency.value} measurement periods for this cycle. "
            f"Expected dates: {[d.isoformat() for d in expected_periods[:5]]}"
            + ("..." if len(expected_periods) > 5 else "")
        )


# ---------------------------------------------------------------------------
# ActualService
# ---------------------------------------------------------------------------


class ActualService:

    async def submit_actual(
        self,
        db: AsyncSession,
        org_id: UUID,
        current_user: User,
        data: KPIActualCreate,
    ) -> KPIActual:
        """
        Submit a KPI actual value for a measurement period.

        Business rules:
        1. Target must exist and belong to the organisation.
        2. Target must be LOCKED (cycle is ACTIVE — performance period running).
        3. Caller must have permission for this target.
        4. period_date must fall within the cycle and align to KPI frequency.
        5. If an APPROVED actual already exists for this period, mark it SUPERSEDED
           and create a new record (full audit trail preserved).
        6. If a PENDING_APPROVAL actual exists, update it in-place.
        7. Auto-approve MANUAL actuals for INDIVIDUAL targets;
           TEAM/ORG targets go to PENDING_APPROVAL for manager review.
        """
        target, cycle = await _get_target_with_cycle(db, data.target_id, org_id)

        if target.status != TargetStatus.LOCKED:
            raise BadRequestException(
                f"Target status is '{target.status.value}'. "
                "Actuals can only be submitted for LOCKED targets "
                "(the review cycle must be ACTIVE)."
            )

        _assert_can_submit_actual(current_user, target)
        _validate_period_date(data.period_date, target.kpi.frequency, cycle)

        period_label = generate_period_label(data.period_date, target.kpi.frequency)

        # Check for existing active (non-superseded) actual for this period
        existing_result = await db.execute(
            select(KPIActual).where(
                KPIActual.target_id == data.target_id,
                KPIActual.period_date == data.period_date,
                KPIActual.status != ActualEntryStatus.SUPERSEDED,
            )
        )
        existing = existing_result.scalar_one_or_none()

        if existing:
            if existing.status == ActualEntryStatus.PENDING_APPROVAL:
                # Update in place — no need for a new record
                existing.actual_value = data.actual_value
                existing.notes = data.notes
                existing.submitted_by_id = current_user.id
                existing.updated_at = datetime.now(timezone.utc)
                await db.flush()
                return await _get_actual_or_404(db, existing.id, org_id)

            elif existing.status == ActualEntryStatus.APPROVED:
                # Supersede old record, create new
                existing.status = ActualEntryStatus.SUPERSEDED
                existing.updated_at = datetime.now(timezone.utc)

            elif existing.status == ActualEntryStatus.REJECTED:
                # Allow resubmission — supersede the rejected one
                existing.status = ActualEntryStatus.SUPERSEDED
                existing.updated_at = datetime.now(timezone.utc)

        # Determine approval status:
        # Individual targets → APPROVED immediately
        # Team/Org targets → PENDING_APPROVAL (needs manager sign-off)
        from app.targets.enums import TargetLevel

        initial_status = (
            ActualEntryStatus.APPROVED
            if target.assignee_type == TargetLevel.INDIVIDUAL
            else ActualEntryStatus.PENDING_APPROVAL
        )

        actual = KPIActual(
            target_id=data.target_id,
            kpi_id=target.kpi_id,
            period_date=data.period_date,
            period_label=period_label,
            actual_value=data.actual_value,
            entry_source=ActualEntrySource.MANUAL,
            status=initial_status,
            notes=data.notes,
            submitted_by_id=current_user.id,
        )
        db.add(actual)
        await db.flush()
        return await _get_actual_or_404(db, actual.id, org_id)

    async def submit_bulk_actuals(
        self,
        db: AsyncSession,
        org_id: UUID,
        current_user: User,
        data: KPIActualBulkCreate,
    ) -> list[KPIActual]:
        """Submit multiple period actuals in a single transaction."""
        results = []
        for entry in data.entries:
            actual = await self.submit_actual(db, org_id, current_user, entry)
            results.append(actual)
        return results

    async def review_actual(
        self,
        db: AsyncSession,
        actual_id: UUID,
        org_id: UUID,
        reviewer: User,
        data: KPIActualReview,
    ) -> KPIActual:
        """
        Manager approves or rejects a PENDING_APPROVAL actual.

        Only hr_admin, executive, or manager roles may review.
        On rejection: requires a reason; triggers notification (stub).
        """
        if reviewer.role not in {
            UserRole.hr_admin,
            UserRole.executive,
            UserRole.manager,
        }:
            raise ForbiddenException("Only managers or hr_admin can review actuals.")

        actual = await _get_actual_or_404(db, actual_id, org_id)

        if actual.status != ActualEntryStatus.PENDING_APPROVAL:
            raise BadRequestException(
                f"Actual is in '{actual.status.value}' status. "
                "Only PENDING_APPROVAL actuals can be reviewed."
            )

        now = datetime.now(timezone.utc)
        if data.action == "approve":
            actual.status = ActualEntryStatus.APPROVED
            actual.reviewed_by_id = reviewer.id
            actual.reviewed_at = now
            actual.rejection_reason = None
        else:  # reject
            actual.status = ActualEntryStatus.REJECTED
            actual.reviewed_by_id = reviewer.id
            actual.reviewed_at = now
            actual.rejection_reason = data.rejection_reason
            # Stub: notify submitter of rejection

        actual.updated_at = now
        await db.flush()
        return await _get_actual_or_404(db, actual.id, org_id)

    async def get_actual_by_id(
        self, db: AsyncSession, actual_id: UUID, org_id: UUID
    ) -> KPIActual:
        return await _get_actual_or_404(db, actual_id, org_id)

    async def update_actual(
        self,
        db: AsyncSession,
        actual_id: UUID,
        org_id: UUID,
        current_user: User,
        data: KPIActualUpdate,
    ) -> KPIActual:
        """
        Edit an own actual that is still PENDING_APPROVAL.

        Only the original submitter may edit, and only before it is reviewed.
        """
        actual = await _get_actual_or_404(db, actual_id, org_id)

        if actual.submitted_by_id != current_user.id:
            if current_user.role not in {UserRole.hr_admin, UserRole.executive}:
                raise ForbiddenException("You can only edit actuals you have submitted.")

        if actual.status != ActualEntryStatus.PENDING_APPROVAL:
            raise BadRequestException(
                f"Cannot edit an actual in '{actual.status.value}' status. "
                "Only PENDING_APPROVAL actuals can be modified."
            )

        if data.actual_value is not None:
            actual.actual_value = data.actual_value
        if data.notes is not None:
            actual.notes = data.notes
        actual.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return await _get_actual_or_404(db, actual.id, org_id)

    async def list_actuals_for_target(
        self,
        db: AsyncSession,
        target_id: UUID,
        org_id: UUID,
        include_superseded: bool = False,
        page: int = 1,
        size: int = 50,
    ) -> list[KPIActual]:
        """Return actuals for a target, optionally including superseded entries."""
        # Verify target belongs to org
        target_result = await db.execute(
            select(KPITarget)
            .join(ReviewCycle, KPITarget.review_cycle_id == ReviewCycle.id)
            .where(
                KPITarget.id == target_id,
                ReviewCycle.organisation_id == org_id,
            )
        )
        if not target_result.scalar_one_or_none():
            raise NotFoundException(f"Target '{target_id}' not found")

        query = select(KPIActual).where(KPIActual.target_id == target_id)
        if not include_superseded:
            query = query.where(
                KPIActual.status != ActualEntryStatus.SUPERSEDED
            )
        query = (
            query.options(*_actual_load_options())
            .order_by(KPIActual.period_date.asc())
            .offset((page - 1) * size)
            .limit(size)
        )
        result = await db.execute(query)
        return list(result.scalars().all())

    async def list_actuals(
        self,
        db: AsyncSession,
        org_id: UUID,
        target_id: UUID | None = None,
        kpi_id: UUID | None = None,
        status: ActualEntryStatus | None = None,
        period_start: date | None = None,
        period_end: date | None = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        from sqlalchemy import func

        query = (
            select(KPIActual)
            .join(KPITarget, KPIActual.target_id == KPITarget.id)
            .join(ReviewCycle, KPITarget.review_cycle_id == ReviewCycle.id)
            .where(ReviewCycle.organisation_id == org_id)
        )
        if target_id:
            query = query.where(KPIActual.target_id == target_id)
        if kpi_id:
            query = query.where(KPIActual.kpi_id == kpi_id)
        if status:
            query = query.where(KPIActual.status == status)
        if period_start:
            query = query.where(KPIActual.period_date >= period_start)
        if period_end:
            query = query.where(KPIActual.period_date <= period_end)

        count_result = await db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = count_result.scalar_one()

        import math

        offset = (page - 1) * size
        query = (
            query.options(*_actual_load_options())
            .order_by(KPIActual.period_date.desc(), KPIActual.created_at.desc())
            .offset(offset)
            .limit(size)
        )
        result = await db.execute(query)
        items = list(result.scalars().all())
        pages = math.ceil(total / size) if size else 1
        return {"items": items, "total": total, "page": page, "size": size, "pages": pages}

    async def get_pending_approvals_for_manager(
        self,
        db: AsyncSession,
        manager: User,
        org_id: UUID,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """
        Return PENDING_APPROVAL actuals from the manager's direct reports.

        hr_admin and executives see all pending actuals in the org.
        """
        from sqlalchemy import func

        query = (
            select(KPIActual)
            .join(KPITarget, KPIActual.target_id == KPITarget.id)
            .join(ReviewCycle, KPITarget.review_cycle_id == ReviewCycle.id)
            .where(
                ReviewCycle.organisation_id == org_id,
                KPIActual.status == ActualEntryStatus.PENDING_APPROVAL,
            )
        )

        # Scope to direct reports unless hr_admin / executive
        if manager.role not in {UserRole.hr_admin, UserRole.executive}:
            from app.users.models import User as UserModel

            direct_report_ids_result = await db.execute(
                select(UserModel.id).where(UserModel.manager_id == manager.id)
            )
            direct_report_ids = [row[0] for row in direct_report_ids_result]
            if not direct_report_ids:
                return {"items": [], "total": 0, "page": page, "size": size, "pages": 0}
            query = query.where(KPIActual.submitted_by_id.in_(direct_report_ids))

        count_result = await db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = count_result.scalar_one()

        import math

        offset = (page - 1) * size
        query = (
            query.options(*_actual_load_options())
            .order_by(KPIActual.created_at.asc())
            .offset(offset)
            .limit(size)
        )
        result = await db.execute(query)
        items = list(result.scalars().all())
        pages = math.ceil(total / size) if size else 1
        return {"items": items, "total": total, "page": page, "size": size, "pages": pages}

    async def get_time_series(
        self, db: AsyncSession, target_id: UUID, org_id: UUID
    ) -> ActualTimeSeries:
        """
        Build a complete time series for a target from cycle start to today.

        Missing periods are included with actual_value=None.
        Achievement percentage is computed per period using the single-period
        target value (i.e. total_target / total_periods for count-type KPIs,
        or target_value directly for rate/percentage KPIs).
        """
        target, cycle = await _get_target_with_cycle(db, target_id, org_id)

        # Fetch all approved / pending actuals for this target
        result = await db.execute(
            select(KPIActual)
            .where(
                KPIActual.target_id == target_id,
                KPIActual.status.in_(
                    [ActualEntryStatus.APPROVED, ActualEntryStatus.PENDING_APPROVAL]
                ),
            )
            .order_by(KPIActual.period_date)
        )
        actuals = list(result.scalars().all())
        actuals_by_period: dict[date, KPIActual] = {
            a.period_date: a for a in actuals
        }

        # Generate expected periods up to today
        today = date.today()
        effective_end = min(cycle.end_date, today)
        expected_periods = get_period_start_dates(
            cycle.start_date, effective_end, target.kpi.frequency
        )
        if not expected_periods:
            expected_periods = [cycle.start_date]

        # Per-period target value
        n_periods = max(len(expected_periods), 1)
        sum_units = {
            MeasurementUnit.COUNT,
            MeasurementUnit.CURRENCY,
            MeasurementUnit.DURATION_HOURS,
        }
        if target.kpi.unit in sum_units:
            period_target = (target.target_value / n_periods).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )
        else:
            period_target = target.target_value

        # Milestone lookup
        from app.targets.models import TargetMilestone as TM

        ms_result = await db.execute(
            select(TM)
            .where(TM.target_id == target_id)
            .order_by(TM.milestone_date)
        )
        milestones = list(ms_result.scalars().all())
        ms_by_date: dict[date, TM] = {m.milestone_date: m for m in milestones}

        data_points: list[ActualTimeSeriesPoint] = []
        total_actual = Decimal("0")

        for pd in expected_periods:
            actual = actuals_by_period.get(pd)
            actual_val = actual.actual_value if actual else None

            achievement = None
            if actual_val is not None:
                achievement = _compute_achievement(
                    actual_val, period_target, target.kpi.scoring_direction
                )
                total_actual += actual_val

            # Find milestone for this period (exact match or nearest preceding)
            ms = ms_by_date.get(pd)
            if not ms:
                preceding = [m for m in milestones if m.milestone_date <= pd]
                ms = preceding[-1] if preceding else None

            data_points.append(
                ActualTimeSeriesPoint(
                    period_date=pd,
                    period_label=generate_period_label(pd, target.kpi.frequency),
                    actual_value=actual_val,
                    target_value=period_target,
                    milestone_value=ms.expected_value if ms else None,
                    achievement_percentage=achievement,
                )
            )

        # Overall achievement
        periods_with_data = sum(1 for p in data_points if p.actual_value is not None)
        overall_achievement = _compute_achievement(
            total_actual, target.target_value, target.kpi.scoring_direction
        ) or Decimal("0")

        return ActualTimeSeries(
            target_id=target_id,
            kpi_id=target.kpi_id,
            kpi_name=target.kpi.name,
            kpi_unit=target.kpi.unit,
            data_points=data_points,
            overall_achievement=overall_achievement,
            periods_with_data=periods_with_data,
            total_periods=len(expected_periods),
        )

    async def add_evidence(
        self,
        db: AsyncSession,
        actual_id: UUID,
        org_id: UUID,
        current_user: User,
        file_name: str,
        file_url: str,
        file_type: str,
    ) -> ActualEvidence:
        """Attach evidence to an actual submission."""
        actual = await _get_actual_or_404(db, actual_id, org_id)

        if actual.status in {
            ActualEntryStatus.SUPERSEDED,
            ActualEntryStatus.REJECTED,
        }:
            raise BadRequestException(
                f"Cannot attach evidence to a {actual.status.value} actual."
            )

        evidence = ActualEvidence(
            actual_id=actual_id,
            file_name=file_name,
            file_url=file_url,
            file_type=file_type,
            uploaded_by_id=current_user.id,
        )
        db.add(evidence)
        await db.flush()
        await db.refresh(evidence)
        return evidence

    async def delete_evidence(
        self,
        db: AsyncSession,
        evidence_id: UUID,
        org_id: UUID,
        current_user: User,
    ) -> None:
        """Delete an evidence attachment."""
        result = await db.execute(
            select(ActualEvidence)
            .join(KPIActual, ActualEvidence.actual_id == KPIActual.id)
            .join(KPITarget, KPIActual.target_id == KPITarget.id)
            .join(ReviewCycle, KPITarget.review_cycle_id == ReviewCycle.id)
            .where(
                ActualEvidence.id == evidence_id,
                ReviewCycle.organisation_id == org_id,
            )
        )
        evidence = result.scalar_one_or_none()
        if not evidence:
            raise NotFoundException(f"Evidence '{evidence_id}' not found")

        if (
            evidence.uploaded_by_id != current_user.id
            and current_user.role not in {UserRole.hr_admin, UserRole.executive}
        ):
            raise ForbiddenException(
                "You can only delete evidence you have uploaded."
            )

        await db.delete(evidence)
        await db.flush()

    async def compute_formula_actuals(
        self,
        db: AsyncSession,
        cycle_id: UUID,
        org_id: UUID,
        period_date: date,
    ) -> list[KPIActual]:
        """
        Auto-compute and insert formula-based KPI actuals for a given period.

        Called as a scheduled job or manually by hr_admin.
        Resolves dependency KPI actual values, evaluates the formula,
        and inserts an AUTO_FORMULA actual (or supersedes the previous one).
        """
        from app.kpis.enums import DataSourceType
        from app.kpis.formula import FormulaEvaluator
        from app.kpis.models import KPI

        # Find all FORMULA KPIs with active locked targets in this cycle
        formula_targets_result = await db.execute(
            select(KPITarget)
            .join(KPI, KPITarget.kpi_id == KPI.id)
            .join(ReviewCycle, KPITarget.review_cycle_id == ReviewCycle.id)
            .where(
                KPITarget.review_cycle_id == cycle_id,
                KPITarget.status == TargetStatus.LOCKED,
                KPI.data_source == DataSourceType.FORMULA,
                ReviewCycle.organisation_id == org_id,
            )
            .options(selectinload(KPITarget.kpi))
        )
        formula_targets = list(formula_targets_result.scalars().all())

        evaluator = FormulaEvaluator()
        created: list[KPIActual] = []

        for target in formula_targets:
            kpi = target.kpi
            if not kpi.formula_expression:
                continue

            # Resolve dependency values for this period
            dep_values: dict[str, float] = {}
            missing = False
            for dep_kpi in kpi.formula_dependencies:
                # Find the most recent approved actual for the dep KPI at this period
                dep_result = await db.execute(
                    select(KPIActual)
                    .join(KPITarget, KPIActual.target_id == KPITarget.id)
                    .where(
                        KPIActual.kpi_id == dep_kpi.id,
                        KPIActual.period_date == period_date,
                        KPIActual.status == ActualEntryStatus.APPROVED,
                        KPITarget.review_cycle_id == cycle_id,
                    )
                    .order_by(KPIActual.created_at.desc())
                )
                dep_actual = dep_result.scalars().first()
                if dep_actual is None:
                    missing = True
                    break
                dep_values[dep_kpi.code] = float(dep_actual.actual_value)

            if missing:
                # Skip this target — dependencies not yet available
                continue

            try:
                formula_result = evaluator.evaluate(
                    kpi.formula_expression, dep_values
                )
            except Exception:
                # Skip quietly; log in production
                continue

            # Supersede any existing formula actual for this period
            existing_result = await db.execute(
                select(KPIActual).where(
                    KPIActual.target_id == target.id,
                    KPIActual.period_date == period_date,
                    KPIActual.status != ActualEntryStatus.SUPERSEDED,
                    KPIActual.entry_source == ActualEntrySource.AUTO_FORMULA,
                )
            )
            existing = existing_result.scalar_one_or_none()
            if existing:
                existing.status = ActualEntryStatus.SUPERSEDED
                existing.updated_at = datetime.now(timezone.utc)

            actual = KPIActual(
                target_id=target.id,
                kpi_id=kpi.id,
                period_date=period_date,
                period_label=generate_period_label(period_date, kpi.frequency),
                actual_value=Decimal(str(formula_result)).quantize(
                    Decimal("0.0001"), rounding=ROUND_HALF_UP
                ),
                entry_source=ActualEntrySource.AUTO_FORMULA,
                status=ActualEntryStatus.APPROVED,
                submitted_by_id=None,  # AUTO_FORMULA: no human submitter
            )
            db.add(actual)
            await db.flush()
            created.append(actual)

        return created
