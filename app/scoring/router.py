"""
Scoring router — all endpoints under /api/v1/scoring.

Prefix: /scoring
Tags:   Scoring
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_active_user, require_roles
from app.exceptions import ForbiddenException
from app.scoring.schemas import (
    CalibrationScoreUpdate,
    CalibrationSessionCreate,
    CalibrationSessionDetail,
    CalibrationSessionRead,
    CompositeAdjustRequest,
    CompositeScoreDetail,
    CompositeScoreRead,
    ScoreAdjustRequest,
    ScoreConfigCreate,
    ScoreConfigRead,
    ScoreConfigUpdate,
    ScoringRunResult,
)
from app.scoring.service import CalibrationService, ScoreConfigService, ScoringEngine
from app.users.models import User, UserRole

router = APIRouter(prefix="/scoring", tags=["Scoring"])
_engine = ScoringEngine()
_calibration = CalibrationService()
_config_service = ScoreConfigService()


def _org_id(user: User) -> UUID:
    if not user.organisation_id:
        raise ForbiddenException("User is not associated with an organisation.")
    return user.organisation_id


def _can_view_scores(current_user: User, target_user_id: UUID) -> None:
    """Employees can only view their own scores unless they are a manager/admin."""
    if current_user.role in {UserRole.hr_admin, UserRole.executive}:
        return
    if current_user.id == target_user_id:
        return
    if current_user.role == UserRole.manager:
        return  # Manager access is further checked in service layer
    raise ForbiddenException(
        "You do not have permission to view this employee's scores."
    )


# ---------------------------------------------------------------------------
# Score Config
# ---------------------------------------------------------------------------


@router.get(
    "/config",
    response_model=ScoreConfigRead,
    summary="Get score config for a cycle",
    description=(
        "Retrieve the scoring threshold configuration for a specific review cycle. "
        "If no config has been created, a 404 is returned — use POST to create one."
    ),
)
async def get_score_config(
    cycle_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> ScoreConfigRead:
    """Get scoring configuration for the given review cycle."""
    config = await _config_service.get_for_cycle(db, _org_id(current_user), cycle_id)
    return ScoreConfigRead.model_validate(config)


@router.post(
    "/config",
    response_model=ScoreConfigRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create score config",
    description=(
        "Create the scoring threshold configuration for a review cycle. "
        "Only one config is allowed per cycle. HR admins only."
    ),
)
async def create_score_config(
    data: ScoreConfigCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles("hr_admin"))],
) -> ScoreConfigRead:
    """Create scoring configuration. Thresholds must be in strictly descending order."""
    config = await _config_service.create(db, _org_id(current_user), data)
    await db.commit()
    return ScoreConfigRead.model_validate(config)


@router.put(
    "/config/{config_id}",
    response_model=ScoreConfigRead,
    summary="Update score config",
    description=(
        "Update scoring thresholds for an existing configuration. "
        "Changes take effect on the next scoring run. HR admins only."
    ),
)
async def update_score_config(
    config_id: UUID,
    data: ScoreConfigUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles("hr_admin"))],
) -> ScoreConfigRead:
    """Update score config thresholds. All fields are optional."""
    config = await _config_service.update(db, config_id, _org_id(current_user), data)
    await db.commit()
    return ScoreConfigRead.model_validate(config)


# ---------------------------------------------------------------------------
# Scoring Engine
# ---------------------------------------------------------------------------


@router.post(
    "/compute/{cycle_id}",
    response_model=ScoringRunResult,
    status_code=status.HTTP_200_OK,
    summary="Run scoring engine for a cycle",
    description=(
        "Triggers the scoring engine for the given review cycle. "
        "Computes achievement percentages, weighted scores, and composite scores "
        "for all employees with locked targets. "
        "Re-running is safe — existing scores are updated in place. "
        "HR admins only."
    ),
)
async def compute_scores(
    cycle_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles("hr_admin"))],
    user_ids: list[UUID] | None = Query(default=None, description="Limit to specific user IDs"),
) -> ScoringRunResult:
    """Run or re-run the scoring engine for the entire cycle (or a specific subset of users)."""
    composites = await _engine.compute_scores_for_cycle(
        db, cycle_id, _org_id(current_user), user_ids=user_ids
    )
    await db.commit()
    return ScoringRunResult(
        cycle_id=cycle_id,
        users_scored=len(composites),
        composite_scores=[CompositeScoreRead.model_validate(c) for c in composites],
    )


@router.post(
    "/recompute/{user_id}/{cycle_id}",
    response_model=CompositeScoreRead,
    summary="Recompute scores for a single user",
    description=(
        "Recompute all KPI and composite scores for a single employee. "
        "Useful after correcting an actual or adjusting a target. "
        "Existing manual adjustments are preserved. "
        "HR admins and the employee's manager can trigger this."
    ),
)
async def recompute_user_score(
    user_id: UUID,
    cycle_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CompositeScoreRead:
    """Recompute scores for one user in one cycle."""
    if current_user.role not in {UserRole.hr_admin, UserRole.manager}:
        raise ForbiddenException("Only HR admins and managers can trigger score recomputation.")
    composite = await _engine.recompute_score_for_user(
        db, user_id, cycle_id, _org_id(current_user)
    )
    await db.commit()
    return CompositeScoreRead.model_validate(composite)


@router.get(
    "/users/{user_id}/{cycle_id}",
    response_model=CompositeScoreDetail,
    summary="Get full score breakdown for a user",
    description=(
        "Returns the composite score, individual KPI scores, and full adjustment "
        "history for a given employee in a given cycle. "
        "Employees can only view their own scores. "
        "Managers can view their direct reports. "
        "HR admins and executives can view any employee."
    ),
)
async def get_user_score(
    user_id: UUID,
    cycle_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CompositeScoreDetail:
    """Full KPI + composite score breakdown for one employee."""
    _can_view_scores(current_user, user_id)
    org_id = _org_id(current_user)
    data = await _engine.get_score_for_user(db, user_id, cycle_id, org_id)

    from app.scoring.schemas import PerformanceScoreDetail, ScoreAdjustmentRead

    kpi_scores_detail = []
    for score in data["kpi_scores"]:
        detail = PerformanceScoreDetail.model_validate(score)
        if score.kpi:
            detail.kpi_name = score.kpi.name
            detail.kpi_code = score.kpi.code
        if score.target:
            detail.target_value = score.target.target_value
            detail.weight = score.target.weight
        detail.adjustments = [ScoreAdjustmentRead.model_validate(a) for a in score.adjustments]
        kpi_scores_detail.append(detail)

    composite = data["composite"]
    if not composite:
        from app.exceptions import NotFoundException

        raise NotFoundException(
            f"No scores found for user '{user_id}' in cycle '{cycle_id}'. "
            "Run scoring first with POST /scoring/compute/{cycle_id}."
        )

    result = CompositeScoreDetail(
        **CompositeScoreRead.model_validate(composite).model_dump(),
        kpi_scores=kpi_scores_detail,
        adjustment_history=[
            ScoreAdjustmentRead.model_validate(a) for a in data["adjustment_history"]
        ],
    )
    return result


@router.get(
    "/team/{cycle_id}",
    response_model=list[CompositeScoreRead],
    summary="Get team scores (manager view)",
    description=(
        "Returns composite scores for all direct reports of the requesting manager. "
        "HR admins see all users; managers see their own team only."
    ),
)
async def get_team_scores(
    cycle_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> list[CompositeScoreRead]:
    """List composite scores for the manager's direct reports."""
    if current_user.role not in {UserRole.hr_admin, UserRole.manager, UserRole.executive}:
        raise ForbiddenException("Only managers, executives, and HR admins can access team scores.")
    team_data = await _engine.get_team_scores(
        db, current_user.id, cycle_id, _org_id(current_user)
    )
    return [
        CompositeScoreRead.model_validate(d["composite"])
        for d in team_data
        if d.get("composite")
    ]


@router.get(
    "/org/{cycle_id}",
    response_model=dict,
    summary="Organisation score distribution",
    description=(
        "Returns statistical distribution of composite scores for the entire organisation "
        "in one cycle. Includes mean, median, std dev, percentiles, and rating breakdown. "
        "Executives and HR admins only."
    ),
)
async def get_org_distribution(
    cycle_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles("hr_admin", "executive"))],
    department: str | None = Query(default=None),
) -> dict:
    """Score distribution for the whole organisation, used for executive dashboards."""
    return await _engine.get_org_distribution(
        db, cycle_id, _org_id(current_user), department=department
    )


@router.patch(
    "/kpi-score/{score_id}/adjust",
    response_model=CompositeScoreRead,
    summary="Adjust a KPI score (manager)",
    description=(
        "Manager applies a qualitative adjustment to an individual KPI score. "
        "The adjustment must not exceed max_adjustment_points from the ScoreConfig. "
        "A mandatory reason must be provided. "
        "The composite score is automatically recomputed after adjustment. "
        "Scores with status=FINAL cannot be adjusted."
    ),
)
async def adjust_kpi_score(
    score_id: UUID,
    data: ScoreAdjustRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CompositeScoreRead:
    """Apply a manager adjustment to a single KPI score."""
    if current_user.role not in {UserRole.hr_admin, UserRole.manager}:
        raise ForbiddenException("Only managers and HR admins can adjust KPI scores.")

    score = await _engine.apply_manager_adjustment(
        db, score_id, current_user.id, _org_id(current_user), data
    )
    # Return updated composite
    composite = await _engine.get_score_for_user(
        db, score.user_id, score.review_cycle_id, _org_id(current_user)
    )
    await db.commit()
    from app.exceptions import NotFoundException

    if not composite.get("composite"):
        raise NotFoundException("Composite score not found after adjustment.")
    return CompositeScoreRead.model_validate(composite["composite"])


@router.patch(
    "/composite/{composite_id}/adjust",
    response_model=CompositeScoreRead,
    summary="Directly adjust a composite score",
    description=(
        "Directly adjust an employee's overall (composite) score. "
        "Used by HR admins for exceptional cases not covered by KPI-level adjustments. "
        "Subject to the same max_adjustment_points cap as KPI adjustments."
    ),
)
async def adjust_composite_score(
    composite_id: UUID,
    data: CompositeAdjustRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles("hr_admin", "manager"))],
) -> CompositeScoreRead:
    """Direct adjustment to a composite score (creates an audit record)."""
    composite = await _engine.apply_composite_adjustment(
        db, composite_id, current_user.id, _org_id(current_user), data
    )
    await db.commit()
    return CompositeScoreRead.model_validate(composite)


@router.post(
    "/finalise/{cycle_id}",
    response_model=dict,
    summary="Finalise (lock) all scores for a cycle",
    description=(
        "Locks all composite and KPI scores for the cycle. "
        "After this, no further adjustments are possible. "
        "If ScoreConfig.requires_calibration=True, at least one calibration session "
        "must be COMPLETED before this endpoint succeeds. "
        "HR admins only."
    ),
)
async def finalise_scores(
    cycle_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles("hr_admin"))],
) -> dict:
    """Lock all scores for the cycle. This action is irreversible."""
    count = await _engine.finalise_scores(db, cycle_id, _org_id(current_user))
    await db.commit()
    return {
        "message": f"Successfully finalised {count} composite scores.",
        "scores_finalised": count,
        "cycle_id": str(cycle_id),
    }


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------


@router.post(
    "/calibration",
    response_model=CalibrationSessionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a calibration session",
    description=(
        "Create a calibration session for a group of employees. "
        "Scoring must have already run for all specified users. "
        "HR admins only."
    ),
)
async def create_calibration_session(
    data: CalibrationSessionCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles("hr_admin"))],
) -> CalibrationSessionRead:
    """Create a new calibration session."""
    session = await _calibration.create_session(
        db, _org_id(current_user), current_user.id, data
    )
    await db.commit()
    return CalibrationSessionRead.model_validate(session)


@router.get(
    "/calibration",
    response_model=list[CalibrationSessionRead],
    summary="List calibration sessions",
    description=(
        "List all calibration sessions for a given review cycle. "
        "HR admins only."
    ),
)
async def list_calibration_sessions(
    cycle_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles("hr_admin"))],
) -> list[CalibrationSessionRead]:
    """List all calibration sessions for the given cycle."""
    sessions = await _calibration.list_sessions(db, cycle_id, _org_id(current_user))
    return [CalibrationSessionRead.model_validate(s) for s in sessions]


@router.get(
    "/calibration/{session_id}",
    response_model=CalibrationSessionDetail,
    summary="Get calibration session with scores",
    description=(
        "Retrieve a calibration session including all composite scores for in-scope "
        "employees, sorted by score descending. Includes distribution statistics. "
        "HR admins only."
    ),
)
async def get_calibration_session(
    session_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles("hr_admin"))],
) -> CalibrationSessionDetail:
    """Full calibration session data with scores and distribution."""
    data = await _calibration.get_session_data(db, session_id, _org_id(current_user))
    result = CalibrationSessionDetail.model_validate(data["session"])
    result.composite_scores = [
        CompositeScoreRead.model_validate(c) for c in data["composite_scores"]
    ]
    result.distribution = data["distribution"]
    return result


@router.patch(
    "/calibration/{session_id}/scores/{composite_id}",
    response_model=CompositeScoreRead,
    summary="Adjust a score within a calibration session",
    description=(
        "Adjust a composite score during an open calibration session. "
        "No cap restriction applies — facilitators have full authority. "
        "Records a ScoreAdjustment with type='calibration'. "
        "Session must be OPEN or IN_PROGRESS."
    ),
)
async def adjust_score_in_calibration(
    session_id: UUID,
    composite_id: UUID,
    data: CalibrationScoreUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles("hr_admin"))],
) -> CompositeScoreRead:
    """Apply a calibration adjustment to a composite score."""
    composite = await _calibration.update_score_in_session(
        db, session_id, composite_id, _org_id(current_user), current_user.id, data
    )
    await db.commit()
    return CompositeScoreRead.model_validate(composite)


@router.post(
    "/calibration/{session_id}/complete",
    response_model=CalibrationSessionRead,
    summary="Complete a calibration session",
    description=(
        "Mark the calibration session as COMPLETED. "
        "Any in-scope composites that were not adjusted are moved to MANAGER_REVIEWED. "
        "After completion, no further adjustments can be made in this session."
    ),
)
async def complete_calibration_session(
    session_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles("hr_admin"))],
) -> CalibrationSessionRead:
    """Complete the calibration session."""
    session = await _calibration.complete_session(
        db, session_id, _org_id(current_user), current_user.id
    )
    await db.commit()
    return CalibrationSessionRead.model_validate(session)
