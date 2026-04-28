"""
Integrations router — endpoints under /api/v1/integrations.

Prefix: /integrations
Tags:   Integrations

Endpoints:
  POST  /integrations/push/{endpoint_key}     — receive pushed variable value (public, key-auth)
  GET   /integrations/adapters/               — list available adapters + their config schemas
  POST  /integrations/adapters/test           — test a source_config without saving
  GET   /integrations/variables/{kpi_id}/status — sync status for all variables
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_active_user, require_roles
from app.exceptions import NotFoundException, ValidationException
from app.integrations.adapter_registry import AdapterRegistry
from app.integrations.enums import SyncStatus, VariableSourceType
from app.integrations.models import KPIVariable, VariableActual
from app.integrations.schemas import (
    AdapterTestRequest,
    AdapterTestResult,
    VariableActualRead,
    VariableStatusRead,
    WebhookPushPayload,
)
from app.users.models import User

router = APIRouter(prefix="/integrations", tags=["Integrations"])


def _org_id(user: User) -> UUID:
    if not user.organisation_id:
        from app.exceptions import ForbiddenException
        raise ForbiddenException("User is not associated with an organisation")
    return user.organisation_id


# ---------------------------------------------------------------------------
# Webhook push — external system POSTs data to PMS
# ---------------------------------------------------------------------------

@router.post(
    "/push/{endpoint_key}",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Receive pushed variable value",
    description=(
        "Public endpoint (protected by endpoint_key token). "
        "External systems POST new values for webhook-configured variables."
    ),
)
async def receive_webhook_push(
    endpoint_key: str,
    payload: WebhookPushPayload,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    # Find the variable configured with this endpoint_key
    var_result = await db.execute(
        select(KPIVariable).where(
            KPIVariable.source_type == VariableSourceType.WEBHOOK_RECEIVE,
        )
    )
    all_webhook_vars = list(var_result.scalars().all())

    # Match endpoint_key in source_config
    variable = None
    for v in all_webhook_vars:
        if (v.source_config or {}).get("endpoint_key") == endpoint_key:
            variable = v
            break

    if variable is None:
        raise NotFoundException("Webhook endpoint not found")

    # Optional IP allowlist check
    allowed_ips = (variable.source_config or {}).get("allowed_ips", [])
    if allowed_ips:
        client_ip = request.client.host if request.client else ""
        import ipaddress
        allowed = False
        for cidr in allowed_ips:
            try:
                if ipaddress.ip_address(client_ip) in ipaddress.ip_network(cidr, strict=False):
                    allowed = True
                    break
            except ValueError:
                continue
        if not allowed:
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="IP not in allowlist")

    # Parse period
    try:
        period_date = date.fromisoformat(payload.period + "-01")
    except ValueError:
        raise ValidationException(f"Invalid period: {payload.period!r}. Use YYYY-MM.")

    # Supersede previous is_current for this variable+period
    await db.execute(
        update(VariableActual)
        .where(VariableActual.variable_id == variable.id)
        .where(VariableActual.period_date == period_date)
        .where(VariableActual.is_current.is_(True))
        .values(is_current=False)
    )

    actual = VariableActual(
        variable_id=variable.id,
        kpi_id=variable.kpi_id,
        period_date=period_date,
        raw_value=payload.value,
        source_type=VariableSourceType.WEBHOOK_RECEIVE,
        sync_metadata={
            "adapter": "webhook_receive",
            "source": payload.source,
            "extra": payload.metadata,
            "synced_at": datetime.now(timezone.utc).isoformat(),
        },
        is_current=True,
    )
    db.add(actual)

    # Update variable sync status
    variable.last_synced_at = datetime.now(timezone.utc)
    variable.last_sync_status = SyncStatus.SUCCESS
    variable.last_sync_error = None

    await db.commit()
    await db.refresh(actual)

    return {"status": "accepted", "variable_id": str(variable.id), "period": payload.period}


# ---------------------------------------------------------------------------
# Adapter discovery
# ---------------------------------------------------------------------------

@router.get(
    "/adapters/",
    summary="List available data adapters",
    description="Returns metadata and config schemas for all registered adapters.",
)
async def list_adapters(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> list[dict]:
    return AdapterRegistry.list_available()


@router.post(
    "/adapters/test",
    response_model=AdapterTestResult,
    summary="Test adapter configuration",
    description="Execute a one-off fetch to verify source_config is correct. Requires hr_admin.",
)
async def test_adapter(
    payload: AdapterTestRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles("hr_admin"))],
) -> AdapterTestResult:
    import time

    try:
        adapter = AdapterRegistry.get(payload.adapter_name)
    except ValueError as exc:
        raise ValidationException(str(exc))

    errors = adapter.validate_config(payload.source_config)
    if errors:
        return AdapterTestResult(success=False, error="; ".join(errors))

    start = time.monotonic()
    try:
        result = await adapter.fetch(payload.source_config, payload.period_date, None)
        elapsed = int((time.monotonic() - start) * 1000)
        return AdapterTestResult(
            success=result.success,
            value=result.value if result.success else None,
            error=result.error,
            metadata=result.metadata,
            elapsed_ms=elapsed,
        )
    except NotImplementedError:
        return AdapterTestResult(
            success=False,
            error="This adapter does not support pull-fetch (push-only or upload-only).",
        )
    except Exception as exc:
        elapsed = int((time.monotonic() - start) * 1000)
        return AdapterTestResult(
            success=False,
            error=str(exc),
            elapsed_ms=elapsed,
        )


# ---------------------------------------------------------------------------
# Variable sync status
# ---------------------------------------------------------------------------

@router.get(
    "/variables/{kpi_id}/status",
    response_model=list[VariableStatusRead],
    summary="Get sync status for all variables of a KPI",
)
async def get_variable_sync_status(
    kpi_id: UUID,
    period_date: str | None = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: Annotated[User, Depends(get_current_active_user)] = None,
) -> list[VariableStatusRead]:
    from sqlalchemy import select

    var_result = await db.execute(
        select(KPIVariable).where(
            KPIVariable.kpi_id == kpi_id,
            KPIVariable.organisation_id == _org_id(current_user),
        ).order_by(KPIVariable.display_order)
    )
    variables = list(var_result.scalars().all())

    parsed_period: date | None = None
    if period_date:
        try:
            parsed_period = date.fromisoformat(period_date)
        except ValueError:
            raise ValidationException(f"Invalid period_date: {period_date!r}")

    statuses = []
    for var in variables:
        has_value = False
        if parsed_period:
            actual_result = await db.execute(
                select(VariableActual).where(
                    VariableActual.variable_id == var.id,
                    VariableActual.period_date == parsed_period,
                    VariableActual.is_current.is_(True),
                ).limit(1)
            )
            has_value = actual_result.scalar_one_or_none() is not None

        statuses.append(
            VariableStatusRead(
                variable_id=var.id,
                variable_name=var.variable_name,
                source_type=var.source_type,
                last_sync_status=var.last_sync_status,
                last_synced_at=var.last_synced_at,
                has_value_for_period=has_value,
            )
        )

    return statuses
