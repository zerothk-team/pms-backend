"""
KPI Scoring Config router — endpoints under /api/v1/scoring/configs,
plus PATCH endpoints for assigning configs to KPIs and targets.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_active_user, require_roles
from app.exceptions import ForbiddenException
from app.scoring.kpi_scoring_schemas import (
    AssignScoringConfigRequest,
    EffectiveScoringConfigRead,
    FromPresetRequest,
    KPIScoringConfigCreate,
    KPIScoringConfigRead,
    KPIScoringConfigUpdate,
    ScoringPreviewResult,
)
from app.scoring.kpi_scoring_service import KPIScoringConfigService
from app.users.models import User, UserRole

router = APIRouter(tags=["KPI Scoring Configs"])
_svc = KPIScoringConfigService()


def _org_id(user: User) -> UUID:
    if not user.organisation_id:
        raise ForbiddenException("User is not associated with an organisation.")
    return user.organisation_id


# ---------------------------------------------------------------------------
# Config CRUD
# ---------------------------------------------------------------------------


@router.get(
    "/scoring/configs",
    response_model=list[KPIScoringConfigRead],
    summary="List scoring configs (org + system presets)",
)
async def list_scoring_configs(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> list[KPIScoringConfigRead]:
    configs = await _svc.list_for_org(db, _org_id(current_user))
    return [KPIScoringConfigRead.model_validate(c) for c in configs]


@router.post(
    "/scoring/configs",
    response_model=KPIScoringConfigRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a custom scoring config",
    dependencies=[Depends(require_roles(UserRole.hr_admin))],
)
async def create_scoring_config(
    data: KPIScoringConfigCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> KPIScoringConfigRead:
    config = await _svc.create(db, _org_id(current_user), current_user.id, data)
    await db.commit()
    return KPIScoringConfigRead.model_validate(config)


@router.post(
    "/scoring/configs/from-preset",
    response_model=KPIScoringConfigRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a scoring config from a named preset",
    dependencies=[Depends(require_roles(UserRole.hr_admin))],
)
async def create_scoring_config_from_preset(
    data: FromPresetRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> KPIScoringConfigRead:
    create_data = KPIScoringConfigCreate.from_preset(data.preset, data.name)
    create_data.description = data.description
    create_data.preset = data.preset
    config = await _svc.create(db, _org_id(current_user), current_user.id, create_data)
    await db.commit()
    return KPIScoringConfigRead.model_validate(config)


@router.get(
    "/scoring/configs/{config_id}",
    response_model=KPIScoringConfigRead,
    summary="Get a single scoring config",
)
async def get_scoring_config(
    config_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> KPIScoringConfigRead:
    config = await _svc.get(db, config_id, _org_id(current_user))
    return KPIScoringConfigRead.model_validate(config)


@router.put(
    "/scoring/configs/{config_id}",
    response_model=KPIScoringConfigRead,
    summary="Update a custom scoring config",
    dependencies=[Depends(require_roles(UserRole.hr_admin))],
)
async def update_scoring_config(
    config_id: UUID,
    data: KPIScoringConfigUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> KPIScoringConfigRead:
    config = await _svc.update(db, config_id, _org_id(current_user), data)
    await db.commit()
    return KPIScoringConfigRead.model_validate(config)


@router.delete(
    "/scoring/configs/{config_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a custom scoring config (only if not in use)",
    dependencies=[Depends(require_roles(UserRole.hr_admin))],
)
async def delete_scoring_config(
    config_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> None:
    await _svc.delete(db, config_id, _org_id(current_user))
    await db.commit()


@router.get(
    "/scoring/configs/{config_id}/preview",
    response_model=list[ScoringPreviewResult],
    summary="Preview what ratings a set of achievement % values produce",
)
async def preview_scoring_config(
    config_id: UUID,
    test_values: Annotated[list[float], Query(description="Achievement % values to preview ratings for")],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> list[ScoringPreviewResult]:
    return await _svc.preview_scoring(
        db, config_id, _org_id(current_user), test_values
    )


# ---------------------------------------------------------------------------
# Assign scoring config to KPI / Target
# ---------------------------------------------------------------------------


@router.patch(
    "/kpis/{kpi_id}/scoring-config",
    response_model=dict,
    summary="Assign (or remove) a scoring config to a KPI definition",
    dependencies=[Depends(require_roles(UserRole.hr_admin))],
)
async def assign_config_to_kpi(
    kpi_id: UUID,
    data: AssignScoringConfigRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict:
    kpi = await _svc.assign_to_kpi(
        db, kpi_id, _org_id(current_user), data.scoring_config_id
    )
    await db.commit()
    return {
        "kpi_id": str(kpi.id),
        "scoring_config_id": str(kpi.scoring_config_id) if kpi.scoring_config_id else None,
    }


@router.patch(
    "/targets/{target_id}/scoring-config",
    response_model=dict,
    summary="Assign (or remove) a scoring config to a specific target",
    dependencies=[Depends(require_roles(UserRole.hr_admin, UserRole.manager))],
)
async def assign_config_to_target(
    target_id: UUID,
    data: AssignScoringConfigRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict:
    target = await _svc.assign_to_target(
        db, target_id, _org_id(current_user), data.scoring_config_id
    )
    await db.commit()
    return {
        "target_id": str(target.id),
        "scoring_config_id": str(target.scoring_config_id) if target.scoring_config_id else None,
    }


@router.get(
    "/targets/{target_id}/scoring-config",
    response_model=dict,
    summary="Get the effective scoring config (and its source) for a target",
)
async def get_effective_config_for_target(
    target_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict:
    return await _svc.get_effective_config_for_target(
        db, target_id, _org_id(current_user)
    )
