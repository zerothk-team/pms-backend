"""
KPI router — all endpoints under /api/v1/kpis.

Prefix: /kpis
Tags:   KPIs
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_active_user, require_roles
from app.kpis.enums import DataSourceType, DepartmentCategory, KPIStatus
from app.kpis.schemas import (
    FormulaValidationRequest,
    FormulaValidationResponse,
    KPICategoryCreate,
    KPICategoryRead,
    KPICategoryUpdate,
    KPICloneFromTemplate,
    KPICreate,
    KPIHistoryRead,
    KPIRead,
    KPIReadWithDependencies,
    KPIStatusUpdate,
    KPITagRead,
    KPITemplateRead,
    KPIUpdate,
    PaginatedKPIs,
)
from app.kpis.service import KPIService
from app.users.models import User, UserRole

router = APIRouter(prefix="/kpis", tags=["KPIs"])
_service = KPIService()


# ---------------------------------------------------------------------------
# Dependency helpers
# ---------------------------------------------------------------------------

def _org_id(current_user: User) -> UUID:
    """Extract the organisation ID from the authenticated user, raise if missing."""
    if not current_user.organisation_id:
        from app.exceptions import ForbiddenException
        raise ForbiddenException("User is not associated with an organisation")
    return current_user.organisation_id


# ---------------------------------------------------------------------------
# Category endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/categories/",
    response_model=list[KPICategoryRead],
    summary="List KPI categories",
    description="Returns all categories visible to the organisation (org-specific + system-wide).",
)
async def list_categories(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> list[KPICategoryRead]:
    """List all KPI categories for the current user's organisation."""
    categories = await _service.list_categories(db, _org_id(current_user))
    return [KPICategoryRead.model_validate(c) for c in categories]


@router.post(
    "/categories/",
    response_model=KPICategoryRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a KPI category",
    description="Creates a new KPI category for the organisation. Requires hr_admin or manager role.",
)
async def create_category(
    data: KPICategoryCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles("hr_admin", "manager"))],
) -> KPICategoryRead:
    """Create a new KPI category."""
    category = await _service.create_category(db, _org_id(current_user), current_user.id, data)
    return KPICategoryRead.model_validate(category)


@router.put(
    "/categories/{category_id}",
    response_model=KPICategoryRead,
    summary="Update a KPI category",
    description="Updates an existing KPI category. Requires hr_admin role.",
)
async def update_category(
    category_id: UUID,
    data: KPICategoryUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles("hr_admin"))],
) -> KPICategoryRead:
    """Update a KPI category by ID."""
    category = await _service.update_category(db, category_id, _org_id(current_user), data)
    return KPICategoryRead.model_validate(category)


@router.delete(
    "/categories/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a KPI category",
    description="Deletes a KPI category. Fails if any KPIs are still attached. Requires hr_admin role.",
)
async def delete_category(
    category_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles("hr_admin"))],
) -> None:
    """Delete a KPI category if it has no attached KPIs."""
    await _service.delete_category(db, category_id, _org_id(current_user))


# ---------------------------------------------------------------------------
# Tag endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/tags/",
    response_model=list[KPITagRead],
    summary="List KPI tags",
    description="Returns all tags defined within the current organisation.",
)
async def list_tags(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> list[KPITagRead]:
    """List all KPI tags for the current organisation."""
    tags = await _service.list_tags(db, _org_id(current_user))
    return [KPITagRead.model_validate(t) for t in tags]


# ---------------------------------------------------------------------------
# Template endpoints  (MUST come before /{kpi_id} to avoid routing conflicts)
# ---------------------------------------------------------------------------

@router.get(
    "/templates/",
    response_model=list[KPITemplateRead],
    summary="List KPI templates",
    description="Returns the curated library of pre-built KPI templates. Optionally filter by department.",
)
async def list_templates(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    department: DepartmentCategory | None = Query(default=None),
    search: str | None = Query(default=None),
) -> list[KPITemplateRead]:
    """List system KPI templates, optionally filtered by department or search term."""
    templates = await _service.list_templates(db, department=department, search=search)
    return [KPITemplateRead.model_validate(t) for t in templates]


@router.post(
    "/templates/clone/",
    response_model=KPIRead,
    status_code=status.HTTP_201_CREATED,
    summary="Clone a template into an organisation KPI",
    description="Creates a new KPI in the organisation based on a system template.",
)
async def clone_from_template(
    data: KPICloneFromTemplate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles("hr_admin", "manager"))],
) -> KPIRead:
    """Clone a KPI template into the current organisation."""
    kpi = await _service.clone_from_template(db, _org_id(current_user), current_user.id, data)
    return KPIRead.model_validate(kpi)


@router.post(
    "/validate-formula",
    response_model=FormulaValidationResponse,
    summary="Validate a formula expression",
    description=(
        "Validates a formula expression for syntax correctness and verifies that all "
        "referenced KPI codes exist within the organisation. Does not persist anything."
    ),
)
async def validate_formula(
    data: FormulaValidationRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> FormulaValidationResponse:
    """Validate a formula expression without creating a KPI."""
    return await _service.validate_formula_expression(db, _org_id(current_user), data.expression)


# ---------------------------------------------------------------------------
# KPI CRUD endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/",
    response_model=PaginatedKPIs,
    summary="List KPIs",
    description="Returns a paginated, filterable list of KPIs within the organisation.",
)
async def list_kpis(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    status: KPIStatus | None = Query(default=None),
    category_id: UUID | None = Query(default=None),
    department: DepartmentCategory | None = Query(default=None),
    data_source: DataSourceType | None = Query(default=None),
    tag_ids: list[UUID] | None = Query(default=None),
    search: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> PaginatedKPIs:
    """Paginated list of KPIs with optional filters."""
    return await _service.list_kpis(
        db,
        org_id=_org_id(current_user),
        page=page,
        size=size,
        status=status,
        category_id=category_id,
        department=department,
        data_source=data_source,
        tag_ids=tag_ids,
        search=search,
        created_by_id=None,
    )


@router.post(
    "/",
    response_model=KPIRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a KPI",
    description=(
        "Creates a new KPI definition in DRAFT status. If data_source is FORMULA, "
        "validates syntax and resolves all referenced KPI codes. Requires hr_admin or manager."
    ),
)
async def create_kpi(
    data: KPICreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles("hr_admin", "manager"))],
) -> KPIRead:
    """Create a new KPI definition."""
    kpi = await _service.create_kpi(db, _org_id(current_user), current_user.id, data)
    return KPIRead.model_validate(kpi)


@router.get(
    "/{kpi_id}",
    response_model=KPIReadWithDependencies,
    summary="Get a KPI",
    description="Returns a single KPI by ID, including its formula dependencies.",
)
async def get_kpi(
    kpi_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> KPIReadWithDependencies:
    """Retrieve a KPI by its ID."""
    kpi = await _service.get_kpi_by_id(db, kpi_id, _org_id(current_user))
    return KPIReadWithDependencies.model_validate(kpi)


@router.put(
    "/{kpi_id}",
    response_model=KPIRead,
    summary="Update a KPI definition",
    description=(
        "Updates a KPI's definition fields. Increments the version and saves a history snapshot. "
        "change_summary is required when modifying formula_expression."
    ),
)
async def update_kpi(
    kpi_id: UUID,
    data: KPIUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles("hr_admin", "manager"))],
) -> KPIRead:
    """Update a KPI definition."""
    kpi = await _service.update_kpi(db, kpi_id, _org_id(current_user), current_user.id, data)
    return KPIRead.model_validate(kpi)


@router.patch(
    "/{kpi_id}/status",
    response_model=KPIRead,
    summary="Update KPI status",
    description=(
        "Transitions a KPI through the approval workflow. "
        "Valid transitions: DRAFT→PENDING_APPROVAL, DRAFT→ACTIVE (hr_admin), "
        "PENDING_APPROVAL→ACTIVE (hr_admin), PENDING_APPROVAL→DRAFT, "
        "ACTIVE→DEPRECATED, DEPRECATED→ARCHIVED."
    ),
)
async def update_kpi_status(
    kpi_id: UUID,
    data: KPIStatusUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> KPIRead:
    """Update the workflow status of a KPI."""
    is_hr_admin = current_user.role == UserRole.hr_admin
    kpi = await _service.update_kpi_status(
        db, kpi_id, _org_id(current_user), current_user.id, data, is_hr_admin=is_hr_admin
    )
    return KPIRead.model_validate(kpi)


@router.get(
    "/{kpi_id}/history",
    response_model=list[KPIHistoryRead],
    summary="Get KPI version history",
    description="Returns the full audit trail of changes to a KPI definition.",
)
async def get_kpi_history(
    kpi_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> list[KPIHistoryRead]:
    """Retrieve the version history for a KPI."""
    history = await _service.get_kpi_history(db, kpi_id, _org_id(current_user))
    return [KPIHistoryRead.model_validate(h) for h in history]


@router.post(
    "/{kpi_id}/promote-template",
    response_model=KPIRead,
    summary="Promote KPI to organisation template",
    description="Marks a KPI as an organisation-level template (is_template=True). Requires hr_admin.",
)
async def promote_to_template(
    kpi_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles("hr_admin"))],
) -> KPIRead:
    """Promote a KPI to an organisation template."""
    kpi = await _service.promote_to_template(db, kpi_id, _org_id(current_user))
    return KPIRead.model_validate(kpi)
