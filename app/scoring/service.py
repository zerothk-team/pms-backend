"""
ScoringEngine and CalibrationService — all scoring business logic.

Scoring workflow:
1. HR admin closes a review cycle (status → CLOSED).
2. POST /scoring/compute/{cycle_id} triggers ScoringEngine.compute_scores_for_cycle().
3. The engine loads every LOCKED target in the cycle, finds each target's latest
   APPROVED actual, computes achievement %, weighted score, and inserts/updates a
   PerformanceScore row.
4. After all KPI scores are computed the engine computes a CompositeScore (weighted
   average of all KPI scores) for each employee.
5. Managers can then adjust individual KPI scores (within the cap) or leave comments.
6. Optionally HR runs a CalibrationSession to adjust composite scores.
7. HR admin calls POST /scoring/finalise/{cycle_id} to lock all scores (status=FINAL).
"""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.actuals.enums import ActualEntryStatus
from app.actuals.models import KPIActual
from app.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.kpis.enums import DataSourceType
from app.kpis.models import KPI
from app.review_cycles.enums import CycleStatus
from app.review_cycles.models import ReviewCycle
from app.scoring.calculator import (
    compute_achievement_percentage,
    compute_composite_score,
    compute_score_distribution,
    compute_weighted_score,
    determine_rating,
    determine_rating_with_config,
    resolve_scoring_config,
    validate_adjustment,
)
from app.scoring.enums import CalibrationStatus, RatingLabel, ScoreStatus
from app.scoring.models import (
    CalibrationSession,
    CompositeScore,
    PerformanceScore,
    ScoreAdjustment,
    ScoreConfig,
)
from app.scoring.schemas import (
    CalibrationScoreUpdate,
    CalibrationSessionCreate,
    CompositeAdjustRequest,
    ScoreAdjustRequest,
    ScoreConfigCreate,
    ScoreConfigUpdate,
)
from app.targets.enums import TargetStatus
from app.targets.models import KPITarget
from app.users.models import User, UserRole


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_score_config(
    db: AsyncSession, org_id: UUID, cycle_id: UUID
) -> ScoreConfig | None:
    result = await db.execute(
        select(ScoreConfig).where(
            ScoreConfig.organisation_id == org_id,
            ScoreConfig.review_cycle_id == cycle_id,
        )
    )
    return result.scalar_one_or_none()


async def _require_score_config(
    db: AsyncSession, org_id: UUID, cycle_id: UUID
) -> ScoreConfig:
    config = await _get_score_config(db, org_id, cycle_id)
    if not config:
        # Return a default config (not persisted) if none configured.
        # Must supply explicit values — SQLAlchemy column defaults are only
        # applied on INSERT, not on transient Python object construction.
        config = ScoreConfig(
            organisation_id=org_id,
            review_cycle_id=cycle_id,
            exceptional_min=Decimal("120.00"),
            exceeds_min=Decimal("100.00"),
            meets_min=Decimal("80.00"),
            partially_meets_min=Decimal("60.00"),
            does_not_meet_min=Decimal("0.00"),
            allow_manager_adjustment=True,
            max_adjustment_points=Decimal("10.00"),
            requires_calibration=False,
        )
    return config


async def _get_latest_approved_actual(
    db: AsyncSession, target_id: UUID
) -> KPIActual | None:
    """Return the most recent APPROVED actual for the target."""
    result = await db.execute(
        select(KPIActual)
        .where(
            KPIActual.target_id == target_id,
            KPIActual.status == ActualEntryStatus.APPROVED,
        )
        .order_by(KPIActual.period_date.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _get_performance_score(
    db: AsyncSession, target_id: UUID, cycle_id: UUID
) -> PerformanceScore | None:
    result = await db.execute(
        select(PerformanceScore).where(
            PerformanceScore.target_id == target_id,
            PerformanceScore.review_cycle_id == cycle_id,
        )
    )
    return result.scalar_one_or_none()


async def _get_composite_score(
    db: AsyncSession, user_id: UUID, cycle_id: UUID
) -> CompositeScore | None:
    result = await db.execute(
        select(CompositeScore).where(
            CompositeScore.user_id == user_id,
            CompositeScore.review_cycle_id == cycle_id,
        )
    )
    return result.scalar_one_or_none()


def _assert_not_final(score_status: ScoreStatus, label: str = "Score") -> None:
    if score_status == ScoreStatus.FINAL:
        raise ForbiddenException(
            f"{label} is FINAL and cannot be modified. "
            "Use POST /scoring/finalise to understand the lock or contact HR admin."
        )


# ---------------------------------------------------------------------------
# ScoreConfig service
# ---------------------------------------------------------------------------


class ScoreConfigService:

    async def create(
        self, db: AsyncSession, org_id: UUID, data: ScoreConfigCreate
    ) -> ScoreConfig:
        """
        Create scoring thresholds for an org × cycle combination.

        Business rule: Only one config per org per cycle.
        Validates threshold ordering: exceptional > exceeds > meets >
        partially_meets > does_not_meet (≥ 0).
        """
        # Validate threshold ordering
        thresholds = [
            data.exceptional_min,
            data.exceeds_min,
            data.meets_min,
            data.partially_meets_min,
            data.does_not_meet_min,
        ]
        for i in range(len(thresholds) - 1):
            if thresholds[i] <= thresholds[i + 1]:
                raise BadRequestException(
                    "Score thresholds must be in strictly descending order: "
                    "exceptional > exceeds > meets > partially_meets > does_not_meet."
                )

        existing = await _get_score_config(db, org_id, data.review_cycle_id)
        if existing:
            from app.exceptions import ConflictException

            raise ConflictException(
                f"A score config already exists for this cycle. "
                f"Use PUT /scoring/config/{existing.id} to update it."
            )

        config = ScoreConfig(
            organisation_id=org_id,
            review_cycle_id=data.review_cycle_id,
            exceptional_min=data.exceptional_min,
            exceeds_min=data.exceeds_min,
            meets_min=data.meets_min,
            partially_meets_min=data.partially_meets_min,
            does_not_meet_min=data.does_not_meet_min,
            allow_manager_adjustment=data.allow_manager_adjustment,
            max_adjustment_points=data.max_adjustment_points,
            requires_calibration=data.requires_calibration,
        )
        db.add(config)
        await db.flush()
        await db.refresh(config)
        return config

    async def get_for_cycle(
        self, db: AsyncSession, org_id: UUID, cycle_id: UUID
    ) -> ScoreConfig:
        config = await _get_score_config(db, org_id, cycle_id)
        if not config:
            raise NotFoundException(
                f"No score config found for cycle '{cycle_id}'. "
                "Create one with POST /scoring/config/ first."
            )
        return config

    async def update(
        self,
        db: AsyncSession,
        config_id: UUID,
        org_id: UUID,
        data: ScoreConfigUpdate,
    ) -> ScoreConfig:
        result = await db.execute(
            select(ScoreConfig).where(
                ScoreConfig.id == config_id,
                ScoreConfig.organisation_id == org_id,
            )
        )
        config = result.scalar_one_or_none()
        if not config:
            raise NotFoundException(f"Score config '{config_id}' not found.")

        update_data = data.model_dump(exclude_none=True)
        for field, value in update_data.items():
            setattr(config, field, value)

        await db.flush()
        await db.refresh(config)
        return config


# ---------------------------------------------------------------------------
# ScoringEngine
# ---------------------------------------------------------------------------


class ScoringEngine:

    async def compute_scores_for_cycle(
        self,
        db: AsyncSession,
        cycle_id: UUID,
        org_id: UUID,
        user_ids: list[UUID] | None = None,
    ) -> list[CompositeScore]:
        """
        Main scoring run triggered when a cycle is CLOSED.

        For each employee (or the specified subset):
          1. Load all LOCKED targets for the user in this cycle.
          2. For each target, get the latest APPROVED actual.
          3. For FORMULA KPIs with no actual: attempt formula evaluation.
          4. Compute achievement % and weighted score via calculator.
          5. Upsert a PerformanceScore row.
          6. Aggregate into a CompositeScore.

        Returns the list of CompositeScore objects that were created/updated.
        """
        # Verify cycle exists and belongs to org
        cycle_result = await db.execute(
            select(ReviewCycle).where(
                ReviewCycle.id == cycle_id,
                ReviewCycle.organisation_id == org_id,
            )
        )
        cycle = cycle_result.scalar_one_or_none()
        if not cycle:
            raise NotFoundException(f"Review cycle '{cycle_id}' not found.")

        if cycle.status not in (CycleStatus.CLOSED, CycleStatus.ACTIVE):
            raise BadRequestException(
                f"Scoring can only run on CLOSED or ACTIVE cycles. "
                f"Current status: {cycle.status.value}."
            )

        config = await _require_score_config(db, org_id, cycle_id)

        # Load all LOCKED targets for this cycle, optionally filtered by user
        target_query = (
            select(KPITarget)
            .where(
                KPITarget.review_cycle_id == cycle_id,
                KPITarget.status == TargetStatus.LOCKED,
                KPITarget.assignee_user_id.isnot(None),
            )
            .options(
                selectinload(KPITarget.kpi).selectinload(KPI.scoring_config),
                selectinload(KPITarget.scoring_config),
            )
        )
        if user_ids:
            target_query = target_query.where(KPITarget.assignee_user_id.in_(user_ids))

        targets_result = await db.execute(target_query)
        targets = targets_result.scalars().all()

        if not targets:
            return []

        # Group targets by user
        user_targets: dict[UUID, list[KPITarget]] = {}
        for target in targets:
            uid = target.assignee_user_id
            user_targets.setdefault(uid, []).append(target)

        composite_scores: list[CompositeScore] = []
        warnings: list[str] = []

        for user_id, user_target_list in user_targets.items():
            kpi_score_inputs: list[dict] = []
            kpis_with_actuals = 0

            for target in user_target_list:
                kpi = target.kpi

                # Step 1: Get latest approved actual
                actual = await _get_latest_approved_actual(db, target.id)

                # Step 2: For FORMULA KPIs, try to auto-compute if no actual
                if actual is None and kpi.data_source == DataSourceType.FORMULA:
                    try:
                        from app.actuals.service import ActualService  # avoid circular

                        actual = await self._evaluate_formula_actual(
                            db, target, kpi, cycle, org_id, user_id
                        )
                    except Exception as exc:
                        warnings.append(
                            f"Formula evaluation failed for KPI {kpi.code} "
                            f"user={user_id}: {exc}"
                        )

                # Step 3: Compute scores
                if actual is not None:
                    # Resolve effective scoring config (3-level precedence)
                    effective_config = resolve_scoring_config(target, config)
                    achievement_pct = compute_achievement_percentage(
                        actual_value=actual.actual_value,
                        target_value=target.target_value,
                        scoring_direction=kpi.scoring_direction,
                        minimum_value=target.minimum_value,
                    )
                    kpis_with_actuals += 1
                else:
                    # No actual submitted → 0 % achievement, use cycle default for config
                    effective_config = {
                        "exceptional_min":    float(config.exceptional_min),
                        "exceeds_min":        float(config.exceeds_min),
                        "meets_min":          float(config.meets_min),
                        "partially_meets_min": float(config.partially_meets_min),
                        "does_not_meet_min":  0.0,
                        "achievement_cap":    200.0,
                        "source":             "cycle_default",
                    }
                    achievement_pct = Decimal("0.0000")

                weighted = compute_weighted_score(achievement_pct, target.weight)

                # Step 4: Upsert PerformanceScore
                perf_score = await _get_performance_score(db, target.id, cycle_id)
                if perf_score is None:
                    perf_score = PerformanceScore(
                        target_id=target.id,
                        user_id=user_id,
                        kpi_id=target.kpi_id,
                        review_cycle_id=cycle_id,
                    )
                    db.add(perf_score)

                perf_score.achievement_percentage = achievement_pct
                perf_score.weighted_score = weighted
                perf_score.computed_score = achievement_pct
                perf_score.final_score = (
                    perf_score.adjusted_score
                    if perf_score.adjusted_score is not None
                    else achievement_pct
                )
                rating, rating_source = determine_rating_with_config(
                    perf_score.final_score, effective_config
                )
                perf_score.rating = rating
                perf_score.scoring_config_snapshot = effective_config
                perf_score.rating_config_source = rating_source
                if perf_score.status not in (
                    ScoreStatus.ADJUSTED,
                    ScoreStatus.CALIBRATED,
                    ScoreStatus.FINAL,
                ):
                    perf_score.status = ScoreStatus.COMPUTED
                perf_score.computed_at = datetime.now(timezone.utc)

                await db.flush()

                # For composite: use final_score so manager adjustments flow through
                effective_weighted = compute_weighted_score(perf_score.final_score, target.weight)
                kpi_score_inputs.append(
                    {
                        "weighted_score": effective_weighted,
                        "weight": target.weight,
                    }
                )

            # Step 5: Composite score
            composite_score_value = compute_composite_score(kpi_score_inputs)
            composite = await _get_composite_score(db, user_id, cycle_id)
            if composite is None:
                # Get org_id from first target's cycle (already verified above)
                composite = CompositeScore(
                    user_id=user_id,
                    review_cycle_id=cycle_id,
                    organisation_id=org_id,
                )
                db.add(composite)

            composite.weighted_average = composite_score_value
            composite.kpi_count = len(user_target_list)
            composite.kpis_with_actuals = kpis_with_actuals

            # Only update final if not already adjusted/calibrated/final
            if composite.status not in (
                ScoreStatus.ADJUSTED,
                ScoreStatus.CALIBRATED,
                ScoreStatus.FINAL,
            ):
                composite.final_weighted_average = composite_score_value
                composite.status = ScoreStatus.COMPUTED

            if kpis_with_actuals == 0:
                composite.rating = RatingLabel.NOT_RATED
            else:
                composite.rating = determine_rating(composite.final_weighted_average, config)

            composite.computed_at = datetime.now(timezone.utc)
            await db.flush()
            await db.refresh(composite)
            composite_scores.append(composite)

        return composite_scores

    async def _evaluate_formula_actual(
        self,
        db: AsyncSession,
        target: KPITarget,
        kpi: KPI,
        cycle: ReviewCycle,
        org_id: UUID,
        user_id: UUID,
    ) -> KPIActual | None:
        """
        Attempt to evaluate a formula KPI and return a synthetic KPIActual.

        Uses the formula evaluator from the kpis module to resolve
        dependency values and compute the result.  If the formula cannot
        be evaluated (missing dependencies, etc.), returns None.
        """
        if not kpi.formula_expression:
            return None

        try:
            from app.kpis.formula import FormulaEvaluator
            from app.kpis.service import KPIService

            kpi_service = KPIService()
            result_value = await kpi_service.evaluate_formula_for_kpi(
                db,
                kpi_id=kpi.id,
                org_id=org_id,
                period_date=cycle.end_date,
            )

            if result_value is None:
                return None

            # Create a transient (in-memory) KPIActual for scoring purposes
            from app.actuals.enums import ActualEntrySource

            synthetic = KPIActual(
                target_id=target.id,
                kpi_id=kpi.id,
                period_date=cycle.end_date,
                period_label="Formula (auto)",
                actual_value=result_value,
                entry_source=ActualEntrySource.AUTO_FORMULA,
                status=ActualEntryStatus.APPROVED,
                submitted_by_id=None,
            )
            db.add(synthetic)
            await db.flush()
            return synthetic
        except Exception:
            return None

    async def recompute_score_for_user(
        self,
        db: AsyncSession,
        user_id: UUID,
        cycle_id: UUID,
        org_id: UUID,
    ) -> CompositeScore:
        """
        Recompute KPI and composite scores for a single user.

        Useful after an actual is corrected or a target is updated.
        Existing ADJUSTED scores are NOT reset — the adjustment is
        re-applied on top of the new computed value.
        """
        results = await self.compute_scores_for_cycle(
            db, cycle_id, org_id, user_ids=[user_id]
        )
        if not results:
            raise NotFoundException(
                f"No locked targets found for user '{user_id}' in cycle '{cycle_id}'."
            )
        return results[0]

    async def apply_manager_adjustment(
        self,
        db: AsyncSession,
        score_id: UUID,
        manager_id: UUID,
        org_id: UUID,
        data: ScoreAdjustRequest,
    ) -> PerformanceScore:
        """
        Manager adjusts an individual KPI score.

        Business rules:
        - Score must not be FINAL.
        - The abs difference between old and new must not exceed max_adjustment_points.
        - A ScoreAdjustment audit record is always written.
        - After adjustment, the composite score is automatically recomputed.
        """
        # Load score, ensure it belongs to this org via cycle
        result = await db.execute(
            select(PerformanceScore)
            .join(ReviewCycle, PerformanceScore.review_cycle_id == ReviewCycle.id)
            .where(
                PerformanceScore.id == score_id,
                ReviewCycle.organisation_id == org_id,
            )
            .options(selectinload(PerformanceScore.target))
        )
        score = result.scalar_one_or_none()
        if not score:
            raise NotFoundException(f"Performance score '{score_id}' not found.")

        _assert_not_final(score.status, "KPI score")

        config = await _require_score_config(db, org_id, score.review_cycle_id)

        if not config.allow_manager_adjustment:
            raise ForbiddenException(
                "Manager adjustments are disabled for this review cycle."
            )

        if not validate_adjustment(
            score.final_score, data.new_score, config.max_adjustment_points
        ):
            raise BadRequestException(
                f"Adjustment of {abs(data.new_score - score.final_score):.2f} points "
                f"exceeds the allowed maximum of {config.max_adjustment_points} points."
            )

        before = score.final_score
        score.adjusted_score = data.new_score
        score.final_score = data.new_score
        score.status = ScoreStatus.ADJUSTED
        score.rating = determine_rating(data.new_score, config)

        adjustment = ScoreAdjustment(
            score_id=score_id,
            adjusted_by_id=manager_id,
            before_value=before,
            after_value=data.new_score,
            reason=data.reason,
            adjustment_type="manager_review",
        )
        db.add(adjustment)
        await db.flush()

        # Recompute composite score for this user
        await self.recompute_score_for_user(
            db, score.user_id, score.review_cycle_id, org_id
        )

        await db.refresh(score)
        return score

    async def apply_composite_adjustment(
        self,
        db: AsyncSession,
        composite_score_id: UUID,
        adjusted_by: UUID,
        org_id: UUID,
        data: CompositeAdjustRequest,
        adjustment_type: str = "manager_review",
    ) -> CompositeScore:
        """
        Direct adjustment to a composite score (e.g. from calibration).

        The adjustment_type parameter distinguishes manager reviews from
        calibration events in the audit log.
        """
        result = await db.execute(
            select(CompositeScore).where(
                CompositeScore.id == composite_score_id,
                CompositeScore.organisation_id == org_id,
            )
        )
        composite = result.scalar_one_or_none()
        if not composite:
            raise NotFoundException(f"Composite score '{composite_score_id}' not found.")

        _assert_not_final(composite.status, "Composite score")

        config = await _require_score_config(db, org_id, composite.review_cycle_id)

        if adjustment_type == "manager_review" and not config.allow_manager_adjustment:
            raise ForbiddenException(
                "Manager adjustments are disabled for this review cycle."
            )

        if adjustment_type == "manager_review" and not validate_adjustment(
            composite.final_weighted_average,
            data.new_weighted_average,
            config.max_adjustment_points,
        ):
            raise BadRequestException(
                f"Adjustment exceeds the maximum of {config.max_adjustment_points} points."
            )

        before = composite.final_weighted_average
        composite.final_weighted_average = data.new_weighted_average
        composite.status = ScoreStatus.ADJUSTED
        composite.rating = determine_rating(data.new_weighted_average, config)

        if data.manager_comment is not None:
            composite.manager_comment = data.manager_comment

        adjustment = ScoreAdjustment(
            composite_score_id=composite_score_id,
            adjusted_by_id=adjusted_by,
            before_value=before,
            after_value=data.new_weighted_average,
            reason=data.reason,
            adjustment_type=adjustment_type,
        )
        db.add(adjustment)
        await db.flush()
        await db.refresh(composite)
        return composite

    async def finalise_scores(
        self, db: AsyncSession, cycle_id: UUID, org_id: UUID
    ) -> int:
        """
        Lock all composite scores for the cycle (status → FINAL).

        Once FINAL, no further adjustments (manager or calibration) are allowed.
        Returns the number of scores finalised.
        """
        cycle_result = await db.execute(
            select(ReviewCycle).where(
                ReviewCycle.id == cycle_id,
                ReviewCycle.organisation_id == org_id,
            )
        )
        cycle = cycle_result.scalar_one_or_none()
        if not cycle:
            raise NotFoundException(f"Review cycle '{cycle_id}' not found.")

        if cycle.status not in (CycleStatus.CLOSED,):
            raise BadRequestException(
                "Scores can only be finalised for CLOSED cycles. "
                f"Current cycle status: {cycle.status.value}."
            )

        # Check calibration requirement
        config = await _get_score_config(db, org_id, cycle_id)
        if config and config.requires_calibration:
            # Ensure at least one calibration session is completed
            cal_result = await db.execute(
                select(CalibrationSession).where(
                    CalibrationSession.review_cycle_id == cycle_id,
                    CalibrationSession.organisation_id == org_id,
                    CalibrationSession.status == CalibrationStatus.COMPLETED,
                )
            )
            if not cal_result.scalar_one_or_none():
                raise BadRequestException(
                    "This cycle requires calibration. At least one calibration session "
                    "must be COMPLETED before scores can be finalised."
                )

        # Lock all performance scores for the cycle
        await db.execute(
            update(PerformanceScore)
            .where(
                PerformanceScore.review_cycle_id == cycle_id,
                PerformanceScore.status != ScoreStatus.FINAL,
            )
            .values(status=ScoreStatus.FINAL)
        )

        # Lock all composite scores, count them
        result = await db.execute(
            select(CompositeScore).where(
                CompositeScore.review_cycle_id == cycle_id,
                CompositeScore.organisation_id == org_id,
                CompositeScore.status != ScoreStatus.FINAL,
            )
        )
        composites = result.scalars().all()
        count = len(composites)
        for c in composites:
            c.status = ScoreStatus.FINAL

        await db.flush()
        return count

    async def get_score_for_user(
        self, db: AsyncSession, user_id: UUID, cycle_id: UUID, org_id: UUID
    ) -> dict:
        """
        Full score breakdown for a single user in one cycle.

        Returns:
          composite      — CompositeScore
          kpi_scores     — list[PerformanceScore] with KPI and target data
          adjustment_history — list[ScoreAdjustment]
        """
        composite = await _get_composite_score(db, user_id, cycle_id)

        # Verify org access
        if composite and composite.organisation_id != org_id:
            raise ForbiddenException("Score does not belong to your organisation.")

        kpi_scores_result = await db.execute(
            select(PerformanceScore)
            .where(
                PerformanceScore.user_id == user_id,
                PerformanceScore.review_cycle_id == cycle_id,
            )
            .options(
                selectinload(PerformanceScore.kpi),
                selectinload(PerformanceScore.target),
                selectinload(PerformanceScore.adjustments),
            )
        )
        kpi_scores = kpi_scores_result.scalars().all()

        adj_result = await db.execute(
            select(ScoreAdjustment)
            .where(ScoreAdjustment.composite_score_id == (composite.id if composite else None))
            .order_by(ScoreAdjustment.created_at)
        )
        adjustments = adj_result.scalars().all()

        return {
            "composite": composite,
            "kpi_scores": kpi_scores,
            "adjustment_history": adjustments,
        }

    async def get_team_scores(
        self, db: AsyncSession, manager_id: UUID, cycle_id: UUID, org_id: UUID
    ) -> list[dict]:
        """
        Returns individual score breakdowns for all direct reports of the manager.

        Each element follows the same structure as get_score_for_user().
        """
        # Get direct reports
        reports_result = await db.execute(
            select(User).where(
                User.manager_id == manager_id,
                User.organisation_id == org_id,
                User.is_active.is_(True),
            )
        )
        reports = reports_result.scalars().all()

        team_scores = []
        for report in reports:
            score_data = await self.get_score_for_user(db, report.id, cycle_id, org_id)
            score_data["user"] = report
            team_scores.append(score_data)

        return team_scores

    async def get_org_distribution(
        self,
        db: AsyncSession,
        cycle_id: UUID,
        org_id: UUID,
        department: str | None = None,
    ) -> dict:
        """
        Statistical distribution of composite scores for the organisation.

        Optionally filtered by department (matches KPI category department).
        Used to drive heatmaps and bell-curve charts on the executive dashboard.
        """
        query = select(CompositeScore).where(
            CompositeScore.review_cycle_id == cycle_id,
            CompositeScore.organisation_id == org_id,
        )
        result = await db.execute(query)
        composites = result.scalars().all()

        scores = [c.final_weighted_average for c in composites]
        distribution = compute_score_distribution(scores)
        distribution["total_employees"] = len(composites)
        distribution["cycle_id"] = str(cycle_id)

        return distribution


# ---------------------------------------------------------------------------
# CalibrationService
# ---------------------------------------------------------------------------


class CalibrationService:

    async def create_session(
        self,
        db: AsyncSession,
        org_id: UUID,
        facilitator_id: UUID,
        data: CalibrationSessionCreate,
    ) -> CalibrationSession:
        """
        Create a calibration session for a set of employees.

        Business rules:
        - Facilitator must be hr_admin.
        - All scope_user_ids must belong to the same org.
        - Composite scores for all users must exist (scoring must have run).
        """
        # Verify composite scores exist for all in-scope users
        result = await db.execute(
            select(CompositeScore).where(
                CompositeScore.review_cycle_id == data.review_cycle_id,
                CompositeScore.organisation_id == org_id,
                CompositeScore.user_id.in_(data.scope_user_ids),
            )
        )
        found_ids = {c.user_id for c in result.scalars().all()}
        missing = set(data.scope_user_ids) - found_ids
        if missing:
            raise BadRequestException(
                f"The following users do not have computed scores yet: "
                f"{[str(uid) for uid in missing]}. "
                "Run scoring first with POST /scoring/compute/{cycle_id}."
            )

        session = CalibrationSession(
            review_cycle_id=data.review_cycle_id,
            organisation_id=org_id,
            name=data.name,
            facilitator_id=facilitator_id,
            scope_user_ids=data.scope_user_ids,
            notes=data.notes,
        )
        db.add(session)
        await db.flush()
        await db.refresh(session)
        return session

    async def get_session(
        self, db: AsyncSession, session_id: UUID, org_id: UUID
    ) -> CalibrationSession:
        result = await db.execute(
            select(CalibrationSession).where(
                CalibrationSession.id == session_id,
                CalibrationSession.organisation_id == org_id,
            )
        )
        session = result.scalar_one_or_none()
        if not session:
            raise NotFoundException(f"Calibration session '{session_id}' not found.")
        return session

    async def list_sessions(
        self, db: AsyncSession, cycle_id: UUID, org_id: UUID
    ) -> list[CalibrationSession]:
        result = await db.execute(
            select(CalibrationSession).where(
                CalibrationSession.review_cycle_id == cycle_id,
                CalibrationSession.organisation_id == org_id,
            ).order_by(CalibrationSession.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_session_data(
        self, db: AsyncSession, session_id: UUID, org_id: UUID
    ) -> dict:
        """
        Return the calibration session plus all composite scores for
        in-scope users, sorted by score descending.

        Also includes distribution stats to help facilitators spot
        outliers and clustering.
        """
        session = await self.get_session(db, session_id, org_id)

        composites_result = await db.execute(
            select(CompositeScore)
            .where(
                CompositeScore.review_cycle_id == session.review_cycle_id,
                CompositeScore.organisation_id == org_id,
                CompositeScore.user_id.in_(session.scope_user_ids),
            )
            .order_by(CompositeScore.final_weighted_average.desc())
            .options(selectinload(CompositeScore.user))
        )
        composites = list(composites_result.scalars().all())

        scores = [c.final_weighted_average for c in composites]
        distribution = compute_score_distribution(scores)

        return {
            "session": session,
            "composite_scores": composites,
            "distribution": distribution,
        }

    async def update_score_in_session(
        self,
        db: AsyncSession,
        session_id: UUID,
        composite_score_id: UUID,
        org_id: UUID,
        facilitator_id: UUID,
        data: CalibrationScoreUpdate,
    ) -> CompositeScore:
        """
        Adjust a composite score during a calibration session.

        Business rules:
        - The session must be OPEN or IN_PROGRESS.
        - The composite_score must be for a user in the session's scope.
        - No cap enforcement during calibration (facilitator has full authority).
        - Records a ScoreAdjustment of type "calibration".
        """
        session = await self.get_session(db, session_id, org_id)

        if session.status not in (CalibrationStatus.OPEN, CalibrationStatus.IN_PROGRESS):
            raise ForbiddenException(
                "Calibration session is not open for adjustments. "
                f"Current status: {session.status.value}."
            )

        # Verify the composite score is in-scope for this session
        result = await db.execute(
            select(CompositeScore).where(
                CompositeScore.id == composite_score_id,
                CompositeScore.organisation_id == org_id,
            )
        )
        composite = result.scalar_one_or_none()
        if not composite:
            raise NotFoundException(f"Composite score '{composite_score_id}' not found.")

        if composite.user_id not in session.scope_user_ids:
            raise ForbiddenException(
                "This employee is not in the scope of the calibration session."
            )

        _assert_not_final(composite.status, "Composite score")

        config = await _require_score_config(db, org_id, composite.review_cycle_id)

        before = composite.final_weighted_average
        composite.final_weighted_average = data.new_score
        composite.status = ScoreStatus.CALIBRATED
        composite.rating = determine_rating(data.new_score, config)
        composite.calibration_note = data.note

        adjustment = ScoreAdjustment(
            composite_score_id=composite_score_id,
            adjusted_by_id=facilitator_id,
            before_value=before,
            after_value=data.new_score,
            reason=data.note,
            adjustment_type="calibration",
        )
        db.add(adjustment)

        # Mark session as in-progress if it was just opened
        if session.status == CalibrationStatus.OPEN:
            session.status = CalibrationStatus.IN_PROGRESS

        await db.flush()
        await db.refresh(composite)
        return composite

    async def complete_session(
        self,
        db: AsyncSession,
        session_id: UUID,
        org_id: UUID,
        facilitator_id: UUID,
    ) -> CalibrationSession:
        """
        Mark the calibration session as COMPLETED.

        All ADJUSTED composite scores for in-scope users that were
        touched during this session become CALIBRATED.
        """
        session = await self.get_session(db, session_id, org_id)

        if session.status not in (CalibrationStatus.OPEN, CalibrationStatus.IN_PROGRESS):
            raise BadRequestException(
                f"Session status is already {session.status.value}. "
                "Only OPEN or IN_PROGRESS sessions can be completed."
            )

        # Mark any still-COMPUTED scores for in-scope users as MANAGER_REVIEWED
        # (they were reviewed but unchanged during calibration)
        await db.execute(
            update(CompositeScore)
            .where(
                CompositeScore.review_cycle_id == session.review_cycle_id,
                CompositeScore.organisation_id == org_id,
                CompositeScore.user_id.in_(session.scope_user_ids),
                CompositeScore.status == ScoreStatus.COMPUTED,
            )
            .values(status=ScoreStatus.MANAGER_REVIEWED)
        )

        session.status = CalibrationStatus.COMPLETED
        session.completed_at = datetime.now(timezone.utc)

        await db.flush()
        await db.refresh(session)
        return session
