"""
Tests for the formula engine (Part C) and integration infrastructure.

Covers:
  - FormulaParser: extract_variable_names, validate_syntax, validate_variables_exist
  - FormulaEvaluator: arithmetic, variables, functions, division-by-zero, missing vars
  - _safe_eval_ast: no eval() usage
  - BaseAdapter: resolve_secrets, resolve_period_params, extract_json_path
  - RestApiAdapter: validate_config
  - DatabaseAdapter: validate_config security rules
  - AdapterRegistry: registration, get, list
  - DataSyncService: get_resolved_values, validate_formula_with_variables, compute flow
  - Integration API endpoints: /kpis/{id}/variables/ CRUD
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.kpis.formula import (
    CircularDependencyError,
    DependencyResolver,
    EvaluationError,
    FormulaEvaluator,
    FormulaParser,
    FormulaValidationError,
    MissingVariableError,
    _safe_eval_ast,
)

# ---------------------------------------------------------------------------
# Shared helpers for API tests
# ---------------------------------------------------------------------------


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register_and_login(client: AsyncClient, payload: dict) -> str:
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


async def _create_formula_kpi(client: AsyncClient, token: str, suffix: str) -> dict:
    # Use a constant formula so the service doesn't try to resolve variable names
    # as KPI codes (pre-Enhancement-2 behaviour). Variable-vs-formula validation
    # is tested separately via the /validate-formula endpoint.
    payload = {
        "name": f"Variable Test KPI {suffix}",
        "code": f"VAR_TEST_{suffix}",
        "data_source": "formula",
        "formula_expression": "100",
        "unit": "currency",
        "frequency": "monthly",
        "scoring_direction": "higher_is_better",
    }
    r = await client.post("/api/v1/kpis/", json=payload, headers=_auth(token))
    assert r.status_code == 201, r.text
    return r.json()


# =============================================================================
# FormulaParser
# =============================================================================

class TestFormulaParserExtractVariableNames:
    def test_simple_expression(self):
        result = FormulaParser().extract_variable_names("(A + B) / A")
        assert result == ["A", "B"]

    def test_complex_expression(self):
        result = FormulaParser().extract_variable_names(
            "(REVENUE - EXPENSES) / REVENUE * 100"
        )
        assert result == ["REVENUE", "EXPENSES"]

    def test_deduplicates(self):
        result = FormulaParser().extract_variable_names("X + X + Y")
        assert result == ["X", "Y"]

    def test_excludes_function_names(self):
        result = FormulaParser().extract_variable_names("ABS(DELTA)")
        assert "ABS" not in result
        assert "DELTA" in result

    def test_excludes_all_safe_functions(self):
        result = FormulaParser().extract_variable_names(
            "ABS(X) + ROUND(Y, 2) + MIN(A, B) + MAX(C, D)"
        )
        assert set(result) == {"X", "Y", "A", "B", "C", "D"}

    def test_if_function_excluded(self):
        result = FormulaParser().extract_variable_names("IF(X > 100, 100, X)")
        assert "IF" not in result
        assert "X" in result

    def test_empty_expression(self):
        result = FormulaParser().extract_variable_names("")
        assert result == []

    def test_no_variables(self):
        result = FormulaParser().extract_variable_names("10 + 20 * 3")
        assert result == []


class TestFormulaParserValidateSyntax:
    def test_valid_simple(self):
        errors = FormulaParser().validate_syntax("(A + B) / A * 100")
        assert errors == []

    def test_valid_with_if(self):
        errors = FormulaParser().validate_syntax("IF(REVENUE > 0, REVENUE / COST, 0)")
        assert errors == []

    def test_empty_fails(self):
        errors = FormulaParser().validate_syntax("")
        assert len(errors) > 0
        assert "empty" in errors[0].lower()

    def test_syntax_error(self):
        errors = FormulaParser().validate_syntax("((A + B)")
        assert len(errors) > 0

    def test_import_fails(self):
        errors = FormulaParser().validate_syntax("__import__('os').system('rm -rf /')")
        # Should fail — either syntax error or AST validator error
        assert len(errors) > 0

    def test_attribute_access_fails(self):
        errors = FormulaParser().validate_syntax("os.path.join('a', 'b')")
        assert len(errors) > 0

    def test_lowercase_variable_fails(self):
        errors = FormulaParser().validate_syntax("revenue + costs")
        assert len(errors) > 0

    def test_valid_complex_formula(self):
        errors = FormulaParser().validate_syntax(
            "(REVENUE - EXPENSES) / REVENUE * 100"
        )
        assert errors == []


class TestFormulaParserValidateVariablesExist:
    def _parser(self):
        return FormulaParser()

    def test_all_defined(self):
        errors = self._parser().validate_variables_exist(
            "(REVENUE - EXPENSES) / REVENUE",
            ["REVENUE", "EXPENSES"],
        )
        assert errors == []

    def test_missing_variable_reported(self):
        errors = self._parser().validate_variables_exist(
            "(REVENUE - EXPENSES) / REVENUE",
            ["REVENUE"],
        )
        assert len(errors) == 1
        assert "EXPENSES" in errors[0]

    def test_all_missing(self):
        errors = self._parser().validate_variables_exist(
            "A + B + C",
            [],
        )
        assert len(errors) == 3

    def test_empty_formula(self):
        errors = self._parser().validate_variables_exist("", ["REVENUE"])
        assert errors == []


# =============================================================================
# _safe_eval_ast
# =============================================================================

class TestSafeEvalAst:
    """Verify that _safe_eval_ast never uses eval() and handles all node types."""

    import ast as _ast

    def _eval(self, expr: str, ns: dict) -> float:
        import ast
        tree = ast.parse(expr, mode="eval")
        return _safe_eval_ast(tree.body, ns)

    def test_constant(self):
        assert self._eval("42", {}) == 42.0

    def test_binop_add(self):
        assert self._eval("3 + 4", {}) == 7.0

    def test_binop_div(self):
        assert self._eval("10 / 4", {}) == 2.5

    def test_binop_pow(self):
        assert self._eval("2 ** 10", {}) == 1024.0

    def test_unary_neg(self):
        assert self._eval("-X", {"X": 5.0}) == -5.0

    def test_variable_name(self):
        assert self._eval("X + Y", {"X": 3.0, "Y": 7.0}) == 10.0

    def test_missing_variable_raises(self):
        import ast
        tree = ast.parse("MISSING", mode="eval")
        with pytest.raises(MissingVariableError) as exc_info:
            _safe_eval_ast(tree.body, {})
        assert exc_info.value.variable_name == "MISSING"

    def test_function_call(self):
        assert self._eval("abs(NEG)", {"abs": abs, "NEG": -7.0}) == 7.0

    def test_compare_true(self):
        result = self._eval("X > 5", {"X": 10.0})
        assert result is True

    def test_compare_false(self):
        result = self._eval("X > 15", {"X": 10.0})
        assert result is False


# =============================================================================
# FormulaEvaluator
# =============================================================================

class TestFormulaEvaluator:
    _ev = FormulaEvaluator()

    def test_simple_arithmetic(self):
        result = self._ev.evaluate(
            "(10 + 5) / 10 * 100",
            {},
        )
        assert result == Decimal("150.0000")

    def test_with_variables(self):
        result = self._ev.evaluate(
            "(REVENUE - EXPENSES) / REVENUE * 100",
            {"REVENUE": Decimal("1200000"), "EXPENSES": Decimal("850000")},
        )
        assert result == Decimal("29.1667")

    def test_zero_division_returns_zero(self):
        result = self._ev.evaluate("A / B", {"A": Decimal("10"), "B": Decimal("0")})
        assert result == Decimal("0")

    def test_zero_division_raises_when_configured(self):
        with pytest.raises(EvaluationError):
            self._ev.evaluate(
                "A / B",
                {"A": Decimal("10"), "B": Decimal("0")},
                zero_on_division=False,
            )

    def test_missing_variable_raises(self):
        with pytest.raises(MissingVariableError) as exc_info:
            self._ev.evaluate("REVENUE - MISSING", {"REVENUE": Decimal("100")})
        assert exc_info.value.variable_name == "MISSING"

    def test_if_function(self):
        result = self._ev.evaluate(
            "IF(X > 100, 100, X)",
            {"X": Decimal("120")},
        )
        # X=120 > 100, so should return 100
        assert result == Decimal("100.0000")

    def test_if_function_false_branch(self):
        result = self._ev.evaluate(
            "IF(X > 100, 100, X)",
            {"X": Decimal("80")},
        )
        assert result == Decimal("80.0000")

    def test_abs_function(self):
        result = self._ev.evaluate("ABS(DELTA)", {"DELTA": Decimal("-50")})
        assert result == Decimal("50.0000")

    def test_min_max_functions(self):
        r_min = self._ev.evaluate("MIN(A, B)", {"A": Decimal("3"), "B": Decimal("7")})
        assert r_min == Decimal("3.0000")
        r_max = self._ev.evaluate("MAX(A, B)", {"A": Decimal("3"), "B": Decimal("7")})
        assert r_max == Decimal("7.0000")

    def test_decimal_precision(self):
        result = self._ev.evaluate("A / B", {"A": Decimal("1"), "B": Decimal("3")}, decimal_places=2)
        assert result == Decimal("0.33")

    def test_accepts_float_inputs(self):
        """Backward compatibility: accepts float dict just like old kpi_values."""
        result = self._ev.evaluate("REVENUE * 0.1", {"REVENUE": 1000.0})
        assert result == Decimal("100.0000")

    def test_syntax_error_raises(self):
        with pytest.raises(FormulaValidationError):
            self._ev.evaluate("((A + B)", {"A": Decimal("1"), "B": Decimal("2")})

    def test_nested_formula(self):
        result = self._ev.evaluate(
            "ROUND((A + B) / 2, 0)",
            {"A": Decimal("3"), "B": Decimal("7")},
        )
        assert result == Decimal("5.0000")


# =============================================================================
# Exceptions
# =============================================================================

class TestExceptions:
    def test_formula_validation_error_has_position(self):
        exc = FormulaValidationError("syntax error", position=5)
        assert exc.position == 5
        assert exc.detail == "syntax error"

    def test_circular_dependency_error_has_cycle_path(self):
        path = ["A", "B", "C", "A"]
        exc = CircularDependencyError("cycle!", cycle_path=path)
        assert exc.cycle_path == path

    def test_missing_variable_error_has_name(self):
        exc = MissingVariableError("REVENUE")
        assert exc.variable_name == "REVENUE"
        assert "REVENUE" in str(exc)


# =============================================================================
# AdapterRegistry
# =============================================================================

class TestAdapterRegistry:
    def test_register_and_get(self):
        from app.integrations.adapter_registry import AdapterRegistry
        from app.integrations.adapters.base import BaseAdapter, AdapterResult

        class _TestAdapter(BaseAdapter):
            async def fetch(self, config, period_date, variable):
                return AdapterResult(Decimal("1"), {})

            def validate_config(self, config):
                return []

            def get_config_schema(self):
                return {}

        name = f"_test_{uuid4().hex[:8]}"
        AdapterRegistry.register(name, _TestAdapter)
        adapter = AdapterRegistry.get(name)
        assert isinstance(adapter, _TestAdapter)

    def test_get_unknown_raises(self):
        from app.integrations.adapter_registry import AdapterRegistry

        with pytest.raises(ValueError, match="Unknown adapter"):
            AdapterRegistry.get("nonexistent_adapter_xyz")

    def test_register_builtin_adapters_idempotent(self):
        from app.integrations.adapter_registry import register_builtin_adapters
        register_builtin_adapters()
        register_builtin_adapters()  # Should not raise

    def test_list_available_returns_schemas(self):
        from app.integrations.adapter_registry import AdapterRegistry, register_builtin_adapters
        register_builtin_adapters()
        available = AdapterRegistry.list_available()
        names = {a["name"] for a in available}
        assert "rest_api" in names
        assert "database" in names


# =============================================================================
# BaseAdapter utilities
# =============================================================================

class TestBaseAdapterUtilities:
    def _make_adapter(self):
        from app.integrations.adapters.rest_api import RestApiAdapter
        return RestApiAdapter()

    def test_resolve_period_params_year(self):
        adapter = self._make_adapter()
        result = adapter.resolve_period_params("{period.year}", date(2025, 3, 1))
        assert result == "2025"

    def test_resolve_period_params_month(self):
        adapter = self._make_adapter()
        result = adapter.resolve_period_params("{period.month}", date(2025, 3, 1))
        assert result == "3"

    def test_resolve_period_params_month_padded(self):
        adapter = self._make_adapter()
        result = adapter.resolve_period_params("{period.month_padded}", date(2025, 3, 1))
        assert result == "03"

    def test_resolve_period_params_quarter(self):
        adapter = self._make_adapter()
        result = adapter.resolve_period_params("{period.quarter}", date(2025, 4, 1))
        assert result == "2"

    def test_resolve_period_params_iso(self):
        adapter = self._make_adapter()
        result = adapter.resolve_period_params("{period.iso}", date(2025, 3, 1))
        assert result == "2025-03"

    def test_resolve_secrets_found(self, monkeypatch):
        monkeypatch.setenv("PMS_SECRET_MY_KEY", "supersecret")
        adapter = self._make_adapter()
        config = {"token": "{SECRET:MY_KEY}"}
        result = adapter.resolve_secrets(config)
        assert result["token"] == "supersecret"

    def test_resolve_secrets_missing_raises(self, monkeypatch):
        monkeypatch.delenv("PMS_SECRET_NONEXISTENT", raising=False)
        adapter = self._make_adapter()
        config = {"token": "{SECRET:NONEXISTENT}"}
        with pytest.raises(ValueError, match="not found in environment"):
            adapter.resolve_secrets(config)

    def test_extract_json_path_simple(self):
        adapter = self._make_adapter()
        data = {"data": {"total": 1234}}
        assert adapter.extract_json_path(data, "data.total") == 1234

    def test_extract_json_path_array(self):
        adapter = self._make_adapter()
        data = {"results": [{"amount": 99.5}]}
        assert adapter.extract_json_path(data, "results[0].amount") == 99.5

    def test_extract_json_path_nested(self):
        adapter = self._make_adapter()
        data = {"a": {"b": {"c": 42}}}
        assert adapter.extract_json_path(data, "a.b.c") == 42


# =============================================================================
# RestApiAdapter
# =============================================================================

class TestRestApiAdapterValidateConfig:
    def _adapter(self):
        from app.integrations.adapters.rest_api import RestApiAdapter
        return RestApiAdapter()

    def test_valid_config(self):
        errors = self._adapter().validate_config({
            "url": "https://example.com/api",
            "response_path": "data.value",
        })
        assert errors == []

    def test_missing_url(self):
        errors = self._adapter().validate_config({"response_path": "data.value"})
        assert any("url" in e for e in errors)

    def test_missing_response_path(self):
        errors = self._adapter().validate_config({"url": "https://example.com"})
        assert any("response_path" in e for e in errors)

    def test_get_config_schema(self):
        schema = self._adapter().get_config_schema()
        field_names = [f["name"] for f in schema["fields"]]
        assert "url" in field_names
        assert "response_path" in field_names


# =============================================================================
# DatabaseAdapter
# =============================================================================

class TestDatabaseAdapterValidateConfig:
    def _adapter(self):
        from app.integrations.adapters.database import DatabaseAdapter
        return DatabaseAdapter()

    def test_rejects_non_select(self):
        errors = self._adapter().validate_config({
            "connection_string": "{SECRET:DB}",
            "query": "DELETE FROM users",
        })
        assert any("SELECT" in e for e in errors)

    def test_rejects_raw_connection_string(self):
        errors = self._adapter().validate_config({
            "connection_string": "postgresql://user:pass@host/db",
            "query": "SELECT 1",
        })
        assert any("SECRET" in e for e in errors)

    def test_rejects_forbidden_keyword_in_query(self):
        errors = self._adapter().validate_config({
            "connection_string": "{SECRET:DB}",
            "query": "SELECT 1; DROP TABLE users",
        })
        assert len(errors) > 0

    def test_valid_config(self):
        errors = self._adapter().validate_config({
            "connection_string": "{SECRET:SALES_DB}",
            "query": "SELECT SUM(amount) FROM sales WHERE year = :year",
        })
        assert errors == []


# =============================================================================
# DependencyResolver (new)
# =============================================================================

class TestDependencyResolver:
    def test_no_cycle(self):
        resolver = DependencyResolver()
        kpi_a_id = uuid4()
        kpi_b_id = uuid4()
        graph = {kpi_a_id: [kpi_b_id], kpi_b_id: []}
        result = resolver.detect_cycle(graph, kpi_a_id)
        assert result is None

    def test_direct_cycle(self):
        resolver = DependencyResolver()
        kpi_a_id = uuid4()
        graph = {kpi_a_id: [kpi_a_id]}
        result = resolver.detect_cycle(graph, kpi_a_id)
        assert result is not None

    def test_indirect_cycle(self):
        resolver = DependencyResolver()
        a, b, c = uuid4(), uuid4(), uuid4()
        graph = {a: [b], b: [c], c: [a]}
        result = resolver.detect_cycle(graph, a)
        assert result is not None
        assert len(result) > 0


# =============================================================================
# DataSyncService — unit tests (mocked DB)
# =============================================================================

@pytest.mark.asyncio
class TestDataSyncService:
    async def test_validate_formula_with_variables_valid(self):
        from app.integrations.data_sync_service import DataSyncService
        from app.integrations.enums import VariableSourceType, VariableDataType, SyncStatus
        from app.integrations.models import KPIVariable

        service = DataSyncService()

        # Mock DB
        mock_var = MagicMock()
        mock_var.variable_name = "REVENUE"
        mock_var.source_type = VariableSourceType.MANUAL

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_var]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await service.validate_formula_with_variables(
            mock_db, uuid4(), "REVENUE * 100"
        )
        assert result["valid"] is True
        assert result["errors"] == []
        assert "REVENUE" in result["referenced_variables"]

    async def test_validate_formula_missing_variable(self):
        from app.integrations.data_sync_service import DataSyncService

        service = DataSyncService()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []  # no variables defined

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await service.validate_formula_with_variables(
            mock_db, uuid4(), "REVENUE + COST"
        )
        assert result["valid"] is False
        assert len(result["errors"]) > 0
        assert "REVENUE" in result["undefined_in_formula"]
        assert "COST" in result["undefined_in_formula"]

    async def test_get_resolved_values_all_present(self):
        from app.integrations.data_sync_service import DataSyncService
        from app.integrations.enums import VariableSourceType
        from app.integrations.models import KPIVariable, VariableActual

        service = DataSyncService()
        kpi_id = uuid4()
        var_id = uuid4()
        today = date.today()

        mock_var = MagicMock()
        mock_var.id = var_id
        mock_var.variable_name = "REVENUE"
        mock_var.is_required = True
        mock_var.default_value = None

        mock_actual = MagicMock()
        mock_actual.raw_value = Decimal("1200000.0000")

        # Two execute calls: list vars, then get each actual
        vars_result = MagicMock()
        vars_result.scalars.return_value.all.return_value = [mock_var]

        actual_result = MagicMock()
        actual_result.scalar_one_or_none.return_value = mock_actual

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[vars_result, actual_result])

        resolved = await service.get_resolved_values(mock_db, kpi_id, today)
        assert "REVENUE" in resolved
        assert resolved["REVENUE"] == Decimal("1200000.0000")

    async def test_get_resolved_values_missing_required_raises(self):
        from app.integrations.data_sync_service import DataSyncService

        service = DataSyncService()

        mock_var = MagicMock()
        mock_var.id = uuid4()
        mock_var.variable_name = "EXPENSES"
        mock_var.is_required = True
        mock_var.default_value = None

        vars_result = MagicMock()
        vars_result.scalars.return_value.all.return_value = [mock_var]

        actual_result = MagicMock()
        actual_result.scalar_one_or_none.return_value = None  # no value

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[vars_result, actual_result])

        with pytest.raises(MissingVariableError):
            await service.get_resolved_values(mock_db, uuid4(), date.today())

    async def test_get_resolved_values_optional_uses_default(self):
        from app.integrations.data_sync_service import DataSyncService

        service = DataSyncService()

        mock_var = MagicMock()
        mock_var.id = uuid4()
        mock_var.variable_name = "HEADCOUNT"
        mock_var.is_required = False
        mock_var.default_value = Decimal("50")

        vars_result = MagicMock()
        vars_result.scalars.return_value.all.return_value = [mock_var]

        actual_result = MagicMock()
        actual_result.scalar_one_or_none.return_value = None  # no synced value

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[vars_result, actual_result])

        resolved = await service.get_resolved_values(mock_db, uuid4(), date.today())
        assert resolved["HEADCOUNT"] == Decimal("50")


# =============================================================================
# Integration API tests — KPI Variable endpoints (using AsyncClient / test DB)
# =============================================================================

# =============================================================================
# Integration API tests — KPI Variable endpoints
# =============================================================================

@pytest.mark.asyncio
async def test_list_variables_empty(async_client: AsyncClient) -> None:
    token = await _register_and_login(async_client, {
        "user": {"username": "varlist_u", "email": "varlist@t.com", "full_name": "X", "role": "hr_admin", "password": "password123"},
        "organisation": {"name": "VarList Org", "slug": "varlist-org"},
    })
    kpi = await _create_formula_kpi(async_client, token, "LIST01")
    r = await async_client.get(f"/api/v1/kpis/{kpi['id']}/variables/", headers=_auth(token))
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_create_and_get_variable(async_client: AsyncClient) -> None:
    token = await _register_and_login(async_client, {
        "user": {"username": "varcreate_u", "email": "varcreate@t.com", "full_name": "X", "role": "hr_admin", "password": "password123"},
        "organisation": {"name": "VarCreate Org", "slug": "varcreate-org"},
    })
    kpi = await _create_formula_kpi(async_client, token, "CREATE01")
    kpi_id = kpi["id"]

    var_payload = {
        "variable_name": "REVENUE",
        "display_label": "Total Monthly Revenue",
        "data_type": "currency",
        "source_type": "manual",
        "is_required": True,
    }
    r = await async_client.post(
        f"/api/v1/kpis/{kpi_id}/variables/", json=var_payload, headers=_auth(token)
    )
    assert r.status_code == 201, r.text
    var = r.json()
    assert var["variable_name"] == "REVENUE"
    assert var["source_type"] == "manual"
    var_id = var["id"]

    r2 = await async_client.get(
        f"/api/v1/kpis/{kpi_id}/variables/{var_id}", headers=_auth(token)
    )
    assert r2.status_code == 200
    assert r2.json()["id"] == var_id

    r3 = await async_client.get(
        f"/api/v1/kpis/{kpi_id}/variables/", headers=_auth(token)
    )
    assert r3.status_code == 200
    assert len(r3.json()) == 1


@pytest.mark.asyncio
async def test_duplicate_variable_name_fails(async_client: AsyncClient) -> None:
    token = await _register_and_login(async_client, {
        "user": {"username": "vardup_u", "email": "vardup@t.com", "full_name": "X", "role": "hr_admin", "password": "password123"},
        "organisation": {"name": "VarDup Org", "slug": "vardup-org"},
    })
    kpi = await _create_formula_kpi(async_client, token, "DUP01")
    kpi_id = kpi["id"]

    var_payload = {
        "variable_name": "COST",
        "display_label": "Cost",
        "source_type": "manual",
    }
    r1 = await async_client.post(
        f"/api/v1/kpis/{kpi_id}/variables/", json=var_payload, headers=_auth(token)
    )
    assert r1.status_code == 201

    r2 = await async_client.post(
        f"/api/v1/kpis/{kpi_id}/variables/", json=var_payload, headers=_auth(token)
    )
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_update_variable(async_client: AsyncClient) -> None:
    token = await _register_and_login(async_client, {
        "user": {"username": "varupdate_u", "email": "varupdate@t.com", "full_name": "X", "role": "hr_admin", "password": "password123"},
        "organisation": {"name": "VarUpdate Org", "slug": "varupdate-org"},
    })
    kpi = await _create_formula_kpi(async_client, token, "UPDATE01")
    kpi_id = kpi["id"]

    r = await async_client.post(
        f"/api/v1/kpis/{kpi_id}/variables/",
        json={"variable_name": "EXPENSE", "display_label": "Old Label", "source_type": "manual"},
        headers=_auth(token),
    )
    var_id = r.json()["id"]

    update_r = await async_client.put(
        f"/api/v1/kpis/{kpi_id}/variables/{var_id}",
        json={"display_label": "Updated Label", "is_required": False},
        headers=_auth(token),
    )
    assert update_r.status_code == 200
    assert update_r.json()["display_label"] == "Updated Label"
    assert update_r.json()["is_required"] is False


@pytest.mark.asyncio
async def test_delete_variable(async_client: AsyncClient) -> None:
    token = await _register_and_login(async_client, {
        "user": {"username": "vardelete_u", "email": "vardelete@t.com", "full_name": "X", "role": "hr_admin", "password": "password123"},
        "organisation": {"name": "VarDelete Org", "slug": "vardelete-org"},
    })
    kpi = await _create_formula_kpi(async_client, token, "DELETE01")
    kpi_id = kpi["id"]

    r = await async_client.post(
        f"/api/v1/kpis/{kpi_id}/variables/",
        json={"variable_name": "UNITS", "display_label": "Units", "source_type": "manual"},
        headers=_auth(token),
    )
    var_id = r.json()["id"]

    del_r = await async_client.delete(
        f"/api/v1/kpis/{kpi_id}/variables/{var_id}", headers=_auth(token)
    )
    assert del_r.status_code == 204

    list_r = await async_client.get(
        f"/api/v1/kpis/{kpi_id}/variables/", headers=_auth(token)
    )
    assert list_r.json() == []


@pytest.mark.asyncio
async def test_validate_formula_endpoint(async_client: AsyncClient) -> None:
    token = await _register_and_login(async_client, {
        "user": {"username": "varvalidate_u", "email": "varvalidate@t.com", "full_name": "X", "role": "hr_admin", "password": "password123"},
        "organisation": {"name": "VarValidate Org", "slug": "varvalidate-org"},
    })
    kpi = await _create_formula_kpi(async_client, token, "VALIDATE01")
    kpi_id = kpi["id"]

    await async_client.post(
        f"/api/v1/kpis/{kpi_id}/variables/",
        json={"variable_name": "REVENUE", "display_label": "Revenue", "source_type": "manual"},
        headers=_auth(token),
    )
    await async_client.post(
        f"/api/v1/kpis/{kpi_id}/variables/",
        json={"variable_name": "EXPENSES", "display_label": "Expenses", "source_type": "manual"},
        headers=_auth(token),
    )

    r = await async_client.post(
        f"/api/v1/kpis/{kpi_id}/variables/validate-formula",
        json={"expression": "REVENUE - EXPENSES"},
        headers=_auth(token),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["valid"] is True
    assert data["errors"] == []


@pytest.mark.asyncio
async def test_validate_formula_missing_var_returns_errors(async_client: AsyncClient) -> None:
    token = await _register_and_login(async_client, {
        "user": {"username": "varmiss_u", "email": "varmiss@t.com", "full_name": "X", "role": "hr_admin", "password": "password123"},
        "organisation": {"name": "VarMiss Org", "slug": "varmiss-org"},
    })
    kpi = await _create_formula_kpi(async_client, token, "MISS01")
    kpi_id = kpi["id"]

    # No variables defined
    r = await async_client.post(
        f"/api/v1/kpis/{kpi_id}/variables/validate-formula",
        json={"expression": "REVENUE + COST"},
        headers=_auth(token),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["valid"] is False
    assert len(data["errors"]) > 0
    assert "REVENUE" in data["undefined_in_formula"]
    assert "COST" in data["undefined_in_formula"]

