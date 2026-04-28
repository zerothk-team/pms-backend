"""
integrations/adapters/base.py — Base class for all data source adapters.

Adapter contract:
  1. fetch(config, period_date, variable) → AdapterResult
     - Must be async
     - Must handle its own errors (return AdapterResult(success=False) on failure)
     - Must be idempotent (calling twice for same period returns same value)
     - Must respect timeout settings from config
     - Must NOT log resolved secrets

  2. validate_config(config) → list[str]
     - Called before saving a KPIVariable
     - Returns empty list if valid, list of error messages if invalid
     - Must verify {SECRET:KEY} references are used for credentials

  3. get_config_schema() → dict
     - Returns JSON Schema used by frontend AdapterConfigForm
     - Drives dynamic form rendering — no hardcoded forms per adapter type

Adding new adapters:
  1. Create class inheriting BaseAdapter in app/integrations/adapters/
  2. Implement all three methods
  3. Register in adapter_registry.py:
       AdapterRegistry.register("my_adapter", MyAdapter)
  No other changes needed — the registry handles discovery.

Built-in adapters:
  rest_api:         HTTP GET/POST to any JSON endpoint
  database:         Direct SQL SELECT query (PostgreSQL, MySQL, MSSQL)
  influxdb:         InfluxDB Flux query for IoT/time-series
  webhook_receive:  External system pushes data to PMS
  kpi_actual:       Pull latest actual from another KPI in same org
  csv_upload:       Batch upload via CSV file
"""

import copy
import os
import re
from abc import ABC, abstractmethod
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.integrations.models import KPIVariable


class AdapterResult:
    """Standardised result from any adapter fetch."""

    def __init__(
        self,
        value: Decimal,
        metadata: dict,
        success: bool = True,
        error: str | None = None,
    ):
        self.value = value
        self.metadata = metadata
        self.success = success
        self.error = error


class BaseAdapter(ABC):

    @abstractmethod
    async def fetch(
        self,
        config: dict,
        period_date: date,
        variable: "KPIVariable",
    ) -> AdapterResult:
        """
        Pull a single numeric value for the given period.
        Must be idempotent — calling twice returns same value.
        Must handle its own timeouts and errors, returning AdapterResult with success=False.
        """
        ...

    @abstractmethod
    def validate_config(self, config: dict) -> list[str]:
        """
        Validate source_config dict for this adapter.
        Returns list of error messages (empty = valid).
        Called before saving a KPIVariable to prevent bad configs.
        """
        ...

    @abstractmethod
    def get_config_schema(self) -> dict:
        """
        Return JSON Schema for this adapter's source_config.
        Used by frontend to render a dynamic config form.
        """
        ...

    # ── Shared utilities ─────────────────────────────────────────────────────

    def resolve_secrets(self, config: dict) -> dict:
        """
        Replace {SECRET:KEY_NAME} placeholders with actual values.
        Reads from environment variables: PMS_SECRET_KEY_NAME.
        NEVER logs the resolved values.
        """
        SECRET_PATTERN = re.compile(r'\{SECRET:([A-Z0-9_]+)\}')

        def _resolve_value(val: Any) -> Any:
            if isinstance(val, str):
                def _replacer(m: re.Match) -> str:
                    key = m.group(1)
                    env_key = f"PMS_SECRET_{key}"
                    resolved = os.environ.get(env_key)
                    if resolved is None:
                        raise ValueError(
                            f"Secret '{key}' not found in environment "
                            f"(expected env var: {env_key})"
                        )
                    return resolved

                return SECRET_PATTERN.sub(_replacer, val)
            elif isinstance(val, dict):
                return {k: _resolve_value(v) for k, v in val.items()}
            elif isinstance(val, list):
                return [_resolve_value(item) for item in val]
            return val

        return _resolve_value(copy.deepcopy(config))

    def resolve_period_params(self, template: str, period_date: date) -> str:
        """
        Replace period placeholders in URL or query strings.
        Supported: {period.year}, {period.month}, {period.month_padded},
                   {period.quarter}, {period.start_date}, {period.end_date}
        """
        import calendar

        last_day = calendar.monthrange(period_date.year, period_date.month)[1]
        replacements = {
            "{period.year}": str(period_date.year),
            "{period.month}": str(period_date.month),
            "{period.month_padded}": f"{period_date.month:02d}",
            "{period.quarter}": str((period_date.month - 1) // 3 + 1),
            "{period.start_date}": period_date.replace(day=1).isoformat(),
            "{period.end_date}": period_date.replace(day=last_day).isoformat(),
            "{period.iso}": period_date.strftime("%Y-%m"),
        }
        result = template
        for placeholder, value in replacements.items():
            result = result.replace(placeholder, value)
        return result

    def extract_json_path(self, data: Any, json_path: str) -> Any:
        """
        Simple dot-notation + array-index JSONPath extractor.
        Supports: "data.total", "results[0].amount", "data.metrics.revenue"
        Does NOT support wildcards or filter expressions.
        """
        parts = re.split(r'\.|\[(\d+)\]', json_path)
        current = data
        for part in filter(None, parts):
            if part.isdigit():
                current = current[int(part)]
            elif isinstance(current, dict):
                current = current[part]
            else:
                raise ValueError(
                    f"Cannot navigate path '{json_path}' at segment '{part}'"
                )
        return current
