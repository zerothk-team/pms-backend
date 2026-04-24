"""
ReviewCycleService — all business logic for review cycle management.

Review cycles define the time-bounded performance evaluation periods.
They gate target setting and actuals entry, and drive the scoring workflow.
"""

import math
from datetime import date, datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import BadRequestException, ConflictException, NotFoundException
from app.kpis.enums import MeasurementFrequency
from app.review_cycles.enums import CycleStatus
from app.review_cycles.models import ReviewCycle
from app.review_cycles.schemas import (
    PaginatedReviewCycles,
    ReviewCycleCreate,
    ReviewCycleStatusUpdate,
    ReviewCycleUpdate,
)
from app.utils import get_period_start_dates

# ---------------------------------------------------------------------------
# Valid status transitions
# ---------------------------------------------------------------------------

_CYCLE_TRANSITIONS: dict[CycleStatus, set[CycleStatus]] = {
    CycleStatus.DRAFT: {CycleStatus.ACTIVE},
    CycleStatus.ACTIVE: {CycleStatus.CLOSED},
    CycleStatus.CLOSED: {CycleStatus.ARCHIVED},
    CycleStatus.ARCHIVED: set(),
}

# hr_admin can additionally revert a CLOSED cycle back to ACTIVE
# (e.g., to allow late actual submissions) or ACTIVE back to DRAFT
_HR_ADMIN_EXTRA: dict[CycleStatus, set[CycleStatus]] = {
    CycleStatus.ACTIVE: {CycleStatus.DRAFT},
    CycleStatus.CLOSED: {CycleStatus.ACTIVE},
}


def _allowed_transitions(status: CycleStatus, is_hr_admin: bool) -> set[CycleStatus]:
    allowed = _CYCLE_TRANSITIONS.get(status, set()).copy()
    if is_hr_admin:
        allowed |= _HR_ADMIN_EXTRA.get(status, set())
    return allowed


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_cycle_or_404(
    db: AsyncSession, cycle_id: UUID, org_id: UUID
) -> ReviewCycle:
    result = await db.execute(
        select(ReviewCycle).where(
            ReviewCycle.id == cycle_id,
            ReviewCycle.organisation_id == org_id,
        )
    )
    cycle = result.scalar_one_or_none()
    if not cycle:
        raise NotFoundException(f"Review cycle '{cycle_id}' not found")
    return cycle


async def _check_no_active_overlap(
    db: AsyncSession,
    org_id: UUID,
    start_date: date,
    end_date: date,
    exclude_id: UUID | None = None,
) -> None:
    """Raise ConflictException if any ACTIVE cycle overlaps the proposed date range."""
    stmt = select(ReviewCycle).where(
        ReviewCycle.organisation_id == org_id,
        ReviewCycle.status == CycleStatus.ACTIVE,
        ReviewCycle.start_date <= end_date,
        ReviewCycle.end_date >= start_date,
    )
    if exclude_id:
        stmt = stmt.where(ReviewCycle.id != exclude_id)

    result = await db.execute(stmt)
    overlapping = result.scalar_one_or_none()
    if overlapping:
        raise ConflictException(
            f"An ACTIVE review cycle '{overlapping.name}' "
            f"({overlapping.start_date} – {overlapping.end_date}) already overlaps "
            "with the proposed dates. Only one ACTIVE cycle may run per organisation "
            "at a time."
        )


# ---------------------------------------------------------------------------
# ReviewCycleService
# ---------------------------------------------------------------------------


class ReviewCycleService:

    async def create_cycle(
        self,
        db: AsyncSession,
        org_id: UUID,
        user_id: UUID,
        data: ReviewCycleCreate,
    ) -> ReviewCycle:
        """
        Create a new review cycle in DRAFT status.

        Business rules:
        - end_date must be after start_date (validated in schema)
        - No ACTIVE cycle may overlap the proposed dates
        """
        await _check_no_active_overlap(db, org_id, data.start_date, data.end_date)

        cycle = ReviewCycle(
            name=data.name,
            cycle_type=data.cycle_type,
            status=CycleStatus.DRAFT,
            start_date=data.start_date,
            end_date=data.end_date,
            target_setting_deadline=data.target_setting_deadline,
            actual_entry_deadline=data.actual_entry_deadline,
            scoring_start_date=data.scoring_start_date,
            organisation_id=org_id,
            created_by_id=user_id,
        )
        db.add(cycle)
        await db.flush()
        await db.refresh(cycle)
        return cycle

    async def get_by_id(
        self, db: AsyncSession, cycle_id: UUID, org_id: UUID
    ) -> ReviewCycle:
        return await _get_cycle_or_404(db, cycle_id, org_id)

    async def list_cycles(
        self,
        db: AsyncSession,
        org_id: UUID,
        status: CycleStatus | None = None,
        page: int = 1,
        size: int = 20,
    ) -> PaginatedReviewCycles:
        query = select(ReviewCycle).where(ReviewCycle.organisation_id == org_id)
        if status:
            query = query.where(ReviewCycle.status == status)

        count_result = await db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = count_result.scalar_one()

        offset = (page - 1) * size
        query = query.order_by(ReviewCycle.start_date.desc()).offset(offset).limit(size)
        result = await db.execute(query)
        items = list(result.scalars().all())

        pages = math.ceil(total / size) if size else 1
        return PaginatedReviewCycles(
            items=items, total=total, page=page, size=size, pages=pages
        )

    async def get_active_cycle(
        self, db: AsyncSession, org_id: UUID
    ) -> ReviewCycle | None:
        """Return the currently active cycle where today falls within start-end range."""
        today = date.today()
        result = await db.execute(
            select(ReviewCycle).where(
                ReviewCycle.organisation_id == org_id,
                ReviewCycle.status == CycleStatus.ACTIVE,
                ReviewCycle.start_date <= today,
                ReviewCycle.end_date >= today,
            )
        )
        return result.scalar_one_or_none()

    async def update_cycle(
        self,
        db: AsyncSession,
        cycle_id: UUID,
        org_id: UUID,
        data: ReviewCycleUpdate,
    ) -> ReviewCycle:
        """
        Update editable fields on a DRAFT cycle.

        Only DRAFT cycles can be edited — once activated the dates and type
        are immutable to protect the integrity of targets and actuals.
        """
        cycle = await _get_cycle_or_404(db, cycle_id, org_id)

        if cycle.status != CycleStatus.DRAFT:
            raise BadRequestException(
                f"Review cycle '{cycle_id}' is in '{cycle.status.value}' status. "
                "Only DRAFT cycles can be edited."
            )

        if data.name is not None:
            cycle.name = data.name
        if data.target_setting_deadline is not None:
            cycle.target_setting_deadline = data.target_setting_deadline
        if data.actual_entry_deadline is not None:
            cycle.actual_entry_deadline = data.actual_entry_deadline
        if data.scoring_start_date is not None:
            cycle.scoring_start_date = data.scoring_start_date

        cycle.updated_at = datetime.now(timezone.utc)
        await db.flush()
        await db.refresh(cycle)
        return cycle

    async def update_status(
        self,
        db: AsyncSession,
        cycle_id: UUID,
        org_id: UUID,
        data: ReviewCycleStatusUpdate,
        is_hr_admin: bool = False,
    ) -> ReviewCycle:
        """
        Transition a review cycle through its lifecycle.

        Standard transitions (any authorised user):
            DRAFT → ACTIVE
            ACTIVE → CLOSED
            CLOSED → ARCHIVED

        HR admin extra transitions:
            ACTIVE → DRAFT  (revert for corrections)
            CLOSED → ACTIVE (re-open for late actuals)

        Side-effects:
            DRAFT → ACTIVE: locks all targets in DRAFT/PENDING/ACKNOWLEDGED/APPROVED
        """
        cycle = await _get_cycle_or_404(db, cycle_id, org_id)
        allowed = _allowed_transitions(cycle.status, is_hr_admin)

        if data.status not in allowed:
            raise BadRequestException(
                f"Cannot transition review cycle from '{cycle.status.value}' "
                f"to '{data.status.value}'. "
                f"Allowed: {[s.value for s in allowed] or 'none'}"
            )

        if data.status == CycleStatus.ACTIVE:
            # Validate no other ACTIVE cycle overlaps these dates
            await _check_no_active_overlap(
                db, org_id, cycle.start_date, cycle.end_date, exclude_id=cycle_id
            )
            # Lock all outstanding targets
            locked_count = await self._lock_targets_for_cycle(db, cycle_id)
            # Stub: send notification that cycle is now active

        if data.status == CycleStatus.CLOSED:
            # Stub: trigger period-close notifications and scoring initiation
            pass

        cycle.status = data.status
        cycle.updated_at = datetime.now(timezone.utc)
        await db.flush()
        await db.refresh(cycle)
        return cycle

    async def _lock_targets_for_cycle(
        self, db: AsyncSession, cycle_id: UUID
    ) -> int:
        """
        Bulk-lock all targets for the cycle when it transitions to ACTIVE.

        Any target not yet in LOCKED state is locked so that no further
        modifications are allowed once the performance period begins.
        Returns the number of targets locked.
        """
        # Import here to avoid circular imports at module load time
        from app.targets.enums import TargetStatus
        from app.targets.models import KPITarget

        now = datetime.now(timezone.utc)
        result = await db.execute(
            select(KPITarget).where(
                KPITarget.review_cycle_id == cycle_id,
                KPITarget.status.in_(
                    [
                        TargetStatus.DRAFT,
                        TargetStatus.PENDING_ACKNOWLEDGEMENT,
                        TargetStatus.ACKNOWLEDGED,
                        TargetStatus.APPROVED,
                    ]
                ),
            )
        )
        targets = list(result.scalars().all())
        for target in targets:
            target.status = TargetStatus.LOCKED
            target.locked_at = now
        await db.flush()
        return len(targets)

    def get_current_measurement_periods(
        self, cycle: ReviewCycle, kpi_frequency: MeasurementFrequency
    ) -> list[date]:
        """
        Return the expected measurement period start dates for a KPI within this cycle.

        Example: a MONTHLY KPI in a Q1 cycle → [2025-01-01, 2025-02-01, 2025-03-01]
        """
        return get_period_start_dates(cycle.start_date, cycle.end_date, kpi_frequency)
