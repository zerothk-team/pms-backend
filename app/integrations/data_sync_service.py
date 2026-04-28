"""
DataSyncService — orchestrates fetching variable values and computing formula actuals.

Responsibilities:
  1. Route each KPIVariable to the correct adapter
  2. Store results in variable_actuals with full metadata
  3. Handle partial failures gracefully
  4. Provide resolved variable dict to FormulaEvaluator
  5. Compute formula KPI actuals (full pipeline)
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.integrations.enums import SyncStatus, VariableSourceType
from app.integrations.models import KPIVariable, VariableActual
from app.kpis.formula import FormulaEvaluator, FormulaParser, MissingVariableError

if TYPE_CHECKING:
    from app.kpis.models import KPI


class DataSyncService:
    """
    Orchestrates fetching variable values from external sources and storing
    them in variable_actuals.
    """

    def __init__(self) -> None:
        self.evaluator = FormulaEvaluator()

    # ------------------------------------------------------------------
    # Public: sync a single variable
    # ------------------------------------------------------------------

    async def sync_variable(
        self,
        db: AsyncSession,
        variable: KPIVariable,
        period_date: date,
    ) -> VariableActual:
        """
        Fetch the current value for one variable from its configured source.
        Marks any previous value for this period as is_current=False before inserting.

        Raises:
            ValueError: If variable source type cannot be auto-synced.
        """
        if variable.source_type == VariableSourceType.MANUAL:
            raise ValueError("Manual variables cannot be auto-synced")
        if variable.source_type == VariableSourceType.WEBHOOK_RECEIVE:
            raise ValueError("Webhook variables are push-only and cannot be pulled")

        from app.integrations.adapter_registry import AdapterRegistry

        adapter_name = (variable.source_config or {}).get("adapter", variable.source_type.value)
        adapter = AdapterRegistry.get(adapter_name)

        # KPI_ACTUAL source is handled specially — we query the DB
        if variable.source_type == VariableSourceType.KPI_ACTUAL:
            result = await self._fetch_via_kpi_actual_adapter(db, variable, period_date)
        else:
            result = await adapter.fetch(variable.source_config or {}, period_date, variable)

        # Supersede previous is_current values for this variable+period
        await db.execute(
            update(VariableActual)
            .where(VariableActual.variable_id == variable.id)
            .where(VariableActual.period_date == period_date)
            .where(VariableActual.is_current.is_(True))
            .values(is_current=False)
        )

        value = result.value if result.success else (
            variable.default_value or Decimal("0")
        )

        actual = VariableActual(
            variable_id=variable.id,
            kpi_id=variable.kpi_id,
            period_date=period_date,
            raw_value=value,
            source_type=variable.source_type,
            sync_metadata=result.metadata,
            is_current=True,
        )
        db.add(actual)

        # Update variable sync status
        variable.last_synced_at = datetime.now(timezone.utc)
        variable.last_sync_status = SyncStatus.SUCCESS if result.success else SyncStatus.FAILED
        variable.last_sync_error = result.error

        await db.flush()
        await db.refresh(actual)
        return actual

    # ------------------------------------------------------------------
    # Public: sync all auto-sync-enabled variables for a KPI
    # ------------------------------------------------------------------

    async def sync_all_auto_variables_for_kpi(
        self,
        db: AsyncSession,
        kpi_id: UUID,
        period_date: date,
    ) -> dict[str, VariableActual]:
        """
        Sync all non-manual, non-webhook variables for a KPI that have auto_sync_enabled=True.
        Returns mapping: {"REVENUE": VariableActual, ...}

        Failures are logged and skipped (partial success allowed).
        """
        import logging

        logger = logging.getLogger(__name__)
        variables = await self._get_kpi_variables(db, kpi_id)
        results: dict[str, VariableActual] = {}

        skip_types = {VariableSourceType.MANUAL, VariableSourceType.WEBHOOK_RECEIVE}
        for var in variables:
            if var.source_type in skip_types or not var.auto_sync_enabled:
                continue
            try:
                actual = await self.sync_variable(db, var, period_date)
                results[var.variable_name] = actual
            except Exception as exc:
                logger.warning(
                    "sync_variable failed for variable=%s kpi=%s period=%s: %s",
                    var.variable_name, kpi_id, period_date, exc,
                )

        return results

    # ------------------------------------------------------------------
    # Public: get resolved values for all variables
    # ------------------------------------------------------------------

    async def get_resolved_values(
        self,
        db: AsyncSession,
        kpi_id: UUID,
        period_date: date,
    ) -> dict[str, Decimal]:
        """
        Get current values for ALL variables of a KPI for a given period.
        Returns a dict ready for FormulaEvaluator: {"REVENUE": Decimal("1200000"), ...}

        Raises:
            MissingVariableError: if a required variable has no value for the period.
        """
        variables = await self._get_kpi_variables(db, kpi_id)
        resolved: dict[str, Decimal] = {}
        missing_required: list[str] = []

        for var in variables:
            actual = await self._get_latest_actual(db, var.id, period_date)
            if actual is not None:
                resolved[var.variable_name] = Decimal(str(actual.raw_value))
            elif not var.is_required and var.default_value is not None:
                resolved[var.variable_name] = Decimal(str(var.default_value))
            elif var.is_required:
                missing_required.append(var.variable_name)

        if missing_required:
            raise MissingVariableError(
                f"Required variables missing for period {period_date}: "
                + ", ".join(missing_required)
            )

        return resolved

    # ------------------------------------------------------------------
    # Public: full formula pipeline
    # ------------------------------------------------------------------

    async def compute_formula_actual(
        self,
        db: AsyncSession,
        kpi: "KPI",
        period_date: date,
        trigger_source: str = "manual",
    ) -> Decimal:
        """
        Full pipeline:
          1. Auto-sync all non-manual variables
          2. Get all resolved variable values (manual + synced)
          3. Evaluate formula expression
          4. Return computed KPI actual value

        Single entry point for computing formula KPI actual values.

        Raises:
            ValueError:           If the KPI is not a formula KPI.
            MissingVariableError: If a required variable has no value.
            EvaluationError:      If formula evaluation fails.
        """
        from app.kpis.enums import DataSourceType

        if kpi.data_source != DataSourceType.FORMULA:
            raise ValueError(f"KPI {kpi.code!r} is not a formula KPI")

        await self.sync_all_auto_variables_for_kpi(db, kpi.id, period_date)

        resolved_values = await self.get_resolved_values(db, kpi.id, period_date)

        decimal_places = getattr(kpi, "decimal_places", 4) or 4
        return self.evaluator.evaluate(
            expression=kpi.formula_expression,
            variables=resolved_values,
            decimal_places=decimal_places,
        )

    # ------------------------------------------------------------------
    # Public: validate formula expression against defined variables
    # ------------------------------------------------------------------

    async def validate_formula_with_variables(
        self,
        db: AsyncSession,
        kpi_id: UUID,
        expression: str,
    ) -> dict:
        """
        Full validation: syntax + variable existence check.
        Returns:
            {
                "valid": bool,
                "errors": list[str],
                "referenced_variables": list[str],
                "defined_variables": list[str],
                "undefined_in_formula": list[str],
            }
        """
        parser = FormulaParser()
        errors = parser.validate_syntax(expression)

        variables = await self._get_kpi_variables(db, kpi_id)
        variable_names = [v.variable_name for v in variables]
        errors += parser.validate_variables_exist(expression, variable_names)

        referenced = parser.extract_variable_names(expression)
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "referenced_variables": referenced,
            "defined_variables": variable_names,
            "undefined_in_formula": [n for n in referenced if n not in set(variable_names)],
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_kpi_variables(
        self, db: AsyncSession, kpi_id: UUID
    ) -> list[KPIVariable]:
        result = await db.execute(
            select(KPIVariable)
            .where(KPIVariable.kpi_id == kpi_id)
            .order_by(KPIVariable.display_order)
        )
        return list(result.scalars().all())

    async def _get_latest_actual(
        self, db: AsyncSession, variable_id: UUID, period_date: date
    ) -> VariableActual | None:
        result = await db.execute(
            select(VariableActual)
            .where(
                VariableActual.variable_id == variable_id,
                VariableActual.period_date == period_date,
                VariableActual.is_current.is_(True),
            )
            .order_by(VariableActual.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _fetch_via_kpi_actual_adapter(
        self,
        db: AsyncSession,
        variable: KPIVariable,
        period_date: date,
    ):
        """
        Pull the latest approved actual from another KPI (KPI_ACTUAL source type).
        Inline DB query used here because the adapter itself cannot access the session.
        """
        from decimal import Decimal as _Dec
        from datetime import datetime as _dt, timezone as _tz

        from app.actuals.enums import ActualEntryStatus
        from app.actuals.models import KPIActual
        from app.integrations.adapters.base import AdapterResult
        from app.kpis.models import KPI

        config = variable.source_config or {}
        kpi_code = config.get("kpi_code")
        if not kpi_code:
            return AdapterResult(
                value=_Dec("0"), metadata={}, success=False, error="kpi_code not set in config"
            )

        # Find the referenced KPI in the same org
        kpi_result = await db.execute(
            select(KPI).where(
                KPI.code == kpi_code,
                KPI.organisation_id == variable.organisation_id,
            )
        )
        dep_kpi = kpi_result.scalar_one_or_none()
        if dep_kpi is None:
            return AdapterResult(
                value=_Dec("0"),
                metadata={},
                success=False,
                error=f"KPI with code '{kpi_code}' not found",
            )

        # Find the most recent approved actual for that KPI up to period_date
        actual_result = await db.execute(
            select(KPIActual)
            .where(
                KPIActual.kpi_id == dep_kpi.id,
                KPIActual.period_date <= period_date,
                KPIActual.status == ActualEntryStatus.APPROVED,
            )
            .order_by(KPIActual.period_date.desc())
            .limit(1)
        )
        actual = actual_result.scalar_one_or_none()
        if actual is None:
            return AdapterResult(
                value=_Dec("0"),
                metadata={},
                success=False,
                error=f"No approved actual found for KPI '{kpi_code}'",
            )

        return AdapterResult(
            value=_Dec(str(actual.actual_value)),
            metadata={
                "adapter": "kpi_actual",
                "kpi_code": kpi_code,
                "period": str(actual.period_date),
                "synced_at": _dt.now(_tz.utc).isoformat(),
            },
            success=True,
        )
