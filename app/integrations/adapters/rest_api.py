"""
REST API adapter — fetches a scalar value from any HTTP endpoint.
"""

import time
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from app.integrations.adapters.base import AdapterResult, BaseAdapter

if TYPE_CHECKING:
    from app.integrations.models import KPIVariable


class RestApiAdapter(BaseAdapter):
    """
    Fetch a value from any HTTP endpoint.

    source_config schema:
    {
      "adapter": "rest_api",
      "url": "https://erp.company.com/api/v1/sales/monthly?month={period.iso}",
      "method": "GET",
      "headers": {
        "Authorization": "Bearer {SECRET:ERP_API_TOKEN}"
      },
      "body": null,
      "response_path": "data.total_amount",
      "timeout_seconds": 30,
      "expected_http_status": 200
    }
    """

    async def fetch(
        self, config: dict, period_date: date, variable: "KPIVariable"
    ) -> AdapterResult:
        import httpx

        resolved = self.resolve_secrets(config)
        url = self.resolve_period_params(resolved["url"], period_date)
        headers = resolved.get("headers", {})
        timeout = resolved.get("timeout_seconds", 30)
        method = resolved.get("method", "GET").upper()
        body = resolved.get("body")

        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                if method == "POST":
                    resp = await client.post(url, headers=headers, json=body)
                else:
                    resp = await client.get(url, headers=headers)

            elapsed_ms = int((time.monotonic() - start) * 1000)
            expected_status = resolved.get("expected_http_status", 200)

            if resp.status_code != expected_status:
                return AdapterResult(
                    value=Decimal("0"),
                    metadata={
                        "adapter": "rest_api",
                        "url": url,
                        "http_status": resp.status_code,
                        "response_time_ms": elapsed_ms,
                    },
                    success=False,
                    error=f"HTTP {resp.status_code} — expected {expected_status}",
                )

            raw_data = resp.json()
            extracted = self.extract_json_path(raw_data, resolved["response_path"])
            value = Decimal(str(extracted))

            return AdapterResult(
                value=value,
                metadata={
                    "adapter": "rest_api",
                    "url": url,
                    "http_status": resp.status_code,
                    "response_time_ms": elapsed_ms,
                    "response_path": resolved["response_path"],
                },
                success=True,
            )

        except Exception as e:
            return AdapterResult(
                value=Decimal("0"),
                metadata={"adapter": "rest_api", "url": url},
                success=False,
                error=str(e),
            )

    def validate_config(self, config: dict) -> list[str]:
        errors: list[str] = []
        if "url" not in config:
            errors.append("'url' is required")
        if "response_path" not in config:
            errors.append("'response_path' is required")
        return errors

    def get_config_schema(self) -> dict:
        return {
            "fields": [
                {
                    "name": "url",
                    "type": "string",
                    "label": "Endpoint URL",
                    "required": True,
                    "hint": "Use {period.iso} for YYYY-MM substitution",
                },
                {
                    "name": "method",
                    "type": "select",
                    "label": "HTTP Method",
                    "required": False,
                    "options": ["GET", "POST"],
                    "default": "GET",
                },
                {
                    "name": "headers",
                    "type": "kvpairs",
                    "label": "Request Headers",
                    "required": False,
                    "hint": "Use {SECRET:KEY} for credentials",
                },
                {
                    "name": "response_path",
                    "type": "string",
                    "label": "Response JSON Path",
                    "required": True,
                    "hint": "Dot-notation, e.g. data.total_amount",
                },
                {
                    "name": "timeout_seconds",
                    "type": "number",
                    "label": "Timeout (seconds)",
                    "required": False,
                    "default": 30,
                },
            ]
        }
