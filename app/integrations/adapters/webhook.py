"""
Webhook receive adapter — external system pushes data to PMS.
This adapter is push-only; fetch() retrieves the already-stored value.
"""

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from app.integrations.adapters.base import AdapterResult, BaseAdapter

if TYPE_CHECKING:
    from app.integrations.models import KPIVariable


class WebhookReceiveAdapter(BaseAdapter):
    """
    External system pushes data TO the PMS via HTTP POST.
    The PMS generates a unique endpoint key per variable.
    No polling needed — value is stored as soon as push arrives.

    source_config schema:
    {
      "adapter": "webhook_receive",
      "endpoint_key": "var_abc123def456",
      "expected_field": "value",
      "allowed_ips": ["10.0.1.0/24"],
      "require_hmac": false
    }

    Webhook URL: POST /api/v1/integrations/push/{endpoint_key}
    Body: {"value": 1234567.89, "period": "2025-03", "source": "SAP-ERP"}
    """

    async def fetch(
        self, config: dict, period_date: date, variable: "KPIVariable"
    ) -> AdapterResult:
        # Webhooks are PUSH — data is already stored in variable_actuals when pushed.
        # DataSyncService handles retrieval; this method should not be called.
        raise NotImplementedError(
            "WebhookReceiveAdapter does not pull — data is pushed by external system"
        )

    def validate_config(self, config: dict) -> list[str]:
        errors: list[str] = []
        if "endpoint_key" not in config:
            errors.append("'endpoint_key' is required (auto-generated)")
        if "expected_field" not in config:
            errors.append("'expected_field' is required")
        return errors

    def get_config_schema(self) -> dict:
        return {
            "fields": [
                {
                    "name": "endpoint_key",
                    "type": "readonly",
                    "label": "Webhook Token (auto-generated)",
                },
                {
                    "name": "expected_field",
                    "type": "string",
                    "label": "Value Field Name",
                    "required": True,
                    "hint": "Field name in the POST body that holds the numeric value",
                },
                {
                    "name": "allowed_ips",
                    "type": "list",
                    "label": "Allowed IP ranges (CIDR)",
                    "required": False,
                },
            ]
        }
