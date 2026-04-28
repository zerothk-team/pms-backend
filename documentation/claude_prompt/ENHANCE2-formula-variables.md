# Copilot Prompt — Enhancement 2: Formula Variables, Data Binding & External Integration
> **Model**: Claude Sonnet 4.6 | **Workspace**: @workspace (both frontend + backend open)
> **Depends on**: Backend Parts 1–5, Enhancement 1 completed

---

## Context & Business Problem

The current formula engine stores expressions like `(KPI_REVENUE - KPI_EXPENSES) / KPI_REVENUE * 100` and resolves them by looking up **other KPI actuals**. This means:

1. Every variable in a formula must itself be a tracked KPI — even raw data points like "total sales orders" must be manually entered as a separate KPI.
2. There is **no mechanism to pull data automatically** from external systems (ERP, HRMS, IoT, databases).
3. There is **no variable management UI** — managers cannot see or manage what variables a formula uses.
4. If an ERP changes its API, there is **no way to reconfigure** without code changes.

This enhancement adds:
- **Named formula variables** (`KPIVariable`) — typed slots in a formula that hold raw values
- **Dynamic data binding** via a pluggable adapter system — each variable can pull from REST API, SQL database, IoT stream, HRMS, or remain manual
- **Secrets management** — credentials stored as environment variable references, never in plaintext
- **Generic formula executor** — safely evaluates any formula expression given resolved variable values
- **Variable actuals store** — full audit trail of every value that went into every formula computation
- **Frontend variable entry UI** — shows auto-synced variables and collects manual ones

---

## Part A — Backend: Data Model

### A1. New Enums — `app/integrations/enums.py`

```python
from enum import Enum

class VariableSourceType(str, Enum):
    MANUAL = "manual"                   # user types value on actuals entry screen
    REST_API = "rest_api"               # HTTP GET/POST to external endpoint
    DATABASE = "database"               # direct SQL query to external DB
    INFLUXDB = "influxdb"               # InfluxDB/time-series via Flux query
    WEBHOOK_RECEIVE = "webhook_receive" # external system POSTs to PMS
    KPI_ACTUAL = "kpi_actual"           # pull latest actual from another KPI (existing behaviour)
    CSV_UPLOAD = "csv_upload"           # periodic CSV upload (batch)
    FORMULA = "formula"                 # derived from other variables within the same KPI

class VariableDataType(str, Enum):
    NUMBER = "number"           # floating point
    INTEGER = "integer"         # whole numbers only
    PERCENTAGE = "percentage"   # 0–100 (or 0–∞ for over-achievement)
    CURRENCY = "currency"       # tied to org currency, stored as Numeric
    BOOLEAN = "boolean"         # 1/0, used in conditional formulas
    DURATION_HOURS = "duration_hours"

class SyncStatus(str, Enum):
    NEVER_SYNCED = "never_synced"
    SYNCING = "syncing"
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"   # some periods succeeded, some failed
```

---

### A2. New Table: `kpi_variables`

**Create `app/integrations/models.py`:**

```python
class KPIVariable(Base):
    """
    A named, typed slot in a KPI formula.

    Example: formula "(REVENUE - EXPENSES) / REVENUE * 100" has variables:
      - REVENUE   (source: rest_api → ERP endpoint)
      - EXPENSES  (source: manual  → employee enters)

    The formula_expression in the KPI references these by variable_name.
    """
    __tablename__ = "kpi_variables"

    id                    = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kpi_id                = Column(UUID(as_uuid=True), ForeignKey("kpis.id"), nullable=False)
    variable_name         = Column(String(50), nullable=False)
    # ^ MUST match what appears in the formula: uppercase, no spaces, e.g. "REVENUE"
    # ^ Regex validated: ^[A-Z][A-Z0-9_]{0,49}$

    display_label         = Column(String(150), nullable=False)
    # ^ Human-readable: "Total Monthly Revenue (MYR)"

    description           = Column(Text, nullable=True)
    data_type             = Column(SAEnum(VariableDataType), nullable=False, default=VariableDataType.NUMBER)
    unit_label            = Column(String(50), nullable=True)    # e.g. "MYR", "units", "hours"
    source_type           = Column(SAEnum(VariableSourceType), nullable=False, default=VariableSourceType.MANUAL)
    source_config         = Column(JSON, nullable=True)
    # ^ Adapter-specific configuration (see adapter specs below)
    # ^ MUST NOT contain raw credentials — use {SECRET:KEY_NAME} placeholders

    is_required           = Column(Boolean, default=True)
    # ^ If True: formula eval fails if this variable has no value for the period
    # ^ If False: formula uses default_value when variable is missing

    default_value         = Column(Numeric(18, 4), nullable=True)
    # ^ Used when is_required=False and no value is available

    auto_sync_enabled     = Column(Boolean, default=True)
    # ^ For non-manual sources: whether to auto-pull on scheduled job

    sync_frequency        = Column(SAEnum(MeasurementFrequency), nullable=True)
    # ^ How often to sync. If null: syncs when formula eval is triggered

    last_synced_at        = Column(DateTime(timezone=True), nullable=True)
    last_sync_status      = Column(SAEnum(SyncStatus), default=SyncStatus.NEVER_SYNCED)
    last_sync_error       = Column(Text, nullable=True)
    # ^ Last error message, for debugging

    display_order         = Column(Integer, default=0)
    # ^ Order variables appear in the manual entry UI

    organisation_id       = Column(UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False)
    created_by_id         = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at            = Column(DateTime(timezone=True), server_default=func.now())
    updated_at            = Column(DateTime(timezone=True), onupdate=func.now())

    # Constraints
    __table_args__ = (
        UniqueConstraint("kpi_id", "variable_name", name="uq_kpi_variable_name"),
        # ^ One variable name per KPI — prevents ambiguous formula references
        CheckConstraint(
            "variable_name ~ '^[A-Z][A-Z0-9_]{0,49}$'",
            name="ck_variable_name_format"
        ),
    )

    # Relationships
    kpi          = relationship("KPI", back_populates="variables")
    actuals      = relationship("VariableActual", back_populates="variable", order_by="VariableActual.period_date")
```

---

### A3. New Table: `variable_actuals`

```python
class VariableActual(Base):
    """
    A raw data value for one variable for one period.

    Every value that goes into a formula computation is stored here.
    This provides a complete audit trail: you can always see exactly
    which numbers were used to compute any KPI actual.
    """
    __tablename__ = "variable_actuals"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    variable_id     = Column(UUID(as_uuid=True), ForeignKey("kpi_variables.id"), nullable=False)
    kpi_id          = Column(UUID(as_uuid=True), ForeignKey("kpis.id"), nullable=False)
    # ^ Denormalised for faster queries

    period_date     = Column(Date, nullable=False)
    raw_value       = Column(Numeric(18, 4), nullable=False)
    source_type     = Column(SAEnum(VariableSourceType), nullable=False)
    sync_metadata   = Column(JSON, nullable=True)
    # ^ Audit info: {"adapter": "rest_api", "url": "...", "response_time_ms": 342,
    #                "http_status": 200, "raw_response_snippet": "...", "synced_at": "..."}

    submitted_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    # ^ null for auto-synced values

    is_current      = Column(Boolean, default=True)
    # ^ False when superseded by a re-sync or correction for same period

    created_at      = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_variable_actuals_var_period", "variable_id", "period_date"),
        Index("ix_variable_actuals_kpi_period", "kpi_id", "period_date"),
    )

    variable = relationship("KPIVariable", back_populates="actuals")
```

---

### A4. Update `kpis` Table

Add back-reference in `app/kpis/models.py`:

```python
# In KPI model, add relationship:
variables = relationship(
    "KPIVariable",
    back_populates="kpi",
    order_by="KPIVariable.display_order",
    cascade="all, delete-orphan",
)
```

---

## Part B — Backend: Adapter System

### B1. Base Adapter — `app/integrations/adapters/base.py`

```python
from abc import ABC, abstractmethod
from datetime import date
from decimal import Decimal
from typing import Any
import re


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

    # ── Shared utilities ────────────────────────────────────────────────

    def resolve_secrets(self, config: dict) -> dict:
        """
        Replace {SECRET:KEY_NAME} placeholders with actual values.
        Reads from environment variables: PMS_SECRET_KEY_NAME.
        NEVER logs the resolved values.
        """
        import os, copy
        resolved = copy.deepcopy(config)
        SECRET_PATTERN = re.compile(r'\{SECRET:([A-Z0-9_]+)\}')

        def _resolve_value(val):
            if isinstance(val, str):
                def _replacer(m):
                    env_key = f"PMS_SECRET_{m.group(1)}"
                    secret = os.environ.get(env_key)
                    if not secret:
                        raise ValueError(f"Secret not found: {env_key} (referenced as {{SECRET:{m.group(1)}}})")
                    return secret
                return SECRET_PATTERN.sub(_replacer, val)
            elif isinstance(val, dict):
                return {k: _resolve_value(v) for k, v in val.items()}
            return val

        return _resolve_value(resolved)

    def resolve_period_params(self, template: str, period_date: date) -> str:
        """
        Replace period placeholders in URL or query strings.
        Supported: {period.year}, {period.month}, {period.month_padded},
                   {period.quarter}, {period.start_date}, {period.end_date}
        """
        import calendar
        last_day = calendar.monthrange(period_date.year, period_date.month)[1]
        replacements = {
            "{period.year}":        str(period_date.year),
            "{period.month}":       str(period_date.month),
            "{period.month_padded}": f"{period_date.month:02d}",
            "{period.quarter}":     str((period_date.month - 1) // 3 + 1),
            "{period.start_date}":  period_date.replace(day=1).isoformat(),
            "{period.end_date}":    period_date.replace(day=last_day).isoformat(),
            "{period.iso}":         period_date.strftime("%Y-%m"),
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
                raise ValueError(f"Cannot navigate path '{json_path}' at '{part}'")
        return current
```

---

### B2. REST API Adapter — `app/integrations/adapters/rest_api.py`

```python
class RestApiAdapter(BaseAdapter):
    """
    Fetch a value from any HTTP endpoint.

    source_config schema:
    {
      "adapter": "rest_api",
      "url": "https://erp.company.com/api/v1/sales/monthly?month={period.iso}",
      "method": "GET",                         # GET or POST
      "headers": {
        "Authorization": "Bearer {SECRET:ERP_API_TOKEN}",
        "X-Tenant": "company-id"
      },
      "body": null,                            # JSON body for POST requests
      "response_path": "data.total_amount",   # dot-notation JSONPath
      "timeout_seconds": 30,
      "expected_http_status": 200
    }
    """

    async def fetch(self, config: dict, period_date: date, variable) -> AdapterResult:
        import httpx, time

        resolved = self.resolve_secrets(config)
        url = self.resolve_period_params(resolved["url"], period_date)
        headers = resolved.get("headers", {})
        timeout = resolved.get("timeout_seconds", 30)

        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                if resolved.get("method", "GET").upper() == "POST":
                    resp = await client.post(url, headers=headers, json=resolved.get("body"))
                else:
                    resp = await client.get(url, headers=headers)

            elapsed_ms = int((time.monotonic() - start) * 1000)
            expected_status = resolved.get("expected_http_status", 200)

            if resp.status_code != expected_status:
                return AdapterResult(
                    value=Decimal("0"),
                    metadata={"adapter": "rest_api", "url": url, "http_status": resp.status_code, "elapsed_ms": elapsed_ms},
                    success=False,
                    error=f"HTTP {resp.status_code} from {url}",
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
                    "elapsed_ms": elapsed_ms,
                    "response_path": resolved["response_path"],
                    "synced_at": datetime.now(timezone.utc).isoformat(),
                },
                success=True,
            )

        except Exception as e:
            return AdapterResult(
                value=Decimal("0"),
                metadata={"adapter": "rest_api", "url": url, "error": str(e)},
                success=False,
                error=str(e),
            )

    def validate_config(self, config: dict) -> list[str]:
        errors = []
        if "url" not in config:
            errors.append("'url' is required")
        if "response_path" not in config:
            errors.append("'response_path' is required")
        return errors

    def get_config_schema(self) -> dict:
        return {
            "fields": [
                {"name": "url",           "type": "string",  "label": "Endpoint URL",        "required": True,  "hint": "Use {period.iso} for YYYY-MM substitution"},
                {"name": "method",        "type": "select",  "label": "HTTP Method",          "required": False, "options": ["GET", "POST"], "default": "GET"},
                {"name": "headers",       "type": "kvpairs", "label": "Headers",              "required": False, "hint": "Use {SECRET:KEY} for credentials"},
                {"name": "response_path", "type": "string",  "label": "Response JSON Path",   "required": True,  "hint": "e.g. data.total_amount or results[0].value"},
                {"name": "timeout_seconds","type": "number", "label": "Timeout (seconds)",    "required": False, "default": 30},
            ]
        }
```

---

### B3. Database Adapter — `app/integrations/adapters/database.py`

```python
class DatabaseAdapter(BaseAdapter):
    """
    Execute a SQL query against an external database and return a scalar.
    Supports: PostgreSQL, MySQL, SQL Server, SQLite (via connection string).

    source_config schema:
    {
      "adapter": "database",
      "connection_string": "{SECRET:SALES_DB_CONN}",
      "query": "SELECT SUM(amount) FROM sales_orders WHERE YEAR(created_at) = :year AND MONTH(created_at) = :month AND status = 'completed'",
      "params": {
        "year":  "{period.year}",
        "month": "{period.month}"
      },
      "timeout_seconds": 60
    }

    SECURITY: The query is parameterised — never use f-strings or .format() on queries.
    Only SELECT statements are permitted (enforced by validate_config).
    Connection string is always a SECRET reference.
    """

    ALLOWED_QUERY_START = re.compile(r'^\s*SELECT\s', re.IGNORECASE)
    FORBIDDEN_KEYWORDS = re.compile(r'\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|EXEC)\b', re.IGNORECASE)

    async def fetch(self, config: dict, period_date: date, variable) -> AdapterResult:
        import databases  # pip install databases[asyncpg,aiomysql]

        resolved = self.resolve_secrets(config)
        conn_string = resolved["connection_string"]
        query = resolved["query"]
        params = {
            k: int(self.resolve_period_params(v, period_date))
            if self.resolve_period_params(v, period_date).isdigit()
            else self.resolve_period_params(v, period_date)
            for k, v in resolved.get("params", {}).items()
        }
        timeout = resolved.get("timeout_seconds", 60)

        try:
            database = databases.Database(conn_string)
            await database.connect()
            try:
                row = await asyncio.wait_for(
                    database.fetch_one(query=query, values=params),
                    timeout=timeout
                )
                value = Decimal(str(list(row)[0])) if row else Decimal("0")
            finally:
                await database.disconnect()

            return AdapterResult(
                value=value,
                metadata={"adapter": "database", "synced_at": datetime.now(timezone.utc).isoformat()},
                success=True,
            )
        except Exception as e:
            return AdapterResult(
                value=Decimal("0"),
                metadata={"adapter": "database", "error": str(e)},
                success=False,
                error=str(e),
            )

    def validate_config(self, config: dict) -> list[str]:
        errors = []
        if "connection_string" not in config:
            errors.append("'connection_string' is required")
        elif not config["connection_string"].startswith("{SECRET:"):
            errors.append("'connection_string' must use a {SECRET:KEY} reference, never a raw connection string")
        if "query" not in config:
            errors.append("'query' is required")
        else:
            if not self.ALLOWED_QUERY_START.match(config["query"]):
                errors.append("Only SELECT queries are permitted")
            if self.FORBIDDEN_KEYWORDS.search(config["query"]):
                errors.append("Query contains forbidden keywords (INSERT/UPDATE/DELETE/etc.)")
        return errors

    def get_config_schema(self) -> dict:
        return {
            "fields": [
                {"name": "connection_string", "type": "secret_ref", "label": "Connection String Secret", "required": True, "hint": "Format: {SECRET:MY_DB_CONN_SECRET}"},
                {"name": "query",             "type": "sql",        "label": "SQL Query (SELECT only)",  "required": True, "hint": "Use :year, :month, :quarter as parameters"},
                {"name": "params",            "type": "kvpairs",    "label": "Query Parameters",         "required": False, "hint": "Map param names to period placeholders"},
                {"name": "timeout_seconds",   "type": "number",     "label": "Timeout (seconds)",        "required": False, "default": 60},
            ]
        }
```

---

### B4. Webhook Receive Adapter — `app/integrations/adapters/webhook.py`

```python
class WebhookReceiveAdapter(BaseAdapter):
    """
    External system pushes data TO the PMS via HTTP POST.
    The PMS generates a unique endpoint key per variable.
    No polling needed — value is stored as soon as push arrives.

    source_config schema:
    {
      "adapter": "webhook_receive",
      "endpoint_key": "var_abc123def456",    # auto-generated UUID-based token
      "expected_field": "value",             # which field in POST body holds the value
      "allowed_ips": ["10.0.1.0/24"],        # optional IP allowlist
      "require_hmac": false                  # optional HMAC signature verification
    }

    Webhook URL: POST /api/v1/integrations/push/{endpoint_key}
    Body: {"value": 1234567.89, "period": "2025-03", "source": "SAP-ERP"}
    """

    async def fetch(self, config: dict, period_date: date, variable) -> AdapterResult:
        """
        Webhooks are PUSH — data is already stored in variable_actuals when pushed.
        This fetch() just retrieves the stored value, or returns failure if not received.
        """
        # This is handled by WebhookReceiveService, not active pulling
        raise NotImplementedError("WebhookReceiveAdapter does not pull — data is pushed by external system")

    def validate_config(self, config: dict) -> list[str]:
        errors = []
        if "endpoint_key" not in config:
            errors.append("'endpoint_key' is required (auto-generated)")
        if "expected_field" not in config:
            errors.append("'expected_field' is required")
        return errors

    def get_config_schema(self) -> dict:
        return {
            "fields": [
                {"name": "endpoint_key",    "type": "readonly", "label": "Webhook Token (auto-generated)"},
                {"name": "expected_field",  "type": "string",   "label": "Value field name in POST body", "required": True, "default": "value"},
                {"name": "allowed_ips",     "type": "list",     "label": "Allowed IP ranges (CIDR)",     "required": False},
            ]
        }
```

---

### B5. KPI Actual Adapter — `app/integrations/adapters/kpi_actual.py`

```python
class KPIActualAdapter(BaseAdapter):
    """
    Pull the latest approved actual from another KPI in the same org.
    Maintains backward compatibility with the original formula design.

    source_config schema:
    {
      "adapter": "kpi_actual",
      "kpi_code": "SALES_REVENUE_GROWTH",   # code of the KPI to pull from
      "aggregation": "latest"               # "latest", "sum", "average", "max", "min"
    }
    """

    async def fetch(self, config: dict, period_date: date, variable) -> AdapterResult:
        # Fetches from variable_actuals or kpi_actuals depending on source
        # Implementation uses the DB session passed via context
        ...
```

---

### B6. Adapter Registry — `app/integrations/adapter_registry.py`

```python
class AdapterRegistry:
    """
    Central registry for all data adapters.
    Fully extensible — add new adapters without touching core code.
    """
    _adapters: dict[str, type[BaseAdapter]] = {}

    @classmethod
    def register(cls, name: str, adapter_class: type[BaseAdapter]) -> None:
        """Register a new adapter. Call at module load time."""
        if name in cls._adapters:
            raise ValueError(f"Adapter '{name}' already registered")
        cls._adapters[name] = adapter_class

    @classmethod
    def get(cls, adapter_name: str) -> BaseAdapter:
        if adapter_name not in cls._adapters:
            raise ValueError(
                f"Unknown adapter: '{adapter_name}'. "
                f"Available: {list(cls._adapters.keys())}"
            )
        return cls._adapters[adapter_name]()

    @classmethod
    def list_available(cls) -> list[dict]:
        """Returns metadata for all registered adapters (for frontend config UI)."""
        return [
            {
                "name": name,
                "schema": cls._adapters[name]().get_config_schema(),
                "description": cls._adapters[name].__doc__,
            }
            for name in cls._adapters
        ]


# Register all built-in adapters (called once at app startup)
def register_builtin_adapters():
    AdapterRegistry.register("rest_api",         RestApiAdapter)
    AdapterRegistry.register("database",         DatabaseAdapter)
    AdapterRegistry.register("influxdb",         InfluxDbAdapter)
    AdapterRegistry.register("webhook_receive",  WebhookReceiveAdapter)
    AdapterRegistry.register("kpi_actual",       KPIActualAdapter)
    AdapterRegistry.register("csv_upload",       CsvUploadAdapter)
```

---

## Part C — Backend: Formula Executor (Generic, Complete)

### C1. `app/kpis/formula.py` — Complete Rewrite

```python
"""
Safe formula executor for KPI formula KPIs.

Design principles:
  1. Uses Python AST (not eval()) — only whitelisted node types allowed
  2. Variables are resolved BEFORE execution — no DB calls inside the evaluator
  3. Pure function — FormulaEvaluator has no side effects, fully testable
  4. Circular dependency detection uses topological sort (Kahn's algorithm)
  5. Formula syntax supports: +  -  *  /  **  ()  abs()  round()  min()  max()  if()
"""

import ast
import re
import operator
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID


# ── Exceptions ────────────────────────────────────────────────────────────────

class FormulaValidationError(ValueError):
    def __init__(self, message: str, position: int | None = None):
        self.position = position
        super().__init__(message)

class CircularDependencyError(ValueError):
    def __init__(self, cycle_path: list[str]):
        self.cycle_path = cycle_path
        super().__init__(f"Circular dependency detected: {' → '.join(cycle_path)}")

class MissingVariableError(ValueError):
    def __init__(self, variable_name: str):
        self.variable_name = variable_name
        super().__init__(f"Required variable '{variable_name}' has no value for this period")

class EvaluationError(RuntimeError):
    pass


# ── AST Validator ─────────────────────────────────────────────────────────────

class FormulaASTValidator(ast.NodeVisitor):
    """
    Walks the AST and raises FormulaValidationError for any non-whitelisted node.
    Whitelist: numbers, arithmetic operators, variable names (uppercase), safe functions.
    """

    SAFE_FUNCTIONS = {"abs", "round", "min", "max", "if_func"}
    # Note: Python 'if' is a statement — we implement it as if_func(condition, true_val, false_val)

    def __init__(self):
        self.errors: list[str] = []

    def visit_Module(self, node):
        self.generic_visit(node)

    def visit_Expr(self, node):
        self.generic_visit(node)

    def visit_Constant(self, node):
        if not isinstance(node.value, (int, float)):
            self.errors.append(f"Only numeric constants allowed, got: {type(node.value).__name__}")

    def visit_Name(self, node):
        # Variable references must be uppercase with underscores
        if not re.match(r'^[A-Z][A-Z0-9_]*$', node.id):
            self.errors.append(f"Variable name must be uppercase: '{node.id}'")

    def visit_BinOp(self, node):
        allowed_ops = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod)
        if not isinstance(node.op, allowed_ops):
            self.errors.append(f"Operator not allowed: {type(node.op).__name__}")
        self.generic_visit(node)

    def visit_UnaryOp(self, node):
        if not isinstance(node.op, (ast.USub, ast.UAdd)):
            self.errors.append(f"Unary operator not allowed: {type(node.op).__name__}")
        self.generic_visit(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name):
            if node.func.id not in self.SAFE_FUNCTIONS:
                self.errors.append(f"Function not allowed: '{node.func.id}'. Allowed: {self.SAFE_FUNCTIONS}")
        else:
            self.errors.append("Complex function calls not allowed")
        self.generic_visit(node)

    def visit_Compare(self, node):
        # Allow comparisons for use inside if_func()
        allowed_comparators = (ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq)
        for op in node.ops:
            if not isinstance(op, allowed_comparators):
                self.errors.append(f"Comparison operator not allowed: {type(op).__name__}")
        self.generic_visit(node)

    def generic_visit(self, node):
        allowed_node_types = (
            ast.Module, ast.Expr, ast.Constant, ast.Name, ast.BinOp, ast.UnaryOp,
            ast.Call, ast.Compare, ast.BoolOp, ast.IfExp, ast.Load,
            ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod,
            ast.USub, ast.UAdd, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq,
            ast.And, ast.Or, ast.Not, ast.Tuple,
        )
        if not isinstance(node, allowed_node_types):
            self.errors.append(f"Disallowed syntax: {type(node).__name__}")
        super().generic_visit(node)


# ── Formula Parser ────────────────────────────────────────────────────────────

class FormulaParser:
    """Parses and validates formula expressions without evaluating them."""

    VARIABLE_PATTERN = re.compile(r'\b([A-Z][A-Z0-9_]*)\b')
    SAFE_FUNCTION_NAMES = {"ABS", "ROUND", "MIN", "MAX", "IF"}

    def extract_variable_names(self, expression: str) -> list[str]:
        """
        Return all uppercase identifiers in the expression that are NOT function names.
        These are the variable names that must be resolved before evaluation.

        >>> FormulaParser().extract_variable_names("(REVENUE - EXPENSES) / REVENUE * 100")
        ['REVENUE', 'EXPENSES']
        """
        found = self.VARIABLE_PATTERN.findall(expression)
        # Exclude safe function names (they're uppercase too)
        return list(dict.fromkeys(
            name for name in found
            if name not in self.SAFE_FUNCTION_NAMES
        ))

    def validate_syntax(self, expression: str) -> list[str]:
        """
        Validate formula syntax using AST.
        Returns list of error messages. Empty list = valid.
        """
        if not expression or not expression.strip():
            return ["Formula expression cannot be empty"]

        # Normalise IF() to if_func() for Python AST parsing
        normalised = re.sub(r'\bIF\s*\(', 'if_func(', expression, flags=re.IGNORECASE)
        normalised = re.sub(r'\bABS\s*\(', 'abs(', normalised, flags=re.IGNORECASE)
        normalised = re.sub(r'\bROUND\s*\(', 'round(', normalised, flags=re.IGNORECASE)
        normalised = re.sub(r'\bMIN\s*\(', 'min(', normalised, flags=re.IGNORECASE)
        normalised = re.sub(r'\bMAX\s*\(', 'max(', normalised, flags=re.IGNORECASE)

        try:
            tree = ast.parse(normalised, mode='eval')
        except SyntaxError as e:
            return [f"Syntax error: {e.msg} at position {e.offset}"]

        validator = FormulaASTValidator()
        validator.visit(tree)
        return validator.errors

    def validate_variables_exist(
        self, expression: str, available_variable_names: list[str]
    ) -> list[str]:
        """
        Check that all variable names in the expression are defined for this KPI.
        """
        referenced = self.extract_variable_names(expression)
        available_set = set(available_variable_names)
        return [
            f"Variable '{name}' is referenced in the formula but not defined. "
            f"Please add it as a KPI variable."
            for name in referenced
            if name not in available_set
        ]


# ── Circular Dependency Detector ──────────────────────────────────────────────

class DependencyResolver:
    """
    Detects circular dependencies in KPI formula chains.
    Uses Kahn's topological sort algorithm.
    """

    def build_dependency_graph(
        self, kpi_id: UUID, all_kpis: list, all_variables: list
    ) -> dict[UUID, list[UUID]]:
        """
        Build adjacency list: {kpi_id: [dependent_kpi_ids]}.
        A dependency exists when a variable's source_type is KPI_ACTUAL.
        """
        graph: dict[UUID, list[UUID]] = {}
        kpi_code_to_id = {k.code: k.id for k in all_kpis}

        for var in all_variables:
            if var.source_type == VariableSourceType.KPI_ACTUAL:
                dep_code = var.source_config.get("kpi_code")
                dep_id = kpi_code_to_id.get(dep_code)
                if dep_id:
                    if var.kpi_id not in graph:
                        graph[var.kpi_id] = []
                    graph[var.kpi_id].append(dep_id)

        return graph

    def detect_cycle(self, graph: dict[UUID, list[UUID]], start: UUID) -> list[str] | None:
        """
        DFS cycle detection starting from `start` node.
        Returns the cycle path as list of KPI IDs (as strings) if cycle found, else None.
        """
        visited = set()
        path = []

        def dfs(node: UUID) -> bool:
            if node in path:
                cycle_start = path.index(node)
                return True
            if node in visited:
                return False
            visited.add(node)
            path.append(node)
            for neighbour in graph.get(node, []):
                if dfs(neighbour):
                    return True
            path.pop()
            return False

        if dfs(start):
            return [str(n) for n in path]
        return None


# ── Formula Evaluator ─────────────────────────────────────────────────────────

class FormulaEvaluator:
    """
    Safely evaluates a formula expression given a dict of resolved variable values.

    Usage:
        evaluator = FormulaEvaluator()
        result = evaluator.evaluate(
            expression="(REVENUE - EXPENSES) / REVENUE * 100",
            variables={"REVENUE": Decimal("1200000"), "EXPENSES": Decimal("850000")}
        )
        # result = Decimal("29.17")

    Security:
        - Uses ast.parse() + restricted node visitor — no eval()
        - Only numeric values, arithmetic, and whitelisted functions
        - Division by zero → returns 0.0 (configurable)
        - All inputs are Decimal for precision
    """

    SAFE_BUILTINS = {
        "abs":      abs,
        "round":    round,
        "min":      min,
        "max":      max,
        "if_func":  lambda condition, true_val, false_val: true_val if condition else false_val,
    }

    def evaluate(
        self,
        expression: str,
        variables: dict[str, Decimal],
        decimal_places: int = 4,
        zero_on_division: bool = True,
    ) -> Decimal:
        """
        Evaluate the formula expression with the given variable values.

        Args:
            expression:       The formula string (e.g. "(REVENUE - EXPENSES) / REVENUE * 100")
            variables:        Dict mapping variable names to their Decimal values
            decimal_places:   Rounding precision for the result
            zero_on_division: If True, return 0 on ZeroDivisionError (default True for safety)

        Returns:
            Decimal: The computed result, rounded to decimal_places

        Raises:
            MissingVariableError: If a required variable is not in `variables`
            EvaluationError: If evaluation fails for any other reason
        """
        # Normalise function names (IF → if_func, ABS → abs, etc.)
        normalised = re.sub(r'\bIF\b',    'if_func', expression, flags=re.IGNORECASE)
        normalised = re.sub(r'\bABS\b',   'abs',     normalised,  flags=re.IGNORECASE)
        normalised = re.sub(r'\bROUND\b', 'round',   normalised,  flags=re.IGNORECASE)
        normalised = re.sub(r'\bMIN\b',   'min',     normalised,  flags=re.IGNORECASE)
        normalised = re.sub(r'\bMAX\b',   'max',     normalised,  flags=re.IGNORECASE)

        # Build safe namespace: variable values + whitelisted functions
        namespace = {**self.SAFE_BUILTINS}
        for var_name, var_value in variables.items():
            namespace[var_name] = float(var_value)  # ast eval works with float

        # Check all referenced variable names are provided
        referenced = FormulaParser().extract_variable_names(expression)
        for name in referenced:
            if name not in namespace:
                raise MissingVariableError(name)

        try:
            tree = ast.parse(normalised, mode='eval')
            result = _safe_eval_ast(tree.body, namespace)
            return Decimal(str(result)).quantize(Decimal(10) ** -decimal_places)
        except MissingVariableError:
            raise
        except ZeroDivisionError:
            if zero_on_division:
                return Decimal("0.0")
            raise EvaluationError("Division by zero in formula")
        except Exception as e:
            raise EvaluationError(f"Formula evaluation failed: {e}")


def _safe_eval_ast(node: ast.AST, namespace: dict) -> float:
    """
    Recursively evaluate an AST node.
    Only whitelisted node types are processed — anything else raises EvaluationError.
    """
    BINOP_MAP = {
        ast.Add:  operator.add,
        ast.Sub:  operator.sub,
        ast.Mult: operator.mul,
        ast.Div:  operator.truediv,
        ast.Pow:  operator.pow,
        ast.Mod:  operator.mod,
    }
    CMPOP_MAP = {
        ast.Lt:    operator.lt,
        ast.LtE:   operator.le,
        ast.Gt:    operator.gt,
        ast.GtE:   operator.ge,
        ast.Eq:    operator.eq,
        ast.NotEq: operator.ne,
    }

    if isinstance(node, ast.Constant):
        return float(node.value)
    elif isinstance(node, ast.Name):
        if node.id not in namespace:
            raise MissingVariableError(node.id)
        return float(namespace[node.id])
    elif isinstance(node, ast.BinOp):
        op = BINOP_MAP.get(type(node.op))
        if op is None:
            raise EvaluationError(f"Unsupported operator: {type(node.op).__name__}")
        left = _safe_eval_ast(node.left, namespace)
        right = _safe_eval_ast(node.right, namespace)
        return op(left, right)
    elif isinstance(node, ast.UnaryOp):
        operand = _safe_eval_ast(node.operand, namespace)
        if isinstance(node.op, ast.USub):
            return -operand
        return operand
    elif isinstance(node, ast.Call):
        func_name = node.func.id if isinstance(node.func, ast.Name) else None
        if func_name not in namespace:
            raise EvaluationError(f"Function not found: {func_name}")
        args = [_safe_eval_ast(arg, namespace) for arg in node.args]
        return namespace[func_name](*args)
    elif isinstance(node, ast.Compare):
        left = _safe_eval_ast(node.left, namespace)
        for op_node, comparator in zip(node.ops, node.comparators):
            op = CMPOP_MAP.get(type(op_node))
            right = _safe_eval_ast(comparator, namespace)
            if not op(left, right):
                return False
            left = right
        return True
    else:
        raise EvaluationError(f"Unsupported AST node type: {type(node).__name__}")
```

---

## Part D — Backend: Data Sync Service

### D1. `app/integrations/data_sync_service.py`

```python
class DataSyncService:
    """
    Orchestrates fetching variable values from external sources
    and storing them in variable_actuals.

    Responsibilities:
      1. Route each variable to the correct adapter
      2. Store results in variable_actuals with full metadata
      3. Handle partial failures gracefully (some variables succeed, some fail)
      4. Provide resolved variable dict to FormulaEvaluator
    """

    def __init__(self):
        self.evaluator = FormulaEvaluator()

    async def sync_variable(
        self, db: AsyncSession, variable: KPIVariable, period_date: date
    ) -> VariableActual:
        """
        Fetch current value for one variable from its configured source.
        Marks previous value for this period as is_current=False.
        """
        if variable.source_type == VariableSourceType.MANUAL:
            raise ValueError("Manual variables cannot be auto-synced")
        if variable.source_type == VariableSourceType.WEBHOOK_RECEIVE:
            raise ValueError("Webhook variables are push-only")

        adapter = AdapterRegistry.get(variable.source_config["adapter"])
        result = await adapter.fetch(variable.source_config, period_date, variable)

        # Supersede any existing value for this period
        await db.execute(
            update(VariableActual)
            .where(VariableActual.variable_id == variable.id)
            .where(VariableActual.period_date == period_date)
            .where(VariableActual.is_current == True)
            .values(is_current=False)
        )

        actual = VariableActual(
            variable_id=variable.id,
            kpi_id=variable.kpi_id,
            period_date=period_date,
            raw_value=result.value if result.success else (variable.default_value or Decimal("0")),
            source_type=variable.source_type,
            sync_metadata=result.metadata,
            is_current=True,
        )
        db.add(actual)

        # Update variable sync status
        variable.last_synced_at = datetime.now(timezone.utc)
        variable.last_sync_status = SyncStatus.SUCCESS if result.success else SyncStatus.FAILED
        variable.last_sync_error = result.error

        await db.commit()
        await db.refresh(actual)
        return actual

    async def sync_all_auto_variables_for_kpi(
        self, db: AsyncSession, kpi_id: UUID, period_date: date
    ) -> dict[str, VariableActual]:
        """
        Sync all non-manual variables for a KPI.
        Returns dict: {"REVENUE": VariableActual, "HEADCOUNT": VariableActual}
        Does NOT sync manual or webhook variables.
        """
        variables = await self._get_kpi_variables(db, kpi_id)
        results = {}
        for var in variables:
            if var.source_type not in (VariableSourceType.MANUAL, VariableSourceType.WEBHOOK_RECEIVE):
                if var.auto_sync_enabled:
                    actual = await self.sync_variable(db, var, period_date)
                    results[var.variable_name] = actual
        return results

    async def get_resolved_values(
        self, db: AsyncSession, kpi_id: UUID, period_date: date
    ) -> dict[str, Decimal]:
        """
        Get current values for ALL variables for a KPI+period.
        Returns dict ready for FormulaEvaluator: {"REVENUE": Decimal("1200000"), ...}

        Raises:
            MissingVariableError: if a required variable has no value
        """
        variables = await self._get_kpi_variables(db, kpi_id)
        resolved = {}
        missing_required = []

        for var in variables:
            actual = await self._get_latest_actual(db, var.id, period_date)
            if actual:
                resolved[var.variable_name] = actual.raw_value
            elif not var.is_required and var.default_value is not None:
                resolved[var.variable_name] = var.default_value
            elif var.is_required:
                missing_required.append(var.variable_name)

        if missing_required:
            raise MissingVariableError(
                f"Required variables missing for period {period_date}: {missing_required}"
            )

        return resolved

    async def compute_formula_actual(
        self,
        db: AsyncSession,
        kpi: KPI,
        period_date: date,
        trigger_source: str = "manual",
    ) -> Decimal:
        """
        Complete pipeline:
          1. Auto-sync all non-manual variables
          2. Get resolved variable values (manual + synced)
          3. Evaluate formula expression
          4. Return computed KPI actual value

        This is the SINGLE ENTRY POINT for computing formula KPI actuals.
        """
        if kpi.data_source != DataSourceType.FORMULA:
            raise ValueError(f"KPI {kpi.code} is not a formula KPI")

        # Step 1: Auto-sync
        await self.sync_all_auto_variables_for_kpi(db, kpi.id, period_date)

        # Step 2: Get all values (manual entries were stored separately via actuals API)
        resolved_values = await self.get_resolved_values(db, kpi.id, period_date)

        # Step 3: Evaluate
        result = self.evaluator.evaluate(
            expression=kpi.formula_expression,
            variables=resolved_values,
            decimal_places=kpi.decimal_places,
        )

        return result

    async def validate_formula_with_variables(
        self, db: AsyncSession, kpi_id: UUID, expression: str
    ) -> dict:
        """
        Full validation: syntax + variable existence + circular dependency check.
        Returns {"valid": bool, "errors": list[str], "referenced_variables": list[str]}
        """
        parser = FormulaParser()
        errors = parser.validate_syntax(expression)

        variables = await self._get_kpi_variables(db, kpi_id)
        variable_names = [v.variable_name for v in variables]
        errors += parser.validate_variables_exist(expression, variable_names)

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "referenced_variables": parser.extract_variable_names(expression),
            "defined_variables": variable_names,
            "undefined_in_formula": [
                name for name in parser.extract_variable_names(expression)
                if name not in variable_names
            ],
        }
```

---

## Part E — Backend: New Endpoints

### E1. Variable Management — add to `app/kpis/router.py`

```
GET    /kpis/{kpi_id}/variables/                  → list variables for a KPI
POST   /kpis/{kpi_id}/variables/                  → create variable (hr_admin, manager)
GET    /kpis/{kpi_id}/variables/{var_id}          → get variable detail
PUT    /kpis/{kpi_id}/variables/{var_id}          → update variable config
DELETE /kpis/{kpi_id}/variables/{var_id}          → delete variable (if not in use)
PATCH  /kpis/{kpi_id}/variables/reorder           → update display_order for all vars
POST   /kpis/{kpi_id}/variables/{var_id}/test-sync → test sync for a period (hr_admin)
```

### E2. Variable Actuals — add to `app/actuals/router.py`

```
POST   /actuals/variables/                        → submit manual variable value(s)
GET    /actuals/variables/{kpi_id}/{period}       → get all variable values for a KPI+period
POST   /actuals/variables/bulk-sync/{kpi_id}      → trigger auto-sync for all non-manual vars
```

### E3. Integration Webhooks — new `app/integrations/router.py`

```
POST   /integrations/push/{endpoint_key}          → receive pushed variable value (public, key-auth)
GET    /integrations/adapters/                    → list available adapters + their config schemas
POST   /integrations/adapters/test                → test a source_config without saving it
GET    /integrations/variables/{kpi_id}/status    → sync status for all variables
```

---

## Part F — Frontend Changes

### F1. New TypeScript Types — `src/types/integration.types.ts`

```typescript
export interface KPIVariable {
  id: string;
  kpi_id: string;
  variable_name: string;       // e.g. "REVENUE" — matches formula reference
  display_label: string;       // e.g. "Total Monthly Revenue (MYR)"
  description: string | null;
  data_type: VariableDataType;
  unit_label: string | null;
  source_type: VariableSourceType;
  source_config: Record<string, any> | null;
  is_required: boolean;
  default_value: number | null;
  auto_sync_enabled: boolean;
  last_synced_at: string | null;
  last_sync_status: SyncStatus;
  last_sync_error: string | null;
  display_order: number;
}

export interface VariableWithCurrentValue extends KPIVariable {
  current_value: number | null;       // latest variable_actual.raw_value
  current_period: string | null;      // "2025-03"
  synced_minutes_ago: number | null;
  needs_manual_entry: boolean;        // source_type === 'manual' && current_value === null
}

export interface AdapterSchema {
  name: string;
  description: string;
  fields: AdapterField[];
}

export interface AdapterField {
  name: string;
  type: 'string' | 'select' | 'number' | 'kvpairs' | 'list' | 'sql' | 'secret_ref' | 'readonly';
  label: string;
  required: boolean;
  hint?: string;
  options?: string[];
  default?: any;
}
```

---

### F2. Update Actuals Entry Page — `src/features/actuals/components/ActualEntryPage.tsx`

For formula KPIs, replace the single value input with a **variable entry panel**:

```
┌─────────────────────────────────────────────────────────────────┐
│  Revenue Growth — March 2025                                     │
│  Formula: (REVENUE - EXPENSES) / REVENUE × 100                  │
│                                                                  │
│  INPUT VARIABLES                                                 │
│  ──────────────────────────────────────────────────────────────  │
│  REVENUE  — Total Monthly Revenue (MYR)                          │
│  Source: SAP ERP (auto-synced)                                   │
│  ✅ MYR 1,200,000   [Synced 5 min ago]  [🔄 Refresh]            │
│                                                                  │
│  EXPENSES — Total Operating Expenses (MYR)                       │
│  Source: Manual entry required                                   │
│  MYR [__________________]   ← employee must enter this          │
│                                                                  │
│  HEADCOUNT — Active Employee Count                               │
│  Source: HRMS API (auto-synced)                                  │
│  ✅ 47 employees   [Synced 2 hours ago]  [🔄 Refresh]           │
│                                                                  │
│  ──────────────────────────────────────────────────────────────  │
│  COMPUTED RESULT (live preview)                                  │
│  (1,200,000 - [EXPENSES]) / 1,200,000 × 100                     │
│  = 29.17%  ← updates as you type EXPENSES                       │
│                                                                  │
│  vs Target: 15.0%   Achievement: 194.5%   ★ Exceptional         │
│                                                                  │
│  [Submit]  [Save Draft]                                          │
└─────────────────────────────────────────────────────────────────┘
```

**Implementation notes:**
- Auto-synced variables show last sync time and a Refresh button (calls `/actuals/variables/bulk-sync/{kpi_id}`)
- Manual variables render an input field, validated against `data_type` (number, integer, currency)
- Live preview: as user types manual values, client-side formula evaluator computes result instantly
- Client-side formula evaluator (TypeScript port of backend logic):

```typescript
// src/lib/formulaEvaluator.ts
export function evaluateFormula(
  expression: string,
  variables: Record<string, number | null>,
): { result: number | null; error: string | null } {
  // Simple safe evaluation: replace variable names with values, use Function constructor
  // Only allow if all variables are resolved (no nulls)
  const missingVars = Object.entries(variables)
    .filter(([, v]) => v === null)
    .map(([k]) => k);

  if (missingVars.length > 0) {
    return { result: null, error: `Waiting for: ${missingVars.join(', ')}` };
  }

  try {
    let expr = expression;
    for (const [name, value] of Object.entries(variables)) {
      expr = expr.replaceAll(new RegExp(`\\b${name}\\b`, 'g'), String(value));
    }
    // Safe: only numbers and operators remain after substitution
    const sanitized = expr.replace(/[^0-9+\-*/.()% ]/g, '');
    if (sanitized !== expr) {
      return { result: null, error: 'Formula contains unexpected characters' };
    }
    // eslint-disable-next-line no-new-func
    const result = new Function(`"use strict"; return (${sanitized})`)() as number;
    return { result: isFinite(result) ? result : null, error: isFinite(result) ? null : 'Result is not finite' };
  } catch (e) {
    return { result: null, error: `Evaluation error: ${e}` };
  }
}
```

---

### F3. New Component — Variable Manager — `src/features/kpis/components/KPIVariableManager.tsx`

A tab inside the KPI detail drawer / KPI builder Step 3:

```
VARIABLES (for formula KPIs only)
──────────────────────────────────────────────────────────
[+ Add Variable]                    [Test All Syncs]

  ⠿  REVENUE   Total Monthly Revenue    REST API   ✅ Synced 5m ago  [Edit] [Delete]
  ⠿  EXPENSES  Operating Expenses       Manual     ⚠️ Needs entry    [Edit] [Delete]
  ⠿  HEADCOUNT Active Employees         HRMS API   ✅ Synced 2h ago  [Edit] [Delete]

Variable: EXPENSES
  Display Label: Operating Expenses (MYR)
  Data Type: Currency (MYR)
  Source: Manual ← employee enters each period
  Required: Yes
  [Save Variable]
```

---

### F4. New Component — Adapter Config Form — `src/features/integrations/components/AdapterConfigForm.tsx`

Renders dynamically based on `AdapterSchema.fields` fetched from `/integrations/adapters/`:

```
Source Type: [REST API ▾]

  Endpoint URL:
  [https://erp.company.com/api/v1/sales?month={period.iso}    ]
  ℹ️ Use {period.iso} for YYYY-MM, {period.year}, {period.month}

  HTTP Method: [GET ▾]

  Headers (key: value):
  Authorization: [Bearer {SECRET:ERP_TOKEN}                   ]
  + Add header

  Response JSON Path:
  [data.total_amount                                          ]

  Timeout: [30] seconds

  [🔬 Test Connection]  ← calls /integrations/adapters/test
  Result: ✅ Connected — value: MYR 1,234,567.00 for March 2025
```

---

## Part G — Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│          FORMULA KPI DATA FLOW — END TO END                          │
│                                                                       │
│  KPI Definition                                                       │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │  code: REVENUE_GROWTH                                        │    │
│  │  formula: (REVENUE - EXPENSES) / REVENUE * 100               │    │
│  │  data_source: formula                                        │    │
│  │  variables:                                                  │    │
│  │    REVENUE  → REST API (ERP)  auto_sync=True                │    │
│  │    EXPENSES → Manual          is_required=True              │    │
│  └──────────────────────────────────────────────────────────────┘    │
│                          │                                            │
│              ┌───────────▼────────────┐                              │
│              │  DataSyncService       │                              │
│              │  .compute_formula_     │                              │
│              │   actual()             │                              │
│              └───────────┬────────────┘                              │
│                          │                                            │
│      ┌───────────────────┼────────────────────┐                     │
│      │                   │                    │                     │
│      ▼                   ▼                    ▼                     │
│  ┌────────────┐   ┌────────────────┐   ┌──────────────────┐        │
│  │ REVENUE    │   │ EXPENSES       │   │ Result stored    │        │
│  │ source:    │   │ source: manual │   │ in              │        │
│  │ REST API   │   │                │   │ kpi_actuals      │        │
│  │            │   │ Employee enters│   │ + variable_      │        │
│  │ AdapterReg │   │ on UI          │   │ actuals (audit)  │        │
│  │ .get(      │   │                │   └──────────────────┘        │
│  │"rest_api") │   │ Stored via     │                               │
│  │            │   │ /actuals/      │                               │
│  │ → fetch()  │   │ variables/     │                               │
│  └─────┬──────┘   └───────┬────────┘                               │
│        │                  │                                          │
│        └──────────┬────────┘                                         │
│                   │                                                   │
│           ┌───────▼──────────┐                                       │
│           │ FormulaEvaluator │                                       │
│           │ .evaluate(       │                                       │
│           │   "(REVENUE -    │                                       │
│           │    EXPENSES) /   │                                       │
│           │    REVENUE*100", │                                       │
│           │   {REVENUE:      │                                       │
│           │    1200000,      │                                       │
│           │    EXPENSES:     │                                       │
│           │    850000}       │                                       │
│           │ )                │                                       │
│           │ → 29.1667%       │                                       │
│           └──────────────────┘                                       │
│                                                                       │
│  variable_actuals table (full audit):                                 │
│  ┌─────────────┬──────────┬───────────┬─────────────────────────┐   │
│  │ variable    │ period   │ raw_value │ sync_metadata           │   │
│  ├─────────────┼──────────┼───────────┼─────────────────────────┤   │
│  │ REVENUE     │ 2025-03  │ 1200000   │ {adapter:rest_api, ...} │   │
│  │ EXPENSES    │ 2025-03  │ 850000    │ {source_type:manual}    │   │
│  └─────────────┴──────────┴───────────┴─────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Part H — Tests

### `tests/test_formula_evaluator.py`

```python
# Formula parser tests
test_extract_variable_names_simple()          # "(A + B) / A" → ["A", "B"]
test_extract_variable_names_excludes_functions()  # "ABS(X)" → ["X"], not ["ABS","X"]
test_validate_syntax_valid()
test_validate_syntax_empty_fails()
test_validate_syntax_eval_injection_fails()   # "os.system('rm')" → syntax error
test_validate_syntax_import_fails()           # "__import__" → disallowed node
test_validate_variables_all_defined()
test_validate_variables_missing_raises()

# Evaluator tests
test_evaluate_simple_arithmetic()            # "(10 + 5) / 10 * 100" → 150.0
test_evaluate_with_variables()               # "(REVENUE - EXPENSES) / REVENUE * 100"
test_evaluate_zero_division_returns_zero()
test_evaluate_missing_variable_raises()
test_evaluate_if_function()                  # "IF(X > 100, 100, X)" → capped value
test_evaluate_abs_function()                 # "ABS(DELTA)" → always positive
test_evaluate_min_max_functions()
test_evaluate_decimal_precision()            # result rounded to decimal_places
test_evaluate_lower_is_better_inversion()

# Adapter tests
test_rest_api_adapter_success()              # mock httpx response
test_rest_api_adapter_http_error()           # non-200 → AdapterResult(success=False)
test_rest_api_adapter_timeout()
test_database_adapter_rejects_non_select()   # "DELETE FROM ..." → validate_config fails
test_database_adapter_rejects_raw_conn_str() # must use {SECRET:...}
test_json_path_extractor_simple()
test_json_path_extractor_nested()
test_json_path_extractor_array()
test_secret_resolution_found()
test_secret_resolution_missing_raises()
test_period_param_resolution_monthly()
test_period_param_resolution_quarterly()

# DataSyncService tests
test_sync_variable_stores_actual()
test_sync_variable_supersedes_previous()
test_get_resolved_values_all_present()
test_get_resolved_values_missing_required_raises()
test_get_resolved_values_optional_uses_default()
test_compute_formula_actual_full_pipeline()
test_circular_dependency_detection()
test_validate_formula_with_variables_all_valid()
test_validate_formula_with_variables_missing_var()
```

---

## Part I — Alembic Migration

```bash
alembic revision --autogenerate -m "add_kpi_variables_and_variable_actuals"
```

Migration must include:
- `kpi_variables` table with all columns, constraints, and indexes
- `variable_actuals` table with all columns and indexes
- `VariableSourceType` PostgreSQL enum type
- `VariableDataType` PostgreSQL enum type
- `SyncStatus` PostgreSQL enum type