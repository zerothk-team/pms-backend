"""
Targets router — all endpoints under /api/v1/targets.

Prefix: /targets
Tags:   Targets
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_active_user, require_roles
from app.exceptions import ForbiddenException
from app.targets.enums import TargetLevel, TargetStatus
from app.targets.schemas import (
    CascadeTargetRequest,
    CascadeTreeNode,
    KPITargetBulkCreate,
    KPITargetCreate,
    KPITargetProgressRead,
    KPITargetRead,
    KPITargetStatusUpdate,
    KPITargetUpdate,
    WeightsCheckResponse,
)
from app.targets.service import TargetService
from app.users.models import User

router = APIRouter(prefix="/targets", tags=["Targets"])
_service = TargetService()


def _org_id(user: User) -> UUID:
    if not user.organisation_id:
        raise ForbiddenException("User is not associated with an organisation")
    return user.organisation_id


# ---------------------------------------------------------------------------
# List / query endpoints  (must come before /{target_id} to avoid routing conflicts)
# ---------------------------------------------------------------------------


@router.get(
    "/me",
    response_model=list[KPITargetRead],
    summary="My targets",
    description=(
        "Returns all targets assigned to the authenticated user in the "
        "specified review cycle, or the active cycle if cycle_id is omitted."
    ),
)
async def get_my_targets(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    cycle_id: UUID | None = Query(default=None),
) -> list[KPITargetRead]:
    """Return the current user's targets."""
    if cycle_id is None:
        from app.review_cycles.service import ReviewCycleService
        cycle = await ReviewCycleService().get_active_cycle(db, _org_id(current_user))
        if not cycle:
            return []
        cycle_id = cycle.id

    targets = await _service.get_user_targets_for_cycle(
        db, current_user.id, cycle_id, _org_id(current_user)
    )
    return [KPITargetRead.model_validate(t) for t in targets]


@router.get(
    "/weights-check",
    response_model=WeightsCheckResponse,
    summary="Check KPI weight balance",
    description=(
        "Returns the total weight of all targets assigned to a user in a given "
        "cycle and warns if the total is not 100%."
    ),
)
async def weights_check(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    cycle_id: UUID = Query(...),
    user_id: UUID | None = Query(default=None),
) -> WeightsCheckResponse:
    """Validate that a user's target weights sum to 100%."""
    effective_user_id = user_id or current_user.id
    return await _service.validate_weights_for_user_cycle(
        db, effective_user_id, cycle_id, _org_id(current_user)
    )


@router.get(
    "/",
    response_model=dict,
    summary="List targets",
    description=(
        "Returns a paginated, filterable list of targets within the organisation. "
        "Filter by cycle, user, KPI, assignee type, status, or at-risk flag."
    ),
)
async def list_targets(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    cycle_id: UUID | None = Query(default=None),
    user_id: UUID | None = Query(default=None),
    kpi_id: UUID | None = Query(default=None),
    assignee_type: TargetLevel | None = Query(default=None),
    status: TargetStatus | None = Query(default=None),
    at_risk_only: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict:
    return await _service.list_targets(
        db,
        _org_id(current_user),
        cycle_id=cycle_id,
        user_id=user_id,
        kpi_id=kpi_id,
        assignee_type=assignee_type,
        status=status,
        at_risk_only=at_risk_only,
        page=page,
        size=size,
    )


# ---------------------------------------------------------------------------
# Create endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/",
    response_model=KPITargetRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a KPI target",
    description=(
        "Create a target for a KPI within a review cycle."
        " Requires hr_admin, executive, or manager role."
    ),
)
async def create_target(
    data: KPITargetCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> KPITargetRead:
    target = await _service.create_target(db, _org_id(current_user), current_user, data)
    return KPITargetRead.model_validate(target)


@router.post(
    "/bulk",
    response_model=list[KPITargetRead],
    status_code=status.HTTP_201_CREATED,
    summary="Bulk-create targets for a team",
    description=(
        "Assign the same KPI to multiple users at once. "
        "Creates one individual target per user entry."
    ),
)
async def bulk_create_targets(
    data: KPITargetBulkCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles("hr_admin", "manager", "executive"))],
) -> list[KPITargetRead]:
    targets = await _service.bulk_create_targets(
        db, _org_id(current_user), current_user, data
    )
    return [KPITargetRead.model_validate(t) for t in targets]


@router.post(
    "/cascade",
    response_model=list[KPITargetRead],
    status_code=status.HTTP_201_CREATED,
    summary="Cascade a target to individuals",
    description=(
        "Distribute an organisation or department target downward to individual employees. "
        "Supports manual, equal, and proportional distribution strategies."
    ),
)
async def cascade_target(
    data: CascadeTargetRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles("hr_admin", "manager", "executive"))],
) -> list[KPITargetRead]:
    targets = await _service.cascade_target(
        db, _org_id(current_user), current_user, data
    )
    return [KPITargetRead.model_validate(t) for t in targets]


# ---------------------------------------------------------------------------
# Single-target endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/{target_id}",
    response_model=KPITargetProgressRead,
    summary="Get target with progress",
    description=(
        "Returns a single target by ID, enriched with live progress metrics: "
        "achievement %, trend, at-risk status, and milestone tracking."
    ),
)
async def get_target(
    target_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> KPITargetProgressRead:
    progress = await _service.get_target_with_progress(
        db, target_id, _org_id(current_user)
    )
    target = progress["target"]
    base = KPITargetProgressRead.model_validate(target)
    base.latest_actual_value = progress["latest_actual_value"]
    base.total_actual_to_date = progress["total_actual_to_date"]
    base.achievement_percentage = progress["achievement_percentage"]
    base.is_at_risk = progress["is_at_risk"]
    base.trend = progress["trend"]
    return base


@router.put(
    "/{target_id}",
    response_model=KPITargetRead,
    summary="Update a target",
    description=(
        "Update target values and milestones. "
        "Blocked for LOCKED targets (review period has started)."
    ),
)
async def update_target(
    target_id: UUID,
    data: KPITargetUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> KPITargetRead:
    target = await _service.update_target(
        db, target_id, _org_id(current_user), current_user, data
    )
    return KPITargetRead.model_validate(target)


@router.patch(
    "/{target_id}/acknowledge",
    response_model=KPITargetRead,
    summary="Acknowledge a target",
    description=(
        "The assigned employee acknowledges receipt and acceptance of their target. "
        "Only the assigned individual can call this endpoint."
    ),
)
async def acknowledge_target(
    target_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> KPITargetRead:
    target = await _service.acknowledge_target(
        db, target_id, _org_id(current_user), current_user
    )
    return KPITargetRead.model_validate(target)


@router.patch(
    "/{target_id}/status",
    response_model=KPITargetRead,
    summary="Update target workflow status",
    description=(
        "Manually transition a target through the approval workflow: "
        "DRAFT → PENDING_ACKNOWLEDGEMENT → ACKNOWLEDGED → APPROVED. "
        "Requires hr_admin or manager role."
    ),
)
async def update_target_status(
    target_id: UUID,
    data: KPITargetStatusUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles("hr_admin", "manager"))],
) -> KPITargetRead:
    target = await _service.update_target_status(
        db, target_id, _org_id(current_user), current_user, data.status
    )
    return KPITargetRead.model_validate(target)


@router.get(
    "/{target_id}/cascade-tree",
    response_model=CascadeTreeNode,
    summary="View cascade tree",
    description=(
        "Returns the target and its full downward cascade tree: "
        "parent → children → grandchildren."
    ),
)
async def get_cascade_tree(
    target_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CascadeTreeNode:
    target = await _service.get_cascade_tree(db, target_id, _org_id(current_user))
    return CascadeTreeNode.model_validate(target)
