"""
Database adapter — executes a read-only SQL query against an external database.
"""

import asyncio
import re
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from app.integrations.adapters.base import AdapterResult, BaseAdapter

if TYPE_CHECKING:
    from app.integrations.models import KPIVariable


class DatabaseAdapter(BaseAdapter):
    """
    Execute a SQL query against an external database and return a scalar.
    Supports: PostgreSQL, MySQL, SQL Server, SQLite (via connection string).

    source_config schema:
    {
      "adapter": "database",
      "connection_string": "{SECRET:SALES_DB_CONN}",
      "query": "SELECT SUM(amount) FROM sales_orders WHERE year = :year AND month = :month",
      "params": {"year": "{period.year}", "month": "{period.month}"},
      "timeout_seconds": 60
    }

    SECURITY: Only SELECT statements are permitted.
    Connection string MUST be a {SECRET:...} reference.
    """

    ALLOWED_QUERY_START = re.compile(r'^\s*SELECT\s', re.IGNORECASE)
    FORBIDDEN_KEYWORDS = re.compile(
        r'\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|EXEC|EXECUTE)\b',
        re.IGNORECASE,
    )

    async def fetch(
        self, config: dict, period_date: date, variable: "KPIVariable"
    ) -> AdapterResult:
        try:
            import databases  # pip install databases[asyncpg,aiomysql]
        except ImportError:
            return AdapterResult(
                value=Decimal("0"),
                metadata={"adapter": "database"},
                success=False,
                error="'databases' package not installed. Run: pip install databases",
            )

        resolved = self.resolve_secrets(config)
        conn_string = resolved["connection_string"]
        query = resolved["query"]
        timeout = resolved.get("timeout_seconds", 60)

        # Resolve period params in query params values
        params = {
            k: (
                int(pv)
                if (pv := self.resolve_period_params(str(v), period_date)).isdigit()
                else pv
            )
            for k, v in resolved.get("params", {}).items()
        }

        try:
            database = databases.Database(conn_string)
            await database.connect()
            try:
                row = await asyncio.wait_for(
                    database.fetch_one(query=query, values=params),
                    timeout=timeout,
                )
                value = Decimal(str(list(row)[0])) if row else Decimal("0")
            finally:
                await database.disconnect()

            return AdapterResult(
                value=value,
                metadata={
                    "adapter": "database",
                    "query_preview": query[:100],
                    "row_count": 1 if row else 0,
                },
                success=True,
            )
        except Exception as e:
            return AdapterResult(
                value=Decimal("0"),
                metadata={"adapter": "database"},
                success=False,
                error=str(e),
            )

    def validate_config(self, config: dict) -> list[str]:
        errors: list[str] = []
        if "connection_string" not in config:
            errors.append("'connection_string' is required")
        elif not config["connection_string"].startswith("{SECRET:"):
            errors.append(
                "'connection_string' must use a {SECRET:KEY} reference, never a raw connection string"
            )
        if "query" not in config:
            errors.append("'query' is required")
        else:
            if not self.ALLOWED_QUERY_START.match(config["query"]):
                errors.append("Only SELECT queries are permitted")
            if self.FORBIDDEN_KEYWORDS.search(config["query"]):
                errors.append(
                    "Query contains forbidden keywords (INSERT/UPDATE/DELETE/etc.)"
                )
        return errors

    def get_config_schema(self) -> dict:
        return {
            "fields": [
                {
                    "name": "connection_string",
                    "type": "secret_ref",
                    "label": "Connection String Secret",
                    "required": True,
                    "hint": "Format: {SECRET:MY_DB_CONN_SECRET}",
                },
                {
                    "name": "query",
                    "type": "sql",
                    "label": "SQL Query (SELECT only)",
                    "required": True,
                    "hint": "Use :year, :month as named params. Only SELECT is allowed.",
                },
                {
                    "name": "params",
                    "type": "kvpairs",
                    "label": "Query Parameters",
                    "required": False,
                    "hint": "Use {period.year}, {period.month} for dynamic dates",
                },
                {
                    "name": "timeout_seconds",
                    "type": "number",
                    "label": "Timeout (seconds)",
                    "required": False,
                    "default": 60,
                },
            ]
        }
