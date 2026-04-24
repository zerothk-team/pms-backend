"""
Review Cycles router — all endpoints under /api/v1/review-cycles.

Prefix: /review-cycles
Tags:   Review Cycles
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_active_user, require_roles
from app.exceptions import ForbiddenException
from app.review_cycles.enums import CycleStatus
from app.review_cycles.schemas import (
    PaginatedReviewCycles,
    ReviewCycleCreate,
    ReviewCycleRead,
    ReviewCycleStatusUpdate,
    ReviewCycleUpdate,
)
from app.review_cycles.service import ReviewCycleService
from app.users.models import User, UserRole

router = APIRouter(prefix="/review-cycles", tags=["Review Cycles"])
_service = ReviewCycleService()


def _org_id(user: User) -> UUID:
    if not user.organisation_id:
        raise ForbiddenException("User is not associated with an organisation")
    return user.organisation_id


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/",
    response_model=ReviewCycleRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a review cycle",
    description=(
        "Creates a new review cycle in DRAFT status. "
        "Validates that no ACTIVE cycle overlaps the proposed dates. "
        "Requires hr_admin role."
    ),
)
async def create_cycle(
    data: ReviewCycleCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles("hr_admin"))],
) -> ReviewCycleRead:
    cycle = await _service.create_cycle(db, _org_id(current_user), current_user.id, data)
    return ReviewCycleRead.model_validate(cycle)


@router.get(
    "/",
    response_model=PaginatedReviewCycles,
    summary="List review cycles",
    description="Returns a paginated list of review cycles for the organisation. "
    "Optionally filter by status.",
)
async def list_cycles(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    status: CycleStatus | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> PaginatedReviewCycles:
    return await _service.list_cycles(
        db, _org_id(current_user), status=status, page=page, size=size
    )


@router.get(
    "/active",
    response_model=ReviewCycleRead | None,
    summary="Get the currently active cycle",
    description=(
        "Returns the single ACTIVE cycle where today falls within start_date–end_date, "
        "or null if no active cycle exists."
    ),
)
async def get_active_cycle(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> ReviewCycleRead | None:
    cycle = await _service.get_active_cycle(db, _org_id(current_user))
    return ReviewCycleRead.model_validate(cycle) if cycle else None


@router.get(
    "/{cycle_id}",
    response_model=ReviewCycleRead,
    summary="Get a review cycle",
    description="Returns a single review cycle by ID.",
)
async def get_cycle(
    cycle_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> ReviewCycleRead:
    cycle = await _service.get_by_id(db, cycle_id, _org_id(current_user))
    return ReviewCycleRead.model_validate(cycle)


@router.put(
    "/{cycle_id}",
    response_model=ReviewCycleRead,
    summary="Update a review cycle",
    description=(
        "Update editable fields (name, deadline dates) on a DRAFT cycle. "
        "Core dates and type are immutable once set. Requires hr_admin role."
    ),
)
async def update_cycle(
    cycle_id: UUID,
    data: ReviewCycleUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles("hr_admin"))],
) -> ReviewCycleRead:
    cycle = await _service.update_cycle(db, cycle_id, _org_id(current_user), data)
    return ReviewCycleRead.model_validate(cycle)


@router.patch(
    "/{cycle_id}/status",
    response_model=ReviewCycleRead,
    summary="Transition review cycle status",
    description=(
        "Move a review cycle through its lifecycle: "
        "DRAFT → ACTIVE → CLOSED → ARCHIVED. "
        "Activating a cycle locks all outstanding targets. "
        "Requires hr_admin role."
    ),
)
async def update_cycle_status(
    cycle_id: UUID,
    data: ReviewCycleStatusUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles("hr_admin"))],
) -> ReviewCycleRead:
    is_hr_admin = current_user.role == UserRole.hr_admin
    cycle = await _service.update_status(
        db, cycle_id, _org_id(current_user), data, is_hr_admin=is_hr_admin
    )
    return ReviewCycleRead.model_validate(cycle)
