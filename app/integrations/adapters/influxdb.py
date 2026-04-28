"""
InfluxDB adapter — fetches time-series data via Flux query.
"""

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from app.integrations.adapters.base import AdapterResult, BaseAdapter

if TYPE_CHECKING:
    from app.integrations.models import KPIVariable


class InfluxDbAdapter(BaseAdapter):
    """
    Fetch a scalar value from InfluxDB via Flux query.

    source_config schema:
    {
      "adapter": "influxdb",
      "url": "https://influxdb.company.com",
      "token": "{SECRET:INFLUX_TOKEN}",
      "org": "my-org",
      "bucket": "iot-metrics",
      "flux_query": "from(bucket: \\"iot-metrics\\") |> range(start: {period.start_date}T00:00:00Z, stop: {period.end_date}T23:59:59Z) |> filter(fn: (r) => r._measurement == \\"sensor\\") |> sum()",
      "timeout_seconds": 30
    }
    """

    async def fetch(
        self, config: dict, period_date: date, variable: "KPIVariable"
    ) -> AdapterResult:
        try:
            from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync
        except ImportError:
            return AdapterResult(
                value=Decimal("0"),
                metadata={"adapter": "influxdb"},
                success=False,
                error="'influxdb-client' package not installed. Run: pip install influxdb-client",
            )

        resolved = self.resolve_secrets(config)
        url = resolved["url"]
        token = resolved["token"]
        org = resolved["org"]
        query = self.resolve_period_params(resolved["flux_query"], period_date)
        timeout = resolved.get("timeout_seconds", 30)

        try:
            async with InfluxDBClientAsync(url=url, token=token, org=org, timeout=timeout * 1000) as client:
                query_api = client.query_api()
                tables = await query_api.query(query=query)

                value = Decimal("0")
                for table in tables:
                    for record in table.records:
                        value = Decimal(str(record.get_value()))
                        break
                    break

            return AdapterResult(
                value=value,
                metadata={
                    "adapter": "influxdb",
                    "url": url,
                    "org": org,
                    "bucket": resolved.get("bucket"),
                },
                success=True,
            )
        except Exception as e:
            return AdapterResult(
                value=Decimal("0"),
                metadata={"adapter": "influxdb"},
                success=False,
                error=str(e),
            )

    def validate_config(self, config: dict) -> list[str]:
        errors: list[str] = []
        for field in ("url", "org", "flux_query"):
            if field not in config:
                errors.append(f"'{field}' is required")
        if "token" not in config:
            errors.append("'token' is required")
        elif not config["token"].startswith("{SECRET:"):
            errors.append("'token' must use a {SECRET:KEY} reference")
        return errors

    def get_config_schema(self) -> dict:
        return {
            "fields": [
                {"name": "url",         "type": "string",     "label": "InfluxDB URL",      "required": True},
                {"name": "token",       "type": "secret_ref", "label": "API Token Secret",  "required": True},
                {"name": "org",         "type": "string",     "label": "Organisation",      "required": True},
                {"name": "bucket",      "type": "string",     "label": "Bucket",            "required": False},
                {"name": "flux_query",  "type": "string",     "label": "Flux Query",        "required": True,
                 "hint": "Use {period.start_date} and {period.end_date} for date ranges"},
                {"name": "timeout_seconds", "type": "number", "label": "Timeout (seconds)", "required": False, "default": 30},
            ]
        }
