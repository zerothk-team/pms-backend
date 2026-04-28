"""
KPI Actual adapter — pulls latest approved actual from another KPI in the same org.
Maintains backward compatibility with the original formula design.
"""

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from app.integrations.adapters.base import AdapterResult, BaseAdapter

if TYPE_CHECKING:
    from app.integrations.models import KPIVariable


class KPIActualAdapter(BaseAdapter):
    """
    Pull the latest approved actual from another KPI in the same org.

    source_config schema:
    {
      "adapter": "kpi_actual",
      "kpi_code": "SALES_REVENUE_GROWTH",
      "aggregation": "latest"
    }
    """

    async def fetch(
        self, config: dict, period_date: date, variable: "KPIVariable"
    ) -> AdapterResult:
        """
        Fetch is handled by DataSyncService which injects the DB session.
        This method is a stub — override in DataSyncService.
        """
        raise NotImplementedError(
            "KPIActualAdapter.fetch() must be called via DataSyncService which injects the db session"
        )

    def validate_config(self, config: dict) -> list[str]:
        errors: list[str] = []
        if "kpi_code" not in config:
            errors.append("'kpi_code' is required")
        return errors

    def get_config_schema(self) -> dict:
        return {
            "fields": [
                {
                    "name": "kpi_code",
                    "type": "string",
                    "label": "Source KPI Code",
                    "required": True,
                    "hint": "Code of the KPI to pull actual value from",
                },
                {
                    "name": "aggregation",
                    "type": "select",
                    "label": "Aggregation",
                    "required": False,
                    "options": ["latest", "sum", "average", "max", "min"],
                    "default": "latest",
                },
            ]
        }
