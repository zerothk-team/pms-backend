"""
CSV Upload adapter — handles batch data uploads via CSV files.
"""

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from app.integrations.adapters.base import AdapterResult, BaseAdapter

if TYPE_CHECKING:
    from app.integrations.models import KPIVariable


class CsvUploadAdapter(BaseAdapter):
    """
    Periodic CSV upload (batch) adapter.
    Users upload a CSV file and the system extracts the appropriate value.

    source_config schema:
    {
      "adapter": "csv_upload",
      "column_name": "total_revenue",
      "date_column": "period",
      "date_format": "%Y-%m"
    }
    """

    async def fetch(
        self, config: dict, period_date: date, variable: "KPIVariable"
    ) -> AdapterResult:
        # CSV upload is handled via the upload endpoint.
        # fetch() retrieves the already-stored value for the period.
        raise NotImplementedError(
            "CsvUploadAdapter.fetch() is not applicable — values are loaded via CSV upload endpoint"
        )

    def validate_config(self, config: dict) -> list[str]:
        errors: list[str] = []
        if "column_name" not in config:
            errors.append("'column_name' is required")
        return errors

    def get_config_schema(self) -> dict:
        return {
            "fields": [
                {
                    "name": "column_name",
                    "type": "string",
                    "label": "CSV Column Name",
                    "required": True,
                    "hint": "Header name in the CSV that holds the numeric value",
                },
                {
                    "name": "date_column",
                    "type": "string",
                    "label": "Date Column",
                    "required": False,
                    "hint": "Header name for the period date column",
                },
                {
                    "name": "date_format",
                    "type": "string",
                    "label": "Date Format",
                    "required": False,
                    "default": "%Y-%m",
                    "hint": "strptime format, e.g. %Y-%m for 2025-03",
                },
            ]
        }
