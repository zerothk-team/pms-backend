"""
TargetService — all business logic for the target-setting module.

Targets define what an employee / team / organisation must achieve for a
KPI within a specific review cycle.  They drive the actuals entry and the
eventual scoring calculation in Part 4.
"""

from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.kpis.enums import KPIStatus, ScoringDirection
from app.kpis.models import KPI
from app.review_cycles.enums import CycleStatus
from app.review_cycles.models import ReviewCycle
from app.targets.enums import TargetLevel, TargetStatus
from app.targets.models import KPITarget, TargetMilestone
from app.targets.schemas import (
    CascadeTargetRequest,
    KPITargetBulkCreate,
    KPITargetCreate,
    KPITargetProgressRead,
    KPITargetRead,
    KPITargetUpdate,
    WeightsCheckResponse,
)
from app.users.models import User, UserRole


# ---------------------------------------------------------------------------
# Eager-load options
# ---------------------------------------------------------------------------


def _target_load_options():
    from app.kpis.service import _kpi_load_options

    return [
        selectinload(KPITarget.kpi).options(*_kpi_load_options()),
        selectinload(KPITarget.milestones),
        selectinload(KPITarget.cascade_children),
    ]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_target_or_404(
    db: AsyncSession, target_id: UUID, org_id: UUID
) -> KPITarget:
    """Fetch a target with full relationships, scoped to the org via the cycle."""
    result = await db.execute(
        select(KPITarget)
        .join(ReviewCycle, KPITarget.review_cycle_id == ReviewCycle.id)
        .where(
            KPITarget.id == target_id,
            ReviewCycle.organisation_id == org_id,
        )
        .options(*_target_load_options())
    )
    target = result.scalar_one_or_none()
    if not target:
        raise NotFoundException(f"Target '{target_id}' not found")
    return target


async def _get_kpi_active_or_404(db: AsyncSession, kpi_id: UUID, org_id: UUID) -> KPI:
    """Return an ACTIVE KPI for the org, or raise."""
    result = await db.execute(
        select(KPI).where(KPI.id == kpi_id, KPI.organisation_id == org_id)
    )
    kpi = result.scalar_one_or_none()
    if not kpi:
        raise NotFoundException(f"KPI '{kpi_id}' not found")
    if kpi.status != KPIStatus.ACTIVE:
        raise BadRequestException(
            f"KPI '{kpi.code}' is in '{kpi.status.value}' status. "
            "Only ACTIVE KPIs can be assigned targets."
        )
    return kpi


async def _get_cycle_open_or_404(
    db: AsyncSession, cycle_id: UUID, org_id: UUID
) -> ReviewCycle:
    """Return a non-closed/archived cycle for the org, or raise."""
    result = await db.execute(
        select(ReviewCycle).where(
            ReviewCycle.id == cycle_id,
            ReviewCycle.organisation_id == org_id,
        )
    )
    cycle = result.scalar_one_or_none()
    if not cycle:
        raise NotFoundException(f"Review cycle '{cycle_id}' not found")
    if cycle.status in {CycleStatus.CLOSED, CycleStatus.ARCHIVED}:
        raise BadRequestException(
            f"Review cycle '{cycle.name}' is {cycle.status.value}. "
            "Targets cannot be added to closed or archived cycles."
        )
    return cycle


async def _check_duplicate_target(
    db: AsyncSession,
    kpi_id: UUID,
    review_cycle_id: UUID,
    assignee_user_id: UUID | None,
    assignee_type: TargetLevel,
    assignee_org_id: UUID | None,
    exclude_id: UUID | None = None,
) -> None:
    """Raise ConflictException if a duplicate target already exists."""
    if assignee_user_id:
        # Individual target: one per (kpi, cycle, user)
        stmt = select(KPITarget).where(
            KPITarget.kpi_id == kpi_id,
            KPITarget.review_cycle_id == review_cycle_id,
            KPITarget.assignee_user_id == assignee_user_id,
        )
    else:
        # Org / dept / team target: one per (kpi, cycle, assignee_type, org)
        stmt = select(KPITarget).where(
            KPITarget.kpi_id == kpi_id,
            KPITarget.review_cycle_id == review_cycle_id,
            KPITarget.assignee_type == assignee_type,
            KPITarget.assignee_org_id == assignee_org_id,
            KPITarget.assignee_user_id.is_(None),
        )

    if exclude_id:
        stmt = stmt.where(KPITarget.id != exclude_id)

    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing:
        raise ConflictException(
            "A target already exists for this KPI / cycle / assignee combination."
        )


def _assert_can_set_target(current_user: User, assignee_user_id: UUID | None) -> None:
    """
    Verify the current user has permission to set a target for the given assignee.

    Rules:
    - hr_admin: can set targets for anyone
    - manager: can set targets (the service resolves team scope at query time)
    - employee: cannot create targets (employees acknowledge, not set)
    - executive: treated like hr_admin for target setting
    """
    if current_user.role in {UserRole.hr_admin, UserRole.executive, UserRole.manager}:
        return
    raise ForbiddenException("Only hr_admin, executive, or manager can set targets.")


def _compute_achievement(
    actual: Decimal,
    target: Decimal,
    scoring_direction: ScoringDirection,
) -> Decimal:
    """
    Compute achievement percentage adjusted for scoring direction.

    HIGHER_IS_BETTER: (actual / target) * 100
    LOWER_IS_BETTER:  (target / actual) * 100  — achieving *less* is better
    """
    if target == 0:
        return Decimal("0")
    if scoring_direction == ScoringDirection.LOWER_IS_BETTER:
        if actual == 0:
            return Decimal("100")  # Perfect
        pct = (target / actual) * 100
    else:
        pct = (actual / target) * 100
    return pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# TargetService
# ---------------------------------------------------------------------------


class TargetService:

    async def create_target(
        self,
        db: AsyncSession,
        org_id: UUID,
        current_user: User,
        data: KPITargetCreate,
    ) -> KPITarget:
        """
        Create a single KPI target.

        Business rules:
        1. KPI must be ACTIVE within the organisation.
        2. Review cycle must exist and not be CLOSED/ARCHIVED.
        3. Caller must be hr_admin, executive, or manager.
        4. No duplicate target for the same KPI/cycle/assignee.
        5. If the cycle is already ACTIVE (period live), lock the target immediately.
        """
        _assert_can_set_target(current_user, data.assignee_user_id)
        kpi = await _get_kpi_active_or_404(db, data.kpi_id, org_id)
        cycle = await _get_cycle_open_or_404(db, data.review_cycle_id, org_id)

        await _check_duplicate_target(
            db,
            data.kpi_id,
            data.review_cycle_id,
            data.assignee_user_id,
            data.assignee_type,
            data.assignee_org_id or org_id,
        )

        # Determine initial status
        initial_status = TargetStatus.DRAFT
        locked_at = None
        if cycle.status == CycleStatus.ACTIVE:
            initial_status = TargetStatus.LOCKED
            locked_at = datetime.now(timezone.utc)

        target = KPITarget(
            kpi_id=data.kpi_id,
            review_cycle_id=data.review_cycle_id,
            assignee_type=data.assignee_type,
            assignee_user_id=data.assignee_user_id,
            assignee_org_id=data.assignee_org_id or org_id,
            target_value=data.target_value,
            stretch_target_value=data.stretch_target_value,
            minimum_value=data.minimum_value,
            weight=data.weight,
            status=initial_status,
            notes=data.notes,
            set_by_id=current_user.id,
            locked_at=locked_at,
        )
        db.add(target)
        await db.flush()

        # Create milestones
        for ms in data.milestones:
            milestone = TargetMilestone(
                target_id=target.id,
                milestone_date=ms.milestone_date,
                expected_value=ms.expected_value,
                label=ms.label,
            )
            db.add(milestone)

        await db.flush()
        return await _get_target_or_404(db, target.id, org_id)

    async def bulk_create_targets(
        self,
        db: AsyncSession,
        org_id: UUID,
        current_user: User,
        data: KPITargetBulkCreate,
    ) -> list[KPITarget]:
        """
        Create individual targets for multiple users in a single transaction.

        Each entry in user_targets must contain:
        {
            "user_id": UUID str,
            "target_value": float,
            "weight": float,            # optional, default 100
            "stretch_target_value": float | null,
            "minimum_value": float | null,
            "notes": str | null
        }
        """
        _assert_can_set_target(current_user, UUID(int=0))  # role check only
        kpi = await _get_kpi_active_or_404(db, data.kpi_id, org_id)
        cycle = await _get_cycle_open_or_404(db, data.review_cycle_id, org_id)

        created = []
        initial_status = TargetStatus.DRAFT
        locked_at = None
        if cycle.status == CycleStatus.ACTIVE:
            initial_status = TargetStatus.LOCKED
            locked_at = datetime.now(timezone.utc)

        for item in data.user_targets:
            user_id = UUID(str(item["user_id"]))
            target_value = Decimal(str(item["target_value"]))
            weight = Decimal(str(item.get("weight", "100.00")))
            stretch = (
                Decimal(str(item["stretch_target_value"]))
                if item.get("stretch_target_value") is not None
                else None
            )
            minimum = (
                Decimal(str(item["minimum_value"]))
                if item.get("minimum_value") is not None
                else None
            )

            if target_value <= 0:
                raise BadRequestException(
                    f"target_value for user '{user_id}' must be positive."
                )
            if stretch is not None and stretch <= target_value:
                raise BadRequestException(
                    f"stretch_target_value for user '{user_id}' must exceed target_value."
                )
            if minimum is not None and minimum >= target_value:
                raise BadRequestException(
                    f"minimum_value for user '{user_id}' must be less than target_value."
                )

            await _check_duplicate_target(
                db, data.kpi_id, data.review_cycle_id, user_id, TargetLevel.INDIVIDUAL, org_id
            )

            target = KPITarget(
                kpi_id=data.kpi_id,
                review_cycle_id=data.review_cycle_id,
                assignee_type=TargetLevel.INDIVIDUAL,
                assignee_user_id=user_id,
                assignee_org_id=org_id,
                target_value=target_value,
                stretch_target_value=stretch,
                minimum_value=minimum,
                weight=weight,
                status=initial_status,
                notes=item.get("notes"),
                set_by_id=current_user.id,
                locked_at=locked_at,
            )
            db.add(target)
            await db.flush()
            created.append(target)

        return [
            await _get_target_or_404(db, t.id, org_id) for t in created
        ]

    async def cascade_target(
        self,
        db: AsyncSession,
        org_id: UUID,
        current_user: User,
        data: CascadeTargetRequest,
    ) -> list[KPITarget]:
        """
        Distribute a parent target down to individual employees.

        Strategies:
        - manual:        use the target_value provided per user exactly as given.
        - equal:         parent.target_value / num_users for each.
        - proportional:  each user's weight / sum_of_weights * parent.target_value.

        total_check (default True): validates that the summed distribution does
        not exceed the parent target value by more than 1% tolerance.
        """
        _assert_can_set_target(current_user, None)
        parent = await _get_target_or_404(db, data.parent_target_id, org_id)
        cycle = await _get_cycle_open_or_404(db, parent.review_cycle_id, org_id)

        if not data.distribution:
            raise BadRequestException("distribution must contain at least one entry.")

        n = len(data.distribution)
        parent_value = parent.target_value

        initial_status = TargetStatus.DRAFT
        locked_at = None
        if cycle.status == CycleStatus.ACTIVE:
            initial_status = TargetStatus.LOCKED
            locked_at = datetime.now(timezone.utc)

        if data.strategy == "equal":
            equal_value = (parent_value / n).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )
            for item in data.distribution:
                item["target_value"] = float(equal_value)

        elif data.strategy == "proportional":
            weights = [Decimal(str(item.get("weight", 1))) for item in data.distribution]
            sum_weights = sum(weights)
            if sum_weights == 0:
                raise BadRequestException(
                    "Sum of weights in distribution must be greater than zero."
                )
            for item, w in zip(data.distribution, weights):
                item["target_value"] = float(
                    (w / sum_weights * parent_value).quantize(
                        Decimal("0.0001"), rounding=ROUND_HALF_UP
                    )
                )

        # total_check: sum of child values should not exceed parent (with 1% tolerance)
        if data.total_check:
            total_dist = sum(
                Decimal(str(item["target_value"])) for item in data.distribution
            )
            tolerance = parent_value * Decimal("0.01")
            if total_dist > parent_value + tolerance:
                raise BadRequestException(
                    f"Total distribution ({total_dist}) exceeds parent target "
                    f"({parent_value}) by more than 1% tolerance. "
                    "Adjust values or set total_check=false to override."
                )

        created = []
        for item in data.distribution:
            user_id = UUID(str(item["user_id"]))
            target_value = Decimal(str(item["target_value"]))
            weight = Decimal(str(item.get("weight", "100.00")))

            if target_value <= 0:
                raise BadRequestException(
                    f"target_value for user '{user_id}' must be positive."
                )

            await _check_duplicate_target(
                db,
                parent.kpi_id,
                parent.review_cycle_id,
                user_id,
                TargetLevel.INDIVIDUAL,
                org_id,
            )

            child = KPITarget(
                kpi_id=parent.kpi_id,
                review_cycle_id=parent.review_cycle_id,
                assignee_type=TargetLevel.INDIVIDUAL,
                assignee_user_id=user_id,
                assignee_org_id=org_id,
                target_value=target_value,
                stretch_target_value=parent.stretch_target_value,
                minimum_value=parent.minimum_value,
                weight=weight,
                status=initial_status,
                cascade_parent_id=parent.id,
                notes=item.get("notes"),
                set_by_id=current_user.id,
                locked_at=locked_at,
            )
            db.add(child)
            await db.flush()
            created.append(child)

        return [
            await _get_target_or_404(db, t.id, org_id) for t in created
        ]

    async def get_target_by_id(
        self, db: AsyncSession, target_id: UUID, org_id: UUID
    ) -> KPITarget:
        return await _get_target_or_404(db, target_id, org_id)

    async def get_user_targets_for_cycle(
        self,
        db: AsyncSession,
        assignee_user_id: UUID,
        cycle_id: UUID,
        org_id: UUID,
    ) -> list[KPITarget]:
        result = await db.execute(
            select(KPITarget)
            .join(ReviewCycle, KPITarget.review_cycle_id == ReviewCycle.id)
            .where(
                KPITarget.assignee_user_id == assignee_user_id,
                KPITarget.review_cycle_id == cycle_id,
                ReviewCycle.organisation_id == org_id,
            )
            .options(*_target_load_options())
        )
        return list(result.scalars().all())

    async def list_targets(
        self,
        db: AsyncSession,
        org_id: UUID,
        cycle_id: UUID | None = None,
        user_id: UUID | None = None,
        kpi_id: UUID | None = None,
        assignee_type: TargetLevel | None = None,
        status: TargetStatus | None = None,
        at_risk_only: bool = False,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        from sqlalchemy import func

        query = (
            select(KPITarget)
            .join(ReviewCycle, KPITarget.review_cycle_id == ReviewCycle.id)
            .where(ReviewCycle.organisation_id == org_id)
        )
        if cycle_id:
            query = query.where(KPITarget.review_cycle_id == cycle_id)
        if user_id:
            query = query.where(KPITarget.assignee_user_id == user_id)
        if kpi_id:
            query = query.where(KPITarget.kpi_id == kpi_id)
        if assignee_type:
            query = query.where(KPITarget.assignee_type == assignee_type)
        if status:
            query = query.where(KPITarget.status == status)

        count_result = await db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = count_result.scalar_one()

        import math

        offset = (page - 1) * size
        query = (
            query.options(*_target_load_options())
            .order_by(KPITarget.created_at.desc())
            .offset(offset)
            .limit(size)
        )
        result = await db.execute(query)
        items = list(result.scalars().all())

        # at_risk_only is applied post-DB since it requires actual computation
        if at_risk_only:
            items = [t for t in items if await self._is_at_risk(t)]

        pages = math.ceil(total / size) if size else 1
        return {"items": items, "total": total, "page": page, "size": size, "pages": pages}

    async def update_target(
        self,
        db: AsyncSession,
        target_id: UUID,
        org_id: UUID,
        current_user: User,
        data: KPITargetUpdate,
    ) -> KPITarget:
        """
        Update a target's values.

        LOCKED targets cannot be modified — the performance period has begun.
        Only the creator (set_by_id), a manager, or hr_admin may update.
        """
        target = await _get_target_or_404(db, target_id, org_id)

        if target.status == TargetStatus.LOCKED:
            raise ForbiddenException(
                "This target is LOCKED — the review period has started. "
                "No further modifications are allowed."
            )

        _assert_can_set_target(current_user, target.assignee_user_id)

        if data.target_value is not None:
            target.target_value = data.target_value
        if data.stretch_target_value is not None:
            target.stretch_target_value = data.stretch_target_value
        if data.minimum_value is not None:
            target.minimum_value = data.minimum_value
        if data.weight is not None:
            target.weight = data.weight
        if data.notes is not None:
            target.notes = data.notes

        # Replace milestones if provided
        if data.milestones is not None:
            # Delete existing milestones
            for ms in list(target.milestones):
                await db.delete(ms)
            await db.flush()
            for ms in data.milestones:
                db.add(
                    TargetMilestone(
                        target_id=target.id,
                        milestone_date=ms.milestone_date,
                        expected_value=ms.expected_value,
                        label=ms.label,
                    )
                )

        target.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return await _get_target_or_404(db, target.id, org_id)

    async def acknowledge_target(
        self,
        db: AsyncSession,
        target_id: UUID,
        org_id: UUID,
        current_user: User,
    ) -> KPITarget:
        """
        Allow the assignee to acknowledge their target.

        Business rules:
        - Only the designated individual assignee may acknowledge.
        - Target must be in PENDING_ACKNOWLEDGEMENT or DRAFT (before locking).
        - Sets status → ACKNOWLEDGED, records acknowledged_by_id and timestamp.
        """
        target = await _get_target_or_404(db, target_id, org_id)

        if target.assignee_user_id != current_user.id:
            raise ForbiddenException(
                "Only the assigned employee can acknowledge their own target."
            )
        if target.status not in {
            TargetStatus.PENDING_ACKNOWLEDGEMENT,
            TargetStatus.DRAFT,
            TargetStatus.APPROVED,
        }:
            raise BadRequestException(
                f"Cannot acknowledge a target in '{target.status.value}' status."
            )

        target.status = TargetStatus.ACKNOWLEDGED
        target.acknowledged_by_id = current_user.id
        target.acknowledged_at = datetime.now(timezone.utc)
        target.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return await _get_target_or_404(db, target.id, org_id)

    async def update_target_status(
        self,
        db: AsyncSession,
        target_id: UUID,
        org_id: UUID,
        current_user: User,
        new_status: TargetStatus,
    ) -> KPITarget:
        """
        Manually transition a target's workflow status.

        Allowed transitions (hr_admin / manager):
            DRAFT → PENDING_ACKNOWLEDGEMENT
            DRAFT → APPROVED
            ACKNOWLEDGED → APPROVED
        Employee can only:
            PENDING_ACKNOWLEDGEMENT → ACKNOWLEDGED  (use acknowledge_target instead)
        """
        target = await _get_target_or_404(db, target_id, org_id)

        if target.status == TargetStatus.LOCKED:
            raise ForbiddenException("LOCKED targets cannot have their status changed.")

        _valid_transitions: dict[TargetStatus, set[TargetStatus]] = {
            TargetStatus.DRAFT: {
                TargetStatus.PENDING_ACKNOWLEDGEMENT,
                TargetStatus.APPROVED,
            },
            TargetStatus.PENDING_ACKNOWLEDGEMENT: {TargetStatus.ACKNOWLEDGED},
            TargetStatus.ACKNOWLEDGED: {TargetStatus.APPROVED},
            TargetStatus.APPROVED: {TargetStatus.DRAFT},  # revert
        }

        allowed = _valid_transitions.get(target.status, set())
        if new_status not in allowed:
            raise BadRequestException(
                f"Cannot transition target from '{target.status.value}' "
                f"to '{new_status.value}'. Allowed: {[s.value for s in allowed]}"
            )

        target.status = new_status
        target.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return await _get_target_or_404(db, target.id, org_id)

    async def get_target_with_progress(
        self, db: AsyncSession, target_id: UUID, org_id: UUID
    ) -> dict:
        """
        Return a target enriched with live progress metrics.

        Metrics computed:
        - latest_actual_value: most recently APPROVED actual
        - total_actual_to_date: cumulative or latest depending on KPI type
        - achievement_percentage: (actual / target) * 100, direction-adjusted
        - milestone_status: for each milestone, actual vs expected
        - is_at_risk: True if past 50% of period and achievement < 60%
        - trend: "improving" | "declining" | "stable" based on last 3 actuals
        """
        from app.actuals.enums import ActualEntryStatus
        from app.actuals.models import KPIActual

        target = await _get_target_or_404(db, target_id, org_id)

        # Fetch approved actuals ordered by period_date
        result = await db.execute(
            select(KPIActual)
            .where(
                KPIActual.target_id == target_id,
                KPIActual.status == ActualEntryStatus.APPROVED,
            )
            .order_by(KPIActual.period_date)
        )
        actuals = list(result.scalars().all())

        latest_actual = actuals[-1] if actuals else None
        latest_value = latest_actual.actual_value if latest_actual else None

        # For most KPI types, "to date" is the cumulative sum.
        # For PERCENTAGE / RATIO / SCORE, it's the latest value (not summed).
        from app.kpis.enums import MeasurementUnit

        sum_units = {
            MeasurementUnit.COUNT,
            MeasurementUnit.CURRENCY,
            MeasurementUnit.DURATION_HOURS,
        }
        if target.kpi.unit in sum_units:
            total_to_date: Decimal | None = (
                sum(a.actual_value for a in actuals) if actuals else None
            )
        else:
            total_to_date = latest_value

        achievement_pct: Decimal | None = None
        if total_to_date is not None:
            achievement_pct = _compute_achievement(
                total_to_date, target.target_value, target.kpi.scoring_direction
            )

        # Trend: compare last 3 actuals
        trend: str | None = None
        if len(actuals) >= 3:
            last3 = [a.actual_value for a in actuals[-3:]]
            if last3[-1] > last3[0]:
                trend = "improving" if target.kpi.scoring_direction == ScoringDirection.HIGHER_IS_BETTER else "declining"
            elif last3[-1] < last3[0]:
                trend = "declining" if target.kpi.scoring_direction == ScoringDirection.HIGHER_IS_BETTER else "improving"
            else:
                trend = "stable"
        elif len(actuals) >= 2:
            trend = "improving" if actuals[-1].actual_value >= actuals[-2].actual_value else "declining"

        # Is at risk? Past 50% of cycle duration and achievement < 60%
        is_at_risk = False
        if achievement_pct is not None:
            cycle = target.review_cycle
            total_days = (cycle.end_date - cycle.start_date).days
            elapsed_days = (date.today() - cycle.start_date).days
            if total_days > 0 and elapsed_days / total_days >= 0.5:
                is_at_risk = achievement_pct < Decimal("60")

        # Milestone status
        milestone_status = []
        for ms in target.milestones:
            # Find the closest actual by period date
            ms_actuals = [a for a in actuals if a.period_date <= ms.milestone_date]
            ms_actual_value = ms_actuals[-1].actual_value if ms_actuals else None
            milestone_status.append(
                {
                    "milestone_id": str(ms.id),
                    "milestone_date": ms.milestone_date.isoformat(),
                    "expected_value": float(ms.expected_value),
                    "actual_value": float(ms_actual_value) if ms_actual_value is not None else None,
                    "label": ms.label,
                    "on_track": (
                        ms_actual_value >= ms.expected_value
                        if ms_actual_value is not None
                        else None
                    ),
                }
            )

        return {
            "target": target,
            "latest_actual_value": latest_value,
            "total_actual_to_date": total_to_date,
            "achievement_percentage": achievement_pct,
            "is_at_risk": is_at_risk,
            "trend": trend,
            "milestone_status": milestone_status,
        }

    async def validate_weights_for_user_cycle(
        self,
        db: AsyncSession,
        user_id: UUID,
        cycle_id: UUID,
        org_id: UUID,
    ) -> WeightsCheckResponse:
        """
        Check whether a user's KPI targets for a cycle sum to 100% weight.

        Returns a warning message if the total is not exactly 100.
        """
        result = await db.execute(
            select(KPITarget)
            .join(ReviewCycle, KPITarget.review_cycle_id == ReviewCycle.id)
            .where(
                KPITarget.assignee_user_id == user_id,
                KPITarget.review_cycle_id == cycle_id,
                ReviewCycle.organisation_id == org_id,
            )
        )
        targets = list(result.scalars().all())
        if not targets:
            return WeightsCheckResponse(
                user_id=user_id,
                cycle_id=cycle_id,
                total_weight=Decimal("0"),
                is_valid=False,
                warning="No targets found for this user in the specified cycle.",
            )

        total = sum(t.weight for t in targets)
        is_valid = total == Decimal("100.00")
        warning = None
        if not is_valid:
            warning = (
                f"Total weight is {total:.2f}%, not 100%. "
                "Weighted scoring results will be proportional to this total."
            )

        return WeightsCheckResponse(
            user_id=user_id,
            cycle_id=cycle_id,
            total_weight=total,
            is_valid=is_valid,
            warning=warning,
        )

    async def get_cascade_tree(
        self, db: AsyncSession, target_id: UUID, org_id: UUID
    ) -> KPITarget:
        """Return the target with its full cascade tree loaded."""
        result = await db.execute(
            select(KPITarget)
            .join(ReviewCycle, KPITarget.review_cycle_id == ReviewCycle.id)
            .where(
                KPITarget.id == target_id,
                ReviewCycle.organisation_id == org_id,
            )
            .options(
                selectinload(KPITarget.cascade_children).selectinload(
                    KPITarget.cascade_children
                )
            )
        )
        target = result.scalar_one_or_none()
        if not target:
            raise NotFoundException(f"Target '{target_id}' not found")
        return target

    async def _is_at_risk(self, target: KPITarget) -> bool:
        """Quick at-risk check without loading actuals (uses pre-loaded data)."""
        return False  # Placeholder; full check in get_target_with_progress
