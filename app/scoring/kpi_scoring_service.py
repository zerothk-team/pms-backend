"""
KPIScoringConfigService — CRUD for per-KPI / per-target scoring configurations,
including system preset seeding and scoring preview.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.kpis.models import KPI
from app.scoring.calculator import determine_rating_with_config
from app.scoring.enums import ScoringPreset
from app.scoring.kpi_scoring_model import KPIScoringConfig
from app.scoring.kpi_scoring_schemas import (
    KPIScoringConfigCreate,
    KPIScoringConfigUpdate,
    ScoringPreviewResult,
)
from app.targets.enums import TargetStatus
from app.targets.models import KPITarget

# ---------------------------------------------------------------------------
# Rating display labels (mirrors RatingLabel values with human-readable text)
# ---------------------------------------------------------------------------

_RATING_LABELS = {
    "exceptional":          "Exceptional",
    "exceeds_expectations": "Exceeds Expectations",
    "meets_expectations":   "Meets Expectations",
    "partially_meets":      "Partially Meets",
    "does_not_meet":        "Does Not Meet",
    "not_rated":            "Not Rated",
}


class KPIScoringConfigService:

    # ── System presets ───────────────────────────────────────────────────────

    SYSTEM_PRESETS = [
        {
            "name": "Standard",
            "preset": ScoringPreset.STANDARD,
            "exceptional_min": Decimal("120"),
            "exceeds_min":     Decimal("100"),
            "meets_min":       Decimal("80"),
            "partially_meets_min": Decimal("60"),
        },
        {
            "name": "Strict",
            "preset": ScoringPreset.STRICT,
            "exceptional_min": Decimal("130"),
            "exceeds_min":     Decimal("110"),
            "meets_min":       Decimal("95"),
            "partially_meets_min": Decimal("80"),
        },
        {
            "name": "Lenient",
            "preset": ScoringPreset.LENIENT,
            "exceptional_min": Decimal("110"),
            "exceeds_min":     Decimal("90"),
            "meets_min":       Decimal("70"),
            "partially_meets_min": Decimal("50"),
        },
        {
            "name": "Binary",
            "preset": ScoringPreset.BINARY,
            "exceptional_min": Decimal("100"),
            "exceeds_min":     Decimal("100"),
            "meets_min":       Decimal("90"),
            "partially_meets_min": Decimal("0"),
        },
        {
            "name": "Sales Org",
            "preset": ScoringPreset.SALES,
            "exceptional_min": Decimal("120"),
            "exceeds_min":     Decimal("100"),
            "meets_min":       Decimal("85"),
            "partially_meets_min": Decimal("70"),
        },
    ]

    async def seed_system_presets(self, db: AsyncSession) -> None:
        """Idempotent — inserts system presets only if not already present."""
        for preset_data in self.SYSTEM_PRESETS:
            result = await db.execute(
                select(KPIScoringConfig).where(
                    KPIScoringConfig.is_system_preset == True,  # noqa: E712
                    KPIScoringConfig.name == preset_data["name"],
                )
            )
            if result.scalar_one_or_none() is None:
                db.add(
                    KPIScoringConfig(
                        **preset_data,
                        does_not_meet_min=Decimal("0"),
                        achievement_cap=Decimal("200"),
                        is_system_preset=True,
                    )
                )
        await db.commit()

    # ── CRUD ─────────────────────────────────────────────────────────────────

    async def create(
        self,
        db: AsyncSession,
        org_id: UUID,
        user_id: UUID,
        data: KPIScoringConfigCreate,
    ) -> KPIScoringConfig:
        config = KPIScoringConfig(
            name=data.name,
            description=data.description,
            preset=data.preset,
            exceptional_min=data.exceptional_min,
            exceeds_min=data.exceeds_min,
            meets_min=data.meets_min,
            partially_meets_min=data.partially_meets_min,
            does_not_meet_min=data.does_not_meet_min,
            achievement_cap=data.achievement_cap,
            adjustment_justification_threshold=data.adjustment_justification_threshold,
            organisation_id=org_id,
            created_by_id=user_id,
            is_system_preset=False,
        )
        db.add(config)
        await db.flush()
        await db.refresh(config)
        return config

    async def list_for_org(
        self, db: AsyncSession, org_id: UUID
    ) -> list[KPIScoringConfig]:
        """Returns org's custom configs + all system presets, ordered."""
        result = await db.execute(
            select(KPIScoringConfig)
            .where(
                or_(
                    KPIScoringConfig.organisation_id == org_id,
                    KPIScoringConfig.is_system_preset == True,  # noqa: E712
                )
            )
            .order_by(
                KPIScoringConfig.is_system_preset.desc(),
                KPIScoringConfig.name,
            )
        )
        return list(result.scalars().all())

    async def get(
        self, db: AsyncSession, config_id: UUID, org_id: UUID
    ) -> KPIScoringConfig:
        config = await self._get_config(db, config_id, org_id)
        return config

    async def update(
        self,
        db: AsyncSession,
        config_id: UUID,
        org_id: UUID,
        data: KPIScoringConfigUpdate,
    ) -> KPIScoringConfig:
        config = await self._get_config(db, config_id, org_id)
        if config.is_system_preset:
            raise ForbiddenException("System presets cannot be modified.")
        for field, value in data.model_dump(exclude_none=True).items():
            setattr(config, field, value)
        config.updated_at = datetime.now(timezone.utc)
        await db.flush()
        await db.refresh(config)
        return config

    async def delete(
        self, db: AsyncSession, config_id: UUID, org_id: UUID
    ) -> None:
        config = await self._get_config(db, config_id, org_id)
        if config.is_system_preset:
            raise ForbiddenException("System presets cannot be deleted.")
        # Check not in use by any KPI
        kpi_using = await db.execute(
            select(KPI.id).where(KPI.scoring_config_id == config_id).limit(1)
        )
        if kpi_using.scalar_one_or_none():
            raise BadRequestException(
                "This scoring config is assigned to one or more KPIs. "
                "Remove the assignment before deleting."
            )
        # Check not in use by any target
        target_using = await db.execute(
            select(KPITarget.id)
            .where(KPITarget.scoring_config_id == config_id)
            .limit(1)
        )
        if target_using.scalar_one_or_none():
            raise BadRequestException(
                "This scoring config is assigned to one or more targets. "
                "Remove the assignment before deleting."
            )
        await db.delete(config)
        await db.flush()

    # ── Assign to KPI / Target ────────────────────────────────────────────────

    async def assign_to_kpi(
        self,
        db: AsyncSession,
        kpi_id: UUID,
        org_id: UUID,
        scoring_config_id: Optional[UUID],
    ) -> KPI:
        """Assign (or remove) this scoring config from a KPI definition."""
        kpi = await self._get_kpi(db, kpi_id, org_id)
        if scoring_config_id is not None:
            await self._validate_config_accessible(db, scoring_config_id, org_id)
        kpi.scoring_config_id = scoring_config_id
        kpi.updated_at = datetime.now(timezone.utc)
        await db.flush()
        await db.refresh(kpi)
        return kpi

    async def assign_to_target(
        self,
        db: AsyncSession,
        target_id: UUID,
        org_id: UUID,
        scoring_config_id: Optional[UUID],
    ) -> KPITarget:
        """
        Assign (or remove) scoring config from a KPITarget.
        Cannot modify locked targets.
        """
        target = await self._get_target(db, target_id, org_id)
        if scoring_config_id is not None:
            await self._validate_config_accessible(db, scoring_config_id, org_id)
        target.scoring_config_id = scoring_config_id
        await db.flush()
        await db.refresh(target)
        return target

    async def get_effective_config_for_target(
        self,
        db: AsyncSession,
        target_id: UUID,
        org_id: UUID,
    ) -> dict:
        """
        Return the resolved scoring thresholds and source for a target.
        Used by the UI to show which config is in effect.
        """
        target = await db.execute(
            select(KPITarget)
            .where(KPITarget.id == target_id)
            .options(
                selectinload(KPITarget.scoring_config),
                selectinload(KPITarget.kpi).selectinload(KPI.scoring_config),
            )
        )
        target_obj = target.scalar_one_or_none()
        if not target_obj:
            raise NotFoundException(f"Target '{target_id}' not found.")

        # Verify org ownership via review cycle
        from app.review_cycles.models import ReviewCycle
        cycle_check = await db.execute(
            select(ReviewCycle.organisation_id).where(
                ReviewCycle.id == target_obj.review_cycle_id
            )
        )
        cycle_org_id = cycle_check.scalar_one_or_none()
        if cycle_org_id != org_id:
            raise ForbiddenException("Access denied.")

        # Build a minimal stub for resolve_scoring_config when there is no cycle config
        class _FallbackConfig:
            exceptional_min = Decimal("120")
            exceeds_min = Decimal("100")
            meets_min = Decimal("80")
            partially_meets_min = Decimal("60")

        from app.scoring.calculator import resolve_scoring_config
        return resolve_scoring_config(target_obj, _FallbackConfig())  # type: ignore[arg-type]

    # ── Scoring preview ───────────────────────────────────────────────────────

    async def preview_scoring(
        self,
        db: AsyncSession,
        config_id: UUID,
        org_id: UUID,
        test_values: list[float],
    ) -> list[ScoringPreviewResult]:
        config = await self._get_config(db, config_id, org_id)
        effective = {
            "exceptional_min":    float(config.exceptional_min),
            "exceeds_min":        float(config.exceeds_min),
            "meets_min":          float(config.meets_min),
            "partially_meets_min": float(config.partially_meets_min),
            "achievement_cap":    float(config.achievement_cap),
            "source":             config.name,
        }
        results = []
        for v in test_values:
            rating, _ = determine_rating_with_config(Decimal(str(v)), effective)
            results.append(
                ScoringPreviewResult(
                    achievement_pct=v,
                    rating=rating.value,
                    label=_RATING_LABELS.get(rating.value, rating.value),
                )
            )
        return results

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _get_config(
        self, db: AsyncSession, config_id: UUID, org_id: UUID
    ) -> KPIScoringConfig:
        result = await db.execute(
            select(KPIScoringConfig).where(
                KPIScoringConfig.id == config_id,
                or_(
                    KPIScoringConfig.organisation_id == org_id,
                    KPIScoringConfig.is_system_preset == True,  # noqa: E712
                ),
            )
        )
        config = result.scalar_one_or_none()
        if not config:
            raise NotFoundException(
                f"Scoring config '{config_id}' not found or not accessible."
            )
        return config

    async def _validate_config_accessible(
        self, db: AsyncSession, config_id: UUID, org_id: UUID
    ) -> None:
        await self._get_config(db, config_id, org_id)

    async def _get_kpi(
        self, db: AsyncSession, kpi_id: UUID, org_id: UUID
    ) -> KPI:
        result = await db.execute(
            select(KPI).where(KPI.id == kpi_id, KPI.organisation_id == org_id)
        )
        kpi = result.scalar_one_or_none()
        if not kpi:
            raise NotFoundException(f"KPI '{kpi_id}' not found.")
        return kpi

    async def _get_target(
        self, db: AsyncSession, target_id: UUID, org_id: UUID
    ) -> KPITarget:
        # Look up via the review cycle org
        result = await db.execute(
            select(KPITarget)
            .join(KPITarget.review_cycle)
            .where(
                KPITarget.id == target_id,
            )
        )
        target = result.scalar_one_or_none()
        if not target:
            raise NotFoundException(f"Target '{target_id}' not found.")
        return target
