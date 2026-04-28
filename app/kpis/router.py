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


# ---------------------------------------------------------------------------
# KPI Variable management endpoints
# ---------------------------------------------------------------------------

from app.integrations.data_sync_service import DataSyncService
from app.integrations.models import KPIVariable
from app.integrations.schemas import (
    FormulaValidationRequest as IntegFormulaValidationRequest,
    FormulaValidationResponse as IntegFormulaValidationResponse,
    KPIVariableCreate,
    KPIVariableRead,
    KPIVariableReorder,
    KPIVariableUpdate,
    VariableActualRead,
)

_sync_service = DataSyncService()


@router.get(
    "/{kpi_id}/variables/",
    response_model=list[KPIVariableRead],
    summary="List variables for a KPI",
    description="Returns all KPIVariable definitions for the given KPI.",
)
async def list_kpi_variables(
    kpi_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> list[KPIVariableRead]:
    from sqlalchemy import select
    from app.integrations.models import KPIVariable as _KPIVar
    result = await db.execute(
        select(_KPIVar)
        .where(_KPIVar.kpi_id == kpi_id, _KPIVar.organisation_id == _org_id(current_user))
        .order_by(_KPIVar.display_order)
    )
    return [KPIVariableRead.model_validate(v) for v in result.scalars().all()]


@router.post(
    "/{kpi_id}/variables/",
    response_model=KPIVariableRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a KPI variable",
    description="Adds a new named variable to a formula KPI. Requires hr_admin or manager.",
)
async def create_kpi_variable(
    kpi_id: UUID,
    payload: KPIVariableCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles("hr_admin", "manager"))],
) -> KPIVariableRead:
    from sqlalchemy import select
    from app.exceptions import ConflictException, NotFoundException
    from app.kpis.models import KPI
    from app.integrations.models import KPIVariable as _KPIVar

    kpi_result = await db.execute(
        select(KPI).where(KPI.id == kpi_id, KPI.organisation_id == _org_id(current_user))
    )
    kpi = kpi_result.scalar_one_or_none()
    if kpi is None:
        raise NotFoundException("KPI not found")

    # Check name uniqueness
    existing = await db.execute(
        select(_KPIVar).where(_KPIVar.kpi_id == kpi_id, _KPIVar.variable_name == payload.variable_name)
    )
    if existing.scalar_one_or_none():
        raise ConflictException(
            f"Variable '{payload.variable_name}' already exists for this KPI"
        )

    # Validate adapter config if non-manual
    if payload.source_config and payload.source_type.value not in ("manual", "webhook_receive", "formula"):
        from app.integrations.adapter_registry import AdapterRegistry
        try:
            adapter = AdapterRegistry.get(payload.source_config.get("adapter", payload.source_type.value))
            errors = adapter.validate_config(payload.source_config)
            if errors:
                from app.exceptions import ValidationException
                raise ValidationException("; ".join(errors))
        except KeyError:
            pass  # unknown adapter name — will fail at sync time

    variable = _KPIVar(
        kpi_id=kpi_id,
        organisation_id=_org_id(current_user),
        created_by_id=current_user.id,
        **payload.model_dump(),
    )
    db.add(variable)
    await db.flush()
    await db.refresh(variable)
    await db.commit()
    return KPIVariableRead.model_validate(variable)


@router.get(
    "/{kpi_id}/variables/{var_id}",
    response_model=KPIVariableRead,
    summary="Get a KPI variable",
)
async def get_kpi_variable(
    kpi_id: UUID,
    var_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> KPIVariableRead:
    from sqlalchemy import select
    from app.exceptions import NotFoundException
    from app.integrations.models import KPIVariable as _KPIVar

    result = await db.execute(
        select(_KPIVar).where(
            _KPIVar.id == var_id,
            _KPIVar.kpi_id == kpi_id,
            _KPIVar.organisation_id == _org_id(current_user),
        )
    )
    variable = result.scalar_one_or_none()
    if variable is None:
        raise NotFoundException("KPI variable not found")
    return KPIVariableRead.model_validate(variable)


@router.put(
    "/{kpi_id}/variables/{var_id}",
    response_model=KPIVariableRead,
    summary="Update a KPI variable",
    description="Update variable configuration. Requires hr_admin or manager.",
)
async def update_kpi_variable(
    kpi_id: UUID,
    var_id: UUID,
    payload: KPIVariableUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles("hr_admin", "manager"))],
) -> KPIVariableRead:
    from sqlalchemy import select
    from app.exceptions import NotFoundException
    from app.integrations.models import KPIVariable as _KPIVar

    result = await db.execute(
        select(_KPIVar).where(
            _KPIVar.id == var_id,
            _KPIVar.kpi_id == kpi_id,
            _KPIVar.organisation_id == _org_id(current_user),
        )
    )
    variable = result.scalar_one_or_none()
    if variable is None:
        raise NotFoundException("KPI variable not found")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(variable, field, value)

    await db.flush()
    await db.refresh(variable)
    await db.commit()
    return KPIVariableRead.model_validate(variable)


@router.delete(
    "/{kpi_id}/variables/{var_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a KPI variable",
    description="Delete a variable definition. Requires hr_admin.",
)
async def delete_kpi_variable(
    kpi_id: UUID,
    var_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles("hr_admin"))],
) -> None:
    from sqlalchemy import select
    from app.exceptions import NotFoundException
    from app.integrations.models import KPIVariable as _KPIVar

    result = await db.execute(
        select(_KPIVar).where(
            _KPIVar.id == var_id,
            _KPIVar.kpi_id == kpi_id,
            _KPIVar.organisation_id == _org_id(current_user),
        )
    )
    variable = result.scalar_one_or_none()
    if variable is None:
        raise NotFoundException("KPI variable not found")

    await db.delete(variable)
    await db.commit()


@router.patch(
    "/{kpi_id}/variables/reorder",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Reorder KPI variables",
    description="Update display_order for all variables of a KPI. Requires hr_admin or manager.",
)
async def reorder_kpi_variables(
    kpi_id: UUID,
    payload: KPIVariableReorder,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles("hr_admin", "manager"))],
) -> None:
    from sqlalchemy import select, update as sa_update
    from app.integrations.models import KPIVariable as _KPIVar

    for item in payload.variable_orders:
        var_id = item.get("id")
        new_order = item.get("order", 0)
        await db.execute(
            sa_update(_KPIVar)
            .where(_KPIVar.id == var_id, _KPIVar.kpi_id == kpi_id)
            .values(display_order=new_order)
        )
    await db.commit()


@router.post(
    "/{kpi_id}/variables/{var_id}/test-sync",
    response_model=VariableActualRead,
    summary="Test-sync a variable",
    description="Trigger a one-off sync of a variable from its configured source. Requires hr_admin.",
)
async def test_sync_variable(
    kpi_id: UUID,
    var_id: UUID,
    period_date: Annotated[str, Query(description="Period in YYYY-MM-DD format")],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles("hr_admin"))],
) -> VariableActualRead:
    from datetime import date
    from sqlalchemy import select
    from app.exceptions import NotFoundException
    from app.integrations.models import KPIVariable as _KPIVar

    result = await db.execute(
        select(_KPIVar).where(
            _KPIVar.id == var_id,
            _KPIVar.kpi_id == kpi_id,
            _KPIVar.organisation_id == _org_id(current_user),
        )
    )
    variable = result.scalar_one_or_none()
    if variable is None:
        raise NotFoundException("KPI variable not found")

    parsed_date = date.fromisoformat(period_date)
    actual = await _sync_service.sync_variable(db, variable, parsed_date)
    return VariableActualRead.model_validate(actual)


@router.post(
    "/{kpi_id}/variables/validate-formula",
    response_model=IntegFormulaValidationResponse,
    summary="Validate formula expression against defined variables",
)
async def validate_formula_expression(
    kpi_id: UUID,
    payload: IntegFormulaValidationRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> IntegFormulaValidationResponse:
    result = await _sync_service.validate_formula_with_variables(
        db, kpi_id, payload.expression
    )
    return IntegFormulaValidationResponse(**result)

