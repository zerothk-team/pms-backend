"""
Safe formula parser, dependency resolver, and evaluator for KPI formula expressions.

Expressions use uppercase KPI codes (matching kpi.code) as variable references.
Example: (KPI_REVENUE - KPI_COST) / KPI_REVENUE * 100

Supported operators: +  -  *  /  **  (  )
Supported functions: abs()  round()  min()  max()  if(condition, true_val, false_val)

The `if` function is pre-processed to `_if_` before AST parsing, since `if` is a
Python keyword and cannot appear as a function name in standard Python syntax.
"""

import ast
import re
from uuid import UUID

from app.exceptions import BadRequestException, ValidationException


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class FormulaValidationError(ValidationException):
    pass


class CircularDependencyError(BadRequestException):
    pass


class EvaluationError(BadRequestException):
    pass


# ---------------------------------------------------------------------------
# AST whitelist validator
# ---------------------------------------------------------------------------

_SAFE_NODES = (
    ast.Module,
    ast.Expr,
    ast.Expression,
    ast.Constant,        # numeric literals
    ast.BinOp,           # binary operations
    ast.UnaryOp,         # unary operations (e.g., -x)
    ast.Call,            # function calls
    ast.Name,            # variable / function references
    ast.Load,
    # Operators
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.Mod,
    ast.FloorDiv,
    ast.USub,
    ast.UAdd,
    # Comparison (used inside if() condition)
    ast.Compare,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    # Boolean ops (used inside if() condition)
    ast.BoolOp,
    ast.And,
    ast.Or,
    ast.UnaryOp,
    ast.Not,
)

_IF_PLACEHOLDER = "_if_"
_IF_PATTERN = re.compile(r"\bif\s*\(")


def _preprocess(expression: str) -> str:
    """Replace `if(` with `_if_(` to allow AST parsing."""
    return _IF_PATTERN.sub(f"{_IF_PLACEHOLDER}(", expression)


class _SafeASTVisitor(ast.NodeVisitor):
    """Walks the AST and raises FormulaValidationError on any disallowed node."""

    def generic_visit(self, node: ast.AST) -> None:
        if not isinstance(node, _SAFE_NODES):
            raise FormulaValidationError(
                f"Disallowed expression construct: {type(node).__name__}"
            )
        super().generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # Only allow plain Name calls (not attribute access like os.system)
        if not isinstance(node.func, ast.Name):
            raise FormulaValidationError(
                "Only simple function calls are allowed (no attribute access)"
            )
        allowed_funcs = {"abs", "round", "min", "max", _IF_PLACEHOLDER}
        if node.func.id not in allowed_funcs:
            raise FormulaValidationError(
                f"Function '{node.func.id}' is not allowed. "
                f"Allowed functions: abs, round, min, max, if"
            )
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        # Names must be uppercase KPI codes, allowed function names, or the if placeholder
        allowed_funcs = {"abs", "round", "min", "max", _IF_PLACEHOLDER}
        if node.id in allowed_funcs:
            return
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", node.id):
            raise FormulaValidationError(
                f"Invalid identifier '{node.id}'. KPI codes must be uppercase letters, "
                "digits, and underscores (e.g., SALES_REVENUE)."
            )


# ---------------------------------------------------------------------------
# KPI code extraction regex
# ---------------------------------------------------------------------------

# Matches uppercase identifiers that are NOT known function names
_FUNC_NAMES = {"abs", "round", "min", "max", "if"}
_CODE_PATTERN = re.compile(r"\b([A-Z][A-Z0-9_]*)\b")


# ---------------------------------------------------------------------------
# FormulaParser
# ---------------------------------------------------------------------------

class FormulaParser:
    """Tokenises and validates a formula expression without evaluating it."""

    def extract_kpi_references(self, expression: str) -> list[str]:
        """Return list of unique KPI code strings found in the expression."""
        preprocessed = _preprocess(expression)
        matches = _CODE_PATTERN.findall(preprocessed)
        # Filter out the if-placeholder and any known function names (uppercased)
        excluded = {_IF_PLACEHOLDER.upper(), "IF"}
        return list(dict.fromkeys(code for code in matches if code not in excluded))

    def validate_syntax(self, expression: str) -> bool:
        """
        Return True if syntax is valid.
        Raise FormulaValidationError with detail if not.
        """
        preprocessed = _preprocess(expression)
        try:
            tree = ast.parse(preprocessed, mode="eval")
        except SyntaxError as exc:
            raise FormulaValidationError(f"Formula syntax error: {exc.msg}") from exc

        visitor = _SafeASTVisitor()
        try:
            visitor.visit(tree)
        except FormulaValidationError:
            raise
        return True


# ---------------------------------------------------------------------------
# FormulaDependencyResolver
# ---------------------------------------------------------------------------

class FormulaDependencyResolver:
    """Detects circular dependencies in formula chains."""

    def build_dependency_graph(self, kpi_id: UUID, all_kpis: list) -> dict[UUID, list[UUID]]:
        """
        Build an adjacency dict {kpi_id: [dependency_kpi_ids]} for all formula KPIs.

        Args:
            kpi_id: The root KPI whose graph we are building.
            all_kpis: All KPI objects available in the same organisation.
        """
        graph: dict[UUID, list[UUID]] = {}
        kpi_by_id = {k.id: k for k in all_kpis}

        def _add(kid: UUID) -> None:
            if kid in graph:
                return
            kpi = kpi_by_id.get(kid)
            if kpi is None:
                return
            deps = [dep.id for dep in (kpi.formula_dependencies or [])]
            graph[kid] = deps
            for dep_id in deps:
                _add(dep_id)

        _add(kpi_id)
        return graph

    def detect_cycle(self, graph: dict[UUID, list[UUID]], start: UUID) -> bool:
        """
        DFS cycle detection.
        Raises CircularDependencyError if a cycle is found; returns False otherwise.
        """
        visited: set[UUID] = set()
        rec_stack: set[UUID] = set()

        def _dfs(node: UUID) -> bool:
            visited.add(node)
            rec_stack.add(node)
            for neighbour in graph.get(node, []):
                if neighbour not in visited:
                    if _dfs(neighbour):
                        return True
                elif neighbour in rec_stack:
                    return True
            rec_stack.discard(node)
            return False

        if _dfs(start):
            raise CircularDependencyError(
                "Circular dependency detected in formula chain. "
                "A KPI cannot directly or indirectly depend on itself."
            )
        return False


# ---------------------------------------------------------------------------
# FormulaEvaluator
# ---------------------------------------------------------------------------

def _ternary_if(condition: object, true_val: float, false_val: float) -> float:
    """Safe implementation of the if(condition, true_val, false_val) formula function."""
    return true_val if condition else false_val


class FormulaEvaluator:
    """Safely evaluates a formula expression given resolved KPI values."""

    SAFE_NAMES: dict[str, object] = {
        "abs": abs,
        "round": round,
        "min": min,
        "max": max,
        _IF_PLACEHOLDER: _ternary_if,
    }

    def evaluate(self, expression: str, kpi_values: dict[str, float]) -> float:
        """
        Replace KPI codes with their numeric values and evaluate the expression safely.

        Args:
            expression: The formula string (may contain `if(...)` calls).
            kpi_values: Mapping of KPI code → resolved numeric value.

        Returns:
            The computed float result.

        Raises:
            EvaluationError: On division by zero, missing KPI values, or other runtime errors.
        """
        preprocessed = _preprocess(expression)

        # Validate syntax + node whitelist before evaluation
        parser = FormulaParser()
        parser.validate_syntax(expression)

        # Build the evaluation namespace: safe builtins + KPI values
        namespace: dict[str, object] = {**self.SAFE_NAMES}
        for code, value in kpi_values.items():
            namespace[code] = float(value)

        # Check all referenced KPI codes have values
        required = parser.extract_kpi_references(expression)
        missing = [code for code in required if code not in kpi_values]
        if missing:
            raise EvaluationError(
                f"Missing values for KPI references: {', '.join(missing)}"
            )

        try:
            result = eval(  # noqa: S307 — safe: AST-validated expression, no builtins
                compile(preprocessed, "<formula>", "eval"),
                {"__builtins__": {}},
                namespace,
            )
        except ZeroDivisionError as exc:
            raise EvaluationError("Formula evaluation error: division by zero") from exc
        except Exception as exc:
            raise EvaluationError(f"Formula evaluation error: {exc}") from exc

        if not isinstance(result, (int, float)):
            raise EvaluationError(
                f"Formula must evaluate to a numeric value, got {type(result).__name__}"
            )
        return float(result)


# ---------------------------------------------------------------------------
# Period-aware formula evaluation (convenience wrapper used by actuals service)
# ---------------------------------------------------------------------------


def evaluate_formula_for_period(
    formula_expression: str,
    kpi_values: dict[str, float],
) -> float:
    """
    Evaluate a formula expression with pre-resolved KPI values for a given period.

    This is a thin wrapper around FormulaEvaluator.evaluate() for use by the
    actuals service when computing AUTO_FORMULA actuals during scheduled runs.

    Args:
        formula_expression: The formula string (e.g. "(REVENUE - COST) / REVENUE * 100").
        kpi_values: Mapping of KPI code → actual numeric value for the period
                    (already fetched by the caller from the actuals table).

    Returns:
        float: The computed result.

    Raises:
        EvaluationError: On division by zero, missing values, or unsafe expressions.
    """
    evaluator = FormulaEvaluator()
    return evaluator.evaluate(formula_expression, kpi_values)
