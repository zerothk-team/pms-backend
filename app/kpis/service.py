"""
KPIService — all business logic for the KPI module.

Handles: categories, tags, KPI CRUD, status transitions, formula validation,
template management, and version history.
"""

import math
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.exceptions import BadRequestException, ConflictException, NotFoundException
from app.kpis.enums import (
    DataSourceType,
    DepartmentCategory,
    KPIStatus,
)
from app.kpis.formula import (
    CircularDependencyError,
    FormulaDependencyResolver,
    FormulaEvaluator,
    FormulaParser,
    FormulaValidationError,
)
from app.kpis.models import KPI, KPICategory, KPIHistory, KPITag, KPITemplate
from app.kpis.schemas import (
    FormulaValidationResponse,
    KPICategoryCreate,
    KPICategoryUpdate,
    KPICloneFromTemplate,
    KPICreate,
    KPIStatusUpdate,
    KPIUpdate,
    PaginatedKPIs,
)


# ---------------------------------------------------------------------------
# Valid status transitions
# ---------------------------------------------------------------------------

# Maps current status → set of statuses any user can transition to
_TRANSITIONS: dict[KPIStatus, set[KPIStatus]] = {
    KPIStatus.DRAFT: {KPIStatus.PENDING_APPROVAL, KPIStatus.ACTIVE},
    KPIStatus.PENDING_APPROVAL: {KPIStatus.ACTIVE, KPIStatus.DRAFT},
    KPIStatus.ACTIVE: {KPIStatus.DEPRECATED},
    KPIStatus.DEPRECATED: {KPIStatus.ARCHIVED},
    KPIStatus.ARCHIVED: set(),
}

# hr_admin can also reset anything back to DRAFT
_HR_ADMIN_EXTRA: set[KPIStatus] = {KPIStatus.DRAFT}


def _allowed_next_statuses(current: KPIStatus, is_hr_admin: bool) -> set[KPIStatus]:
    allowed = _TRANSITIONS.get(current, set()).copy()
    if is_hr_admin:
        allowed |= _HR_ADMIN_EXTRA
    return allowed


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _kpi_snapshot(kpi: KPI) -> dict:
    """Return a JSON-serialisable snapshot of the KPI's core fields."""
    return {
        "id": str(kpi.id),
        "name": kpi.name,
        "code": kpi.code,
        "description": kpi.description,
        "unit": kpi.unit.value,
        "unit_label": kpi.unit_label,
        "currency_code": kpi.currency_code,
        "frequency": kpi.frequency.value,
        "data_source": kpi.data_source.value,
        "formula_expression": kpi.formula_expression,
        "scoring_direction": kpi.scoring_direction.value,
        "min_value": str(kpi.min_value) if kpi.min_value is not None else None,
        "max_value": str(kpi.max_value) if kpi.max_value is not None else None,
        "decimal_places": kpi.decimal_places,
        "status": kpi.status.value,
        "version": kpi.version,
        "category_id": str(kpi.category_id) if kpi.category_id else None,
        "organisation_id": str(kpi.organisation_id),
        "created_by_id": str(kpi.created_by_id),
        "approved_by_id": str(kpi.approved_by_id) if kpi.approved_by_id else None,
    }


def _kpi_load_options():
    """Standard eager-load options for KPI queries."""
    return [
        selectinload(KPI.category),
        selectinload(KPI.tags),
        selectinload(KPI.formula_dependencies),
    ]


async def _get_kpi_or_404(db: AsyncSession, kpi_id: UUID, org_id: UUID) -> KPI:
    result = await db.execute(
        select(KPI)
        .where(KPI.id == kpi_id, KPI.organisation_id == org_id)
        .options(*_kpi_load_options())
    )
    kpi = result.scalar_one_or_none()
    if not kpi:
        raise NotFoundException(f"KPI '{kpi_id}' not found")
    return kpi


# ---------------------------------------------------------------------------
# KPIService
# ---------------------------------------------------------------------------

class KPIService:

    # -----------------------------------------------------------------------
    # Category methods
    # -----------------------------------------------------------------------

    async def create_category(
        self,
        db: AsyncSession,
        org_id: UUID,
        user_id: UUID,
        data: KPICategoryCreate,
    ) -> KPICategory:
        category = KPICategory(
            name=data.name,
            description=data.description,
            department=data.department,
            colour_hex=data.colour_hex,
            organisation_id=org_id,
            created_by_id=user_id,
        )
        db.add(category)
        await db.flush()
        await db.refresh(category)
        return category

    async def list_categories(
        self,
        db: AsyncSession,
        org_id: UUID,
    ) -> list[KPICategory]:
        result = await db.execute(
            select(KPICategory).where(
                (KPICategory.organisation_id == org_id)
                | (KPICategory.organisation_id.is_(None))
            ).order_by(KPICategory.name)
        )
        return list(result.scalars().all())

    async def update_category(
        self,
        db: AsyncSession,
        category_id: UUID,
        org_id: UUID,
        data: KPICategoryUpdate,
    ) -> KPICategory:
        result = await db.execute(
            select(KPICategory).where(
                KPICategory.id == category_id,
                KPICategory.organisation_id == org_id,
            )
        )
        category = result.scalar_one_or_none()
        if not category:
            raise NotFoundException(f"Category '{category_id}' not found")

        if data.name is not None:
            category.name = data.name
        if data.description is not None:
            category.description = data.description
        if data.colour_hex is not None:
            category.colour_hex = data.colour_hex

        category.updated_at = datetime.now(timezone.utc)
        await db.flush()
        await db.refresh(category)
        return category

    async def delete_category(
        self,
        db: AsyncSession,
        category_id: UUID,
        org_id: UUID,
    ) -> None:
        result = await db.execute(
            select(KPICategory).where(
                KPICategory.id == category_id,
                KPICategory.organisation_id == org_id,
            )
        )
        category = result.scalar_one_or_none()
        if not category:
            raise NotFoundException(f"Category '{category_id}' not found")

        # Reject if KPIs are still attached
        kpi_count_result = await db.execute(
            select(func.count()).select_from(KPI).where(KPI.category_id == category_id)
        )
        kpi_count = kpi_count_result.scalar_one()
        if kpi_count > 0:
            raise BadRequestException(
                f"Cannot delete category: {kpi_count} KPI(s) are still assigned to it"
            )
        await db.delete(category)
        await db.flush()

    # -----------------------------------------------------------------------
    # Tag methods
    # -----------------------------------------------------------------------

    async def get_or_create_tag(
        self,
        db: AsyncSession,
        name: str,
        org_id: UUID,
    ) -> KPITag:
        result = await db.execute(
            select(KPITag).where(KPITag.name == name, KPITag.organisation_id == org_id)
        )
        tag = result.scalar_one_or_none()
        if tag:
            return tag
        tag = KPITag(name=name, organisation_id=org_id)
        db.add(tag)
        await db.flush()
        await db.refresh(tag)
        return tag

    async def list_tags(self, db: AsyncSession, org_id: UUID) -> list[KPITag]:
        result = await db.execute(
            select(KPITag).where(KPITag.organisation_id == org_id).order_by(KPITag.name)
        )
        return list(result.scalars().all())

    # -----------------------------------------------------------------------
    # KPI CRUD
    # -----------------------------------------------------------------------

    async def create_kpi(
        self,
        db: AsyncSession,
        org_id: UUID,
        user_id: UUID,
        data: KPICreate,
    ) -> KPI:
        # 1. Validate code uniqueness within org
        existing = await db.execute(
            select(KPI).where(KPI.organisation_id == org_id, KPI.code == data.code)
        )
        if existing.scalar_one_or_none():
            raise ConflictException(f"A KPI with code '{data.code}' already exists in this organisation")

        # 2. Formula validation
        dep_kpis: list[KPI] = []
        if data.data_source == DataSourceType.FORMULA and data.formula_expression:
            dep_kpis = await self._validate_and_resolve_formula(
                db, org_id, data.formula_expression, exclude_kpi_id=None
            )

        # 3. Resolve tags
        tags: list[KPITag] = []
        for tag_id in data.tag_ids:
            tag_result = await db.execute(
                select(KPITag).where(KPITag.id == tag_id, KPITag.organisation_id == org_id)
            )
            tag = tag_result.scalar_one_or_none()
            if not tag:
                raise NotFoundException(f"Tag '{tag_id}' not found")
            tags.append(tag)

        # 4. Create KPI
        kpi = KPI(
            name=data.name,
            code=data.code,
            description=data.description,
            unit=data.unit,
            unit_label=data.unit_label,
            currency_code=data.currency_code,
            frequency=data.frequency,
            data_source=data.data_source,
            formula_expression=data.formula_expression,
            scoring_direction=data.scoring_direction,
            min_value=data.min_value,
            max_value=data.max_value,
            decimal_places=data.decimal_places,
            status=KPIStatus.DRAFT,
            is_organisation_wide=data.is_organisation_wide,
            category_id=data.category_id,
            organisation_id=org_id,
            created_by_id=user_id,
            version=1,
        )
        kpi.tags = tags
        kpi.formula_dependencies = dep_kpis
        db.add(kpi)
        await db.flush()

        # 5. Create initial history entry
        history = KPIHistory(
            kpi_id=kpi.id,
            version=1,
            change_summary="Initial creation",
            snapshot=_kpi_snapshot(kpi),
            changed_by_id=user_id,
        )
        db.add(history)
        await db.flush()
        await db.refresh(kpi)

        # Reload with relationships
        return await _get_kpi_or_404(db, kpi.id, org_id)

    async def get_kpi_by_id(self, db: AsyncSession, kpi_id: UUID, org_id: UUID) -> KPI:
        return await _get_kpi_or_404(db, kpi_id, org_id)

    async def get_kpi_by_code(self, db: AsyncSession, code: str, org_id: UUID) -> KPI | None:
        result = await db.execute(
            select(KPI)
            .where(KPI.code == code, KPI.organisation_id == org_id)
            .options(*_kpi_load_options())
        )
        return result.scalar_one_or_none()

    async def list_kpis(
        self,
        db: AsyncSession,
        org_id: UUID,
        page: int = 1,
        size: int = 20,
        status: KPIStatus | None = None,
        category_id: UUID | None = None,
        department: DepartmentCategory | None = None,
        data_source: DataSourceType | None = None,
        tag_ids: list[UUID] | None = None,
        search: str | None = None,
        created_by_id: UUID | None = None,
    ) -> PaginatedKPIs:
        query = select(KPI).where(KPI.organisation_id == org_id)

        if status:
            query = query.where(KPI.status == status)
        if category_id:
            query = query.where(KPI.category_id == category_id)
        if data_source:
            query = query.where(KPI.data_source == data_source)
        if created_by_id:
            query = query.where(KPI.created_by_id == created_by_id)
        if search:
            pattern = f"%{search}%"
            query = query.where(
                KPI.name.ilike(pattern) | KPI.description.ilike(pattern)
            )
        if department:
            query = query.join(KPI.category).where(KPICategory.department == department)
        if tag_ids:
            from app.kpis.models import kpi_tag_association
            for tid in tag_ids:
                query = query.where(
                    KPI.id.in_(
                        select(kpi_tag_association.c.kpi_id).where(
                            kpi_tag_association.c.tag_id == tid
                        )
                    )
                )

        # Count total
        count_result = await db.execute(select(func.count()).select_from(query.subquery()))
        total = count_result.scalar_one()

        # Paginate
        offset = (page - 1) * size
        query = query.options(*_kpi_load_options()).order_by(KPI.created_at.desc()).offset(offset).limit(size)
        result = await db.execute(query)
        items = list(result.scalars().all())

        pages = math.ceil(total / size) if size else 1
        return PaginatedKPIs(items=items, total=total, page=page, size=size, pages=pages)

    async def update_kpi(
        self,
        db: AsyncSession,
        kpi_id: UUID,
        org_id: UUID,
        user_id: UUID,
        data: KPIUpdate,
    ) -> KPI:
        kpi = await _get_kpi_or_404(db, kpi_id, org_id)

        # Snapshot old state before making changes
        old_snapshot = _kpi_snapshot(kpi)

        formula_changed = data.formula_expression is not None and data.formula_expression != kpi.formula_expression

        if formula_changed and not data.change_summary:
            raise BadRequestException("change_summary is required when modifying formula_expression")

        # Re-validate formula if changed
        dep_kpis: list[KPI] | None = None
        if formula_changed:
            if data.formula_expression:
                dep_kpis = await self._validate_and_resolve_formula(
                    db, org_id, data.formula_expression, exclude_kpi_id=kpi_id
                )
            else:
                dep_kpis = []

        # Apply changes
        if data.name is not None:
            kpi.name = data.name
        if data.description is not None:
            kpi.description = data.description
        if formula_changed:
            kpi.formula_expression = data.formula_expression
            kpi.formula_dependencies = dep_kpis or []
        if data.scoring_direction is not None:
            kpi.scoring_direction = data.scoring_direction
        if data.min_value is not None:
            kpi.min_value = data.min_value
        if data.max_value is not None:
            kpi.max_value = data.max_value
        if data.decimal_places is not None:
            kpi.decimal_places = data.decimal_places
        if data.category_id is not None:
            kpi.category_id = data.category_id
        if data.tag_ids is not None:
            tags = []
            for tag_id in data.tag_ids:
                tag_result = await db.execute(
                    select(KPITag).where(KPITag.id == tag_id, KPITag.organisation_id == org_id)
                )
                tag = tag_result.scalar_one_or_none()
                if not tag:
                    raise NotFoundException(f"Tag '{tag_id}' not found")
                tags.append(tag)
            kpi.tags = tags

        kpi.version += 1
        kpi.updated_at = datetime.now(timezone.utc)

        # Save history
        history = KPIHistory(
            kpi_id=kpi.id,
            version=kpi.version,
            change_summary=data.change_summary or "Updated",
            snapshot=old_snapshot,
            changed_by_id=user_id,
        )
        db.add(history)
        await db.flush()
        return await _get_kpi_or_404(db, kpi.id, org_id)

    async def update_kpi_status(
        self,
        db: AsyncSession,
        kpi_id: UUID,
        org_id: UUID,
        user_id: UUID,
        data: KPIStatusUpdate,
        is_hr_admin: bool = False,
    ) -> KPI:
        kpi = await _get_kpi_or_404(db, kpi_id, org_id)
        allowed = _allowed_next_statuses(kpi.status, is_hr_admin)

        if data.status not in allowed:
            raise BadRequestException(
                f"Cannot transition from '{kpi.status.value}' to '{data.status.value}'. "
                f"Allowed next statuses: {[s.value for s in allowed] or 'none'}"
            )

        # PENDING_APPROVAL → ACTIVE requires hr_admin
        if (
            kpi.status == KPIStatus.PENDING_APPROVAL
            and data.status == KPIStatus.ACTIVE
            and not is_hr_admin
        ):
            raise BadRequestException("Only hr_admin can approve a KPI from PENDING_APPROVAL to ACTIVE")

        now = datetime.now(timezone.utc)
        kpi.status = data.status
        if data.status == KPIStatus.ACTIVE and kpi.status != KPIStatus.ACTIVE:
            kpi.approved_by_id = user_id
            kpi.approved_at = now
        if data.status == KPIStatus.DEPRECATED:
            kpi.deprecated_at = now

        kpi.updated_at = now
        await db.flush()
        return await _get_kpi_or_404(db, kpi.id, org_id)

    async def get_kpi_history(
        self, db: AsyncSession, kpi_id: UUID, org_id: UUID
    ) -> list[KPIHistory]:
        # Verify KPI belongs to org
        await _get_kpi_or_404(db, kpi_id, org_id)
        result = await db.execute(
            select(KPIHistory)
            .where(KPIHistory.kpi_id == kpi_id)
            .order_by(KPIHistory.version)
        )
        return list(result.scalars().all())

    # -----------------------------------------------------------------------
    # Template methods
    # -----------------------------------------------------------------------

    async def list_templates(
        self,
        db: AsyncSession,
        department: DepartmentCategory | None = None,
        search: str | None = None,
    ) -> list[KPITemplate]:
        query = select(KPITemplate).where(KPITemplate.is_active.is_(True))
        if department:
            query = query.where(KPITemplate.department == department)
        if search:
            pattern = f"%{search}%"
            query = query.where(
                KPITemplate.name.ilike(pattern) | KPITemplate.description.ilike(pattern)
            )
        result = await db.execute(query.order_by(KPITemplate.name))
        return list(result.scalars().all())

    async def clone_from_template(
        self,
        db: AsyncSession,
        org_id: UUID,
        user_id: UUID,
        data: KPICloneFromTemplate,
    ) -> KPI:
        tmpl_result = await db.execute(
            select(KPITemplate).where(KPITemplate.id == data.template_id, KPITemplate.is_active.is_(True))
        )
        template = tmpl_result.scalar_one_or_none()
        if not template:
            raise NotFoundException(f"Template '{data.template_id}' not found")

        create_data = KPICreate(
            name=data.name or template.name,
            code=data.code,
            description=template.description,
            unit=template.unit,
            frequency=template.frequency,
            data_source=DataSourceType.FORMULA if template.suggested_formula else DataSourceType.MANUAL,
            formula_expression=template.suggested_formula or None,
            scoring_direction=template.scoring_direction,
            category_id=data.category_id,
        )

        kpi = await self.create_kpi(db, org_id, user_id, create_data)

        # Increment usage count
        template.usage_count += 1
        await db.flush()

        return kpi

    async def promote_to_template(
        self, db: AsyncSession, kpi_id: UUID, org_id: UUID
    ) -> KPI:
        kpi = await _get_kpi_or_404(db, kpi_id, org_id)
        kpi.is_template = True
        kpi.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return await _get_kpi_or_404(db, kpi.id, org_id)

    # -----------------------------------------------------------------------
    # Formula utilities
    # -----------------------------------------------------------------------

    async def validate_formula_expression(
        self, db: AsyncSession, org_id: UUID, expression: str
    ) -> FormulaValidationResponse:
        parser = FormulaParser()
        errors: list[str] = []
        referenced_codes: list[str] = []

        try:
            parser.validate_syntax(expression)
            referenced_codes = parser.extract_kpi_references(expression)
        except FormulaValidationError as exc:
            errors.append(exc.detail)
            return FormulaValidationResponse(valid=False, referenced_codes=[], errors=errors)

        # Verify all referenced codes exist in org
        for code in referenced_codes:
            result = await db.execute(
                select(KPI).where(KPI.code == code, KPI.organisation_id == org_id)
            )
            if not result.scalar_one_or_none():
                errors.append(f"KPI code '{code}' does not exist in this organisation")

        return FormulaValidationResponse(
            valid=len(errors) == 0,
            referenced_codes=referenced_codes,
            errors=errors,
        )

    async def evaluate_formula_for_kpi(
        self, db: AsyncSession, kpi_id: UUID, org_id: UUID, period_date: date
    ) -> Decimal:
        """
        Recursively resolve formula dependencies and evaluate the formula.

        Note: This method requires actual period values from the actuals module
        (Part 3). Until then it raises a NotImplementedError with guidance.
        """
        kpi = await _get_kpi_or_404(db, kpi_id, org_id)
        if kpi.data_source != DataSourceType.FORMULA or not kpi.formula_expression:
            raise BadRequestException(f"KPI '{kpi.code}' does not use a formula")

        # TODO(Part 3): Fetch actual values for each dependency for the given period_date
        # and recursively resolve nested formulas. Placeholder raises until actuals exist.
        raise NotImplementedError(
            "Formula evaluation requires actuals data (implemented in Part 3). "
            "Use the /validate-formula endpoint to test formula syntax."
        )

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    async def _validate_and_resolve_formula(
        self,
        db: AsyncSession,
        org_id: UUID,
        expression: str,
        exclude_kpi_id: UUID | None,
    ) -> list[KPI]:
        """
        Validate formula syntax, verify referenced KPI codes exist, and check
        for circular dependencies.

        Returns the list of dependency KPI objects.
        """
        parser = FormulaParser()
        try:
            parser.validate_syntax(expression)
        except FormulaValidationError:
            raise

        referenced_codes = parser.extract_kpi_references(expression)
        dep_kpis: list[KPI] = []

        for code in referenced_codes:
            result = await db.execute(
                select(KPI)
                .where(KPI.code == code, KPI.organisation_id == org_id)
                .options(*_kpi_load_options())
            )
            dep = result.scalar_one_or_none()
            if not dep:
                from app.kpis.formula import FormulaValidationError as FVE
                raise FVE(f"Referenced KPI code '{code}' does not exist in this organisation")
            if exclude_kpi_id and dep.id == exclude_kpi_id:
                raise CircularDependencyError(
                    f"KPI cannot reference itself (code: {code})"
                )
            dep_kpis.append(dep)

        # Check for circular dependencies using DFS on the in-memory graph
        if dep_kpis and exclude_kpi_id:
            # Build a temporary in-memory graph treating the being-created/updated KPI
            # as if it already existed with the new dependencies
            all_accessible = list(dep_kpis)

            # Collect transitive deps already in the system
            visited_ids: set[UUID] = set()
            queue = list(dep_kpis)
            while queue:
                item = queue.pop()
                if item.id in visited_ids:
                    continue
                visited_ids.add(item.id)
                for sub_dep in (item.formula_dependencies or []):
                    if sub_dep.id not in visited_ids:
                        all_accessible.append(sub_dep)
                        queue.append(sub_dep)

            resolver = FormulaDependencyResolver()

            # Temporarily build a fake KPI object-like structure for graph building
            class _FakeKPI:
                def __init__(self, kpi_id: UUID, deps: list) -> None:
                    self.id = kpi_id
                    self.formula_dependencies = deps

            fake_kpi = _FakeKPI(exclude_kpi_id, dep_kpis)
            all_for_graph = all_accessible + [fake_kpi]  # type: ignore[list-item]
            graph = resolver.build_dependency_graph(exclude_kpi_id, all_for_graph)  # type: ignore[arg-type]
            resolver.detect_cycle(graph, exclude_kpi_id)

        return dep_kpis
