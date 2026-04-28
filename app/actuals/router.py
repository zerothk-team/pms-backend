"""
Actuals router — all endpoints under /api/v1/actuals.

Prefix: /actuals
Tags:   Actuals
"""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.actuals.enums import ActualEntryStatus
from app.actuals.schemas import (
    ActualEvidenceCreate,
    ActualEvidenceRead,
    ActualTimeSeries,
    KPIActualBulkCreate,
    KPIActualCreate,
    KPIActualRead,
    KPIActualReview,
    KPIActualUpdate,
)
from app.actuals.service import ActualService
from app.database import get_db
from app.dependencies import get_current_active_user, require_roles
from app.exceptions import ForbiddenException
from app.users.models import User

router = APIRouter(prefix="/actuals", tags=["Actuals"])
_service = ActualService()


def _org_id(user: User) -> UUID:
    if not user.organisation_id:
        raise ForbiddenException("User is not associated with an organisation")
    return user.organisation_id


# ---------------------------------------------------------------------------
# Fixed paths (must come before /{actual_id} routes)
# ---------------------------------------------------------------------------


@router.get(
    "/pending-review",
    response_model=dict,
    summary="Pending approvals (manager view)",
    description=(
        "Returns PENDING_APPROVAL actuals submitted by the manager's direct reports. "
        "hr_admin / executive see all pending actuals in the organisation."
    ),
)
async def pending_review(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict:
    result = await _service.get_pending_approvals_for_manager(
        db, current_user, _org_id(current_user), page=page, size=size
    )
    result["items"] = [KPIActualRead.model_validate(a) for a in result["items"]]
    return result


@router.get(
    "/time-series/{target_id}",
    response_model=ActualTimeSeries,
    summary="Time series data for a target",
    description=(
        "Returns the full time series from cycle start to today, with "
        "achievement percentages and milestone comparisons. "
        "Missing periods are represented with actual_value=null."
    ),
)
async def get_time_series(
    target_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> ActualTimeSeries:
    return await _service.get_time_series(db, target_id, _org_id(current_user))


# ---------------------------------------------------------------------------
# List / search
# ---------------------------------------------------------------------------


@router.get(
    "/",
    response_model=dict,
    summary="List actuals",
    description=(
        "Returns a paginated list of actuals for the organisation. "
        "Filter by target, KPI, status, or date range."
    ),
)
async def list_actuals(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    target_id: UUID | None = Query(default=None),
    kpi_id: UUID | None = Query(default=None),
    status: ActualEntryStatus | None = Query(default=None),
    period_start: date | None = Query(default=None),
    period_end: date | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict:
    result = await _service.list_actuals(
        db,
        _org_id(current_user),
        target_id=target_id,
        kpi_id=kpi_id,
        status=status,
        period_start=period_start,
        period_end=period_end,
        page=page,
        size=size,
    )
    result["items"] = [KPIActualRead.model_validate(a) for a in result["items"]]
    return result


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------


@router.post(
    "/",
    response_model=KPIActualRead,
    status_code=status.HTTP_201_CREATED,
    summary="Submit an actual value",
    description=(
        "Submit a KPI actual value for a measurement period. "
        "If a previous value exists for the same period, it is superseded "
        "(full history preserved). The target must be LOCKED (cycle is ACTIVE)."
    ),
)
async def submit_actual(
    data: KPIActualCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> KPIActualRead:
    actual = await _service.submit_actual(db, _org_id(current_user), current_user, data)
    return KPIActualRead.model_validate(actual)


@router.post(
    "/bulk",
    response_model=list[KPIActualRead],
    status_code=status.HTTP_201_CREATED,
    summary="Bulk submit actuals",
    description=(
        "Submit up to 50 actuals for different periods in one request. "
        "Useful for catch-up entry after a gap in submissions."
    ),
)
async def bulk_submit_actuals(
    data: KPIActualBulkCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> list[KPIActualRead]:
    actuals = await _service.submit_bulk_actuals(
        db, _org_id(current_user), current_user, data
    )
    return [KPIActualRead.model_validate(a) for a in actuals]


@router.post(
    "/compute-formulas",
    response_model=dict,
    summary="Trigger formula recalculation",
    description=(
        "Evaluate formula-based KPIs for a given review cycle and period date. "
        "Inserts AUTO_FORMULA actuals for all qualifying targets. "
        "Requires hr_admin role."
    ),
)
async def compute_formulas(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles("hr_admin"))],
    cycle_id: UUID = Query(...),
    period_date: date = Query(...),
) -> dict:
    actuals = await _service.compute_formula_actuals(
        db, cycle_id, _org_id(current_user), period_date
    )
    return {"computed": len(actuals), "period_date": str(period_date)}


# ---------------------------------------------------------------------------
# Single actual CRUD
# ---------------------------------------------------------------------------


@router.get(
    "/{actual_id}",
    response_model=KPIActualRead,
    summary="Get an actual",
    description="Returns a single actual by ID.",
)
async def get_actual(
    actual_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> KPIActualRead:
    actual = await _service.get_actual_by_id(db, actual_id, _org_id(current_user))
    return KPIActualRead.model_validate(actual)


@router.put(
    "/{actual_id}",
    response_model=KPIActualRead,
    summary="Edit a pending actual",
    description=(
        "Edit an actual value that is still in PENDING_APPROVAL status. "
        "Only the original submitter may edit (or hr_admin)."
    ),
)
async def update_actual(
    actual_id: UUID,
    data: KPIActualUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> KPIActualRead:
    actual = await _service.update_actual(
        db, actual_id, _org_id(current_user), current_user, data
    )
    return KPIActualRead.model_validate(actual)


@router.patch(
    "/{actual_id}/review",
    response_model=KPIActualRead,
    summary="Approve or reject an actual",
    description=(
        "Manager approves or rejects a PENDING_APPROVAL actual. "
        "Rejection requires a reason. Requires manager, hr_admin, or executive role."
    ),
)
async def review_actual(
    actual_id: UUID,
    data: KPIActualReview,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> KPIActualRead:
    actual = await _service.review_actual(
        db, actual_id, _org_id(current_user), current_user, data
    )
    return KPIActualRead.model_validate(actual)


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


@router.post(
    "/{actual_id}/evidence",
    response_model=ActualEvidenceRead,
    status_code=status.HTTP_201_CREATED,
    summary="Attach evidence to an actual",
    description=(
        "Upload an evidence reference (file metadata + URL) to an actual submission. "
        "Actual file storage is handled externally (e.g. S3). "
        "This endpoint stores the metadata and URL only."
    ),
)
async def add_evidence(
    actual_id: UUID,
    data: ActualEvidenceCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> ActualEvidenceRead:
    evidence = await _service.add_evidence(
        db,
        actual_id,
        _org_id(current_user),
        current_user,
        data.file_name,
        data.file_url,
        data.file_type,
    )
    return ActualEvidenceRead.model_validate(evidence)


@router.delete(
    "/{actual_id}/evidence/{evidence_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove evidence attachment",
    description="Delete an evidence attachment. Only the uploader or hr_admin may delete.",
)
async def delete_evidence(
    actual_id: UUID,
    evidence_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> None:
    await _service.delete_evidence(
        db, evidence_id, _org_id(current_user), current_user
    )


# ---------------------------------------------------------------------------
# Variable actuals endpoints
# ---------------------------------------------------------------------------

from app.integrations.data_sync_service import DataSyncService
from app.integrations.models import KPIVariable, VariableActual as _VarActual
from app.integrations.schemas import (
    BulkManualEntry,
    BulkSyncResult,
    ManualVariableEntry,
    VariableActualRead,
)

_sync_service = DataSyncService()


@router.post(
    "/variables/",
    response_model=list[VariableActualRead],
    status_code=status.HTTP_201_CREATED,
    summary="Submit manual variable value(s)",
    description="Store one or more manual variable values for a given period.",
)
async def submit_manual_variable_values(
    payload: BulkManualEntry,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> list[VariableActualRead]:
    from datetime import datetime, timezone
    from sqlalchemy import select, update as sa_update
    from app.exceptions import NotFoundException
    from app.integrations.enums import VariableSourceType

    org_id = _org_id(current_user)
    results = []

    for entry in payload.entries:
        # Verify variable belongs to this org
        var_result = await db.execute(
            select(KPIVariable).where(
                KPIVariable.id == entry.variable_id,
                KPIVariable.kpi_id == entry.kpi_id,
                KPIVariable.organisation_id == org_id,
            )
        )
        variable = var_result.scalar_one_or_none()
        if variable is None:
            raise NotFoundException(f"KPI variable {entry.variable_id} not found")

        # Supersede previous current value for this period
        await db.execute(
            sa_update(_VarActual)
            .where(
                _VarActual.variable_id == entry.variable_id,
                _VarActual.period_date == entry.period_date,
                _VarActual.is_current.is_(True),
            )
            .values(is_current=False)
        )

        actual = _VarActual(
            variable_id=entry.variable_id,
            kpi_id=entry.kpi_id,
            period_date=entry.period_date,
            raw_value=entry.raw_value,
            source_type=VariableSourceType.MANUAL,
            sync_metadata={"source_type": "manual", "synced_at": datetime.now(timezone.utc).isoformat()},
            submitted_by_id=current_user.id,
            is_current=True,
        )
        db.add(actual)
        await db.flush()
        await db.refresh(actual)
        results.append(actual)

    await db.commit()
    return [VariableActualRead.model_validate(a) for a in results]


@router.get(
    "/variables/{kpi_id}/{period}",
    response_model=list[VariableActualRead],
    summary="Get all variable values for a KPI and period",
    description="Returns all current variable actuals for a KPI for the given period (YYYY-MM-DD).",
)
async def get_variable_actuals_for_period(
    kpi_id: UUID,
    period: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> list[VariableActualRead]:
    from datetime import date as _date
    from sqlalchemy import select

    try:
        period_date = _date.fromisoformat(period)
    except ValueError:
        from app.exceptions import ValidationException
        raise ValidationException(f"Invalid period format: {period!r}. Use YYYY-MM-DD.")

    result = await db.execute(
        select(_VarActual).where(
            _VarActual.kpi_id == kpi_id,
            _VarActual.period_date == period_date,
            _VarActual.is_current.is_(True),
        )
    )
    return [VariableActualRead.model_validate(a) for a in result.scalars().all()]


@router.post(
    "/variables/bulk-sync/{kpi_id}",
    response_model=BulkSyncResult,
    summary="Trigger auto-sync for all non-manual variables of a KPI",
    description="Fetches fresh values from all external sources. Requires hr_admin.",
)
async def bulk_sync_variables(
    kpi_id: UUID,
    period_date: Annotated[str, Query(description="Period in YYYY-MM-DD format")],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles("hr_admin"))],
) -> BulkSyncResult:
    from datetime import date as _date
    from sqlalchemy import select
    from app.integrations.enums import VariableSourceType as _VST

    try:
        parsed_date = _date.fromisoformat(period_date)
    except ValueError:
        from app.exceptions import ValidationException
        raise ValidationException(f"Invalid period_date: {period_date!r}. Use YYYY-MM-DD.")

    variables_result = await db.execute(
        select(KPIVariable).where(KPIVariable.kpi_id == kpi_id)
    )
    all_variables = list(variables_result.scalars().all())

    skip_types = {_VST.MANUAL, _VST.WEBHOOK_RECEIVE}
    results: dict[str, str] = {}
    synced = 0
    failed = 0

    for var in all_variables:
        if var.source_type in skip_types:
            results[var.variable_name] = "skipped"
            continue
        if not var.auto_sync_enabled:
            results[var.variable_name] = "skipped (auto_sync disabled)"
            continue
        try:
            await _sync_service.sync_variable(db, var, parsed_date)
            results[var.variable_name] = "synced"
            synced += 1
        except Exception as exc:
            results[var.variable_name] = f"failed: {exc}"
            failed += 1

    return BulkSyncResult(
        kpi_id=kpi_id,
        period_date=parsed_date,
        synced_count=synced,
        failed_count=failed,
        results=results,
    )

