"""
kpis/formula.py — Safe formula parser and evaluator.

Security model:
  Uses Python ast.parse() in 'eval' mode, then walks the AST with a whitelist visitor.
  Only these node types are allowed:
    Numbers, variable names (uppercase), arithmetic operators (+,-,*,/,**,%)
    Function calls: abs(), round(), min(), max(), if_func()
    Comparisons: <, <=, >, >=, ==, !=
  Anything else (imports, attribute access, subscripts, etc.) raises FormulaValidationError.
  eval() is NEVER called.

Formula syntax:
  Variables:  Uppercase identifiers — REVENUE, EXPENSES, HEADCOUNT
  Arithmetic: Standard Python operators
  Functions:  ABS(x), ROUND(x, n), MIN(a,b), MAX(a,b), IF(condition, true_val, false_val)
  Constants:  Numeric literals only (100, 0.5, etc.)

Examples:
  (REVENUE - EXPENSES) / REVENUE * 100
  IF(DEFECTS > 0, DEFECTS / OUTPUT * 100, 0)
  ABS(CURRENT_PERIOD - PRIOR_PERIOD) / PRIOR_PERIOD * 100
  MIN(ACTUAL, TARGET) / TARGET * 100

Enhancement 2: FormulaParser.extract_variable_names() returns the list of variable
names that must be resolved via DataSyncService before evaluation.
"""

import ast
import operator
import re
from decimal import Decimal, InvalidOperation
from uuid import UUID

from app.exceptions import BadRequestException, ValidationException


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class FormulaValidationError(ValidationException):
    """Raised when a formula expression fails syntax or semantic validation."""

    def __init__(self, detail: str, position: int | None = None) -> None:
        self.position = position
        super().__init__(detail)


class CircularDependencyError(BadRequestException):
    """Raised when a cycle is detected in the formula dependency graph."""

    def __init__(self, detail: str, cycle_path: list[str] | None = None) -> None:
        self.cycle_path = cycle_path or []
        super().__init__(detail)


class MissingVariableError(BadRequestException):
    """Raised when a required formula variable has no value for the period."""

    def __init__(self, variable_name: str) -> None:
        self.variable_name = variable_name
        super().__init__(f"Required variable '{variable_name}' has no value for this period")


class EvaluationError(BadRequestException):
    """Raised when formula evaluation fails at runtime."""
    pass


# ---------------------------------------------------------------------------
# AST whitelist validator (FormulaASTValidator)
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

_IF_PLACEHOLDER = "if_func"
_FUNC_NAMES_UPPER = {"ABS", "ROUND", "MIN", "MAX", "IF"}
_VAR_PATTERN = re.compile(r"\b([A-Z][A-Z0-9_]*)\b")


def _normalise(expression: str) -> str:
    """
    Normalise function names for AST parsing.
    Replaces IF(, ABS(, ROUND(, MIN(, MAX( with lowercase/prefixed equivalents.
    """
    expr = re.sub(r"\bIF\s*\(", "if_func(", expression, flags=re.IGNORECASE)
    expr = re.sub(r"\bABS\s*\(",  "abs(",     expr,       flags=re.IGNORECASE)
    expr = re.sub(r"\bROUND\s*\(","round(",   expr,       flags=re.IGNORECASE)
    expr = re.sub(r"\bMIN\s*\(",  "min(",     expr,       flags=re.IGNORECASE)
    expr = re.sub(r"\bMAX\s*\(",  "max(",     expr,       flags=re.IGNORECASE)
    return expr


# Legacy alias for code that still uses _preprocess / _if_ placeholder
def _preprocess(expression: str) -> str:
    """Legacy: replace `if(` with `if_func(` to allow AST parsing."""
    return _normalise(expression)


class FormulaASTValidator(ast.NodeVisitor):
    """
    Walks the AST and collects validation errors for non-whitelisted constructs.
    Equivalent to the old _SafeASTVisitor but accumulates errors instead of raising.
    """

    SAFE_FUNCTIONS = {"abs", "round", "min", "max", _IF_PLACEHOLDER}

    def __init__(self) -> None:
        self.errors: list[str] = []

    def generic_visit(self, node: ast.AST) -> None:
        if not isinstance(node, _SAFE_NODES):
            self.errors.append(f"Disallowed syntax: {type(node).__name__}")
        else:
            super().generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if not isinstance(node.func, ast.Name):
            self.errors.append("Complex function calls are not allowed (e.g. os.system())")
        elif node.func.id not in self.SAFE_FUNCTIONS:
            self.errors.append(
                f"Function '{node.func.id}' is not allowed. "
                f"Allowed functions: abs, round, min, max, if"
            )
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        allowed_funcs = self.SAFE_FUNCTIONS
        if node.id in allowed_funcs:
            return
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", node.id):
            self.errors.append(
                f"Invalid identifier '{node.id}'. Variable names must be uppercase "
                "letters, digits, and underscores (e.g. SALES_REVENUE)."
            )


# Keep legacy class name as alias
_SafeASTVisitor = FormulaASTValidator


# ---------------------------------------------------------------------------
# FormulaParser
# ---------------------------------------------------------------------------

class FormulaParser:
    """Parses and validates formula expressions without evaluating them."""

    SAFE_FUNCTION_NAMES = _FUNC_NAMES_UPPER

    def extract_variable_names(self, expression: str) -> list[str]:
        """
        Return all uppercase identifiers in the expression that are NOT function names.
        These are the variable names that must be resolved before evaluation.

        >>> FormulaParser().extract_variable_names("(REVENUE - EXPENSES) / REVENUE * 100")
        ['REVENUE', 'EXPENSES']
        """
        matches = _VAR_PATTERN.findall(expression)
        return list(dict.fromkeys(
            name for name in matches
            if name not in self.SAFE_FUNCTION_NAMES
        ))

    def extract_kpi_references(self, expression: str) -> list[str]:
        """Legacy alias for extract_variable_names()."""
        return self.extract_variable_names(expression)

    def validate_syntax(self, expression: str) -> list[str]:
        """
        Validate formula syntax using AST.
        Returns list of error messages. Empty list = valid.
        (Changed from raising FormulaValidationError to returning error list.)
        """
        if not expression or not expression.strip():
            return ["Formula expression cannot be empty"]

        normalised = _normalise(expression)
        try:
            tree = ast.parse(normalised, mode="eval")
        except SyntaxError as exc:
            return [f"Syntax error: {exc.msg} at position {exc.offset}"]

        validator = FormulaASTValidator()
        validator.visit(tree)
        return validator.errors

    def validate_variables_exist(
        self,
        expression: str,
        available_variable_names: list[str],
    ) -> list[str]:
        """
        Check that all variable names in the expression are defined for this KPI.
        Returns list of error messages. Empty = all variables accounted for.
        """
        referenced = self.extract_variable_names(expression)
        available_set = set(available_variable_names)
        return [
            f"Variable '{name}' is referenced in the formula but not defined. "
            "Please add it as a KPI variable."
            for name in referenced
            if name not in available_set
        ]


# ---------------------------------------------------------------------------
# FormulaDependencyResolver  (legacy — used by app/kpis/service.py)
# ---------------------------------------------------------------------------

class FormulaDependencyResolver:
    """
    Detects circular dependencies in formula chains (legacy resolver).
    Uses KPI.formula_dependencies relationships.
    """

    def build_dependency_graph(self, kpi_id: UUID, all_kpis: list) -> dict[UUID, list[UUID]]:
        """
        Build an adjacency dict {kpi_id: [dependency_kpi_ids]} for all formula KPIs.
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
# DependencyResolver  (new — used by DataSyncService via KPIVariable.source_type)
# ---------------------------------------------------------------------------

class DependencyResolver:
    """
    Detects circular dependencies via KPIVariable.source_type == KPI_ACTUAL links.
    """

    def build_dependency_graph(
        self, kpi_id: UUID, all_kpis: list, all_variables: list
    ) -> dict[UUID, list[UUID]]:
        """Build adjacency list from KPIVariable → KPI_ACTUAL source_type links."""
        from app.integrations.enums import VariableSourceType

        graph: dict[UUID, list[UUID]] = {}
        kpi_code_to_id = {k.code: k.id for k in all_kpis}

        for var in all_variables:
            if var.source_type == VariableSourceType.KPI_ACTUAL:
                dep_code = (var.source_config or {}).get("kpi_code")
                dep_id = kpi_code_to_id.get(dep_code)
                if dep_id:
                    graph.setdefault(var.kpi_id, []).append(dep_id)

        return graph

    def detect_cycle(self, graph: dict[UUID, list[UUID]], start: UUID) -> list[str] | None:
        """
        DFS cycle detection.
        Returns the cycle path as list of stringified node IDs if a cycle is found, else None.
        """
        visited: set[UUID] = set()
        path: list[UUID] = []

        def dfs(node: UUID) -> bool:
            if node in path:
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


# ---------------------------------------------------------------------------
# _safe_eval_ast  (no eval() — pure recursive AST walker)
# ---------------------------------------------------------------------------

_BINOP_MAP = {
    ast.Add:  operator.add,
    ast.Sub:  operator.sub,
    ast.Mult: operator.mul,
    ast.Div:  operator.truediv,
    ast.Pow:  operator.pow,
    ast.Mod:  operator.mod,
}
_CMPOP_MAP = {
    ast.Lt:    operator.lt,
    ast.LtE:   operator.le,
    ast.Gt:    operator.gt,
    ast.GtE:   operator.ge,
    ast.Eq:    operator.eq,
    ast.NotEq: operator.ne,
}


def _safe_eval_ast(node: ast.AST, namespace: dict) -> float:
    """
    Recursively evaluate a whitelisted AST node.
    Only processes node types in _SAFE_NODES — anything else raises EvaluationError.
    No use of eval() or exec().
    """
    if isinstance(node, ast.Constant):
        # Preserve int literals as int (so e.g. ROUND(x, 0) works — round() needs int ndigits)
        if isinstance(node.value, (int, float)):
            return node.value
        return float(node.value)

    if isinstance(node, ast.Name):
        if node.id not in namespace:
            raise MissingVariableError(node.id)
        val = namespace[node.id]
        if callable(val):
            return val  # type: ignore[return-value]  # function reference
        return float(val)

    if isinstance(node, ast.BinOp):
        op = _BINOP_MAP.get(type(node.op))
        if op is None:
            raise EvaluationError(f"Unsupported operator: {type(node.op).__name__}")
        left = _safe_eval_ast(node.left, namespace)
        right = _safe_eval_ast(node.right, namespace)
        return op(left, right)  # type: ignore[operator]

    if isinstance(node, ast.UnaryOp):
        operand = _safe_eval_ast(node.operand, namespace)
        if isinstance(node.op, ast.USub):
            return -operand  # type: ignore[operator]
        return operand  # type: ignore[return-value]

    if isinstance(node, ast.Call):
        func_name = node.func.id if isinstance(node.func, ast.Name) else None
        if func_name not in namespace:
            raise EvaluationError(f"Function not found: {func_name}")
        func = namespace[func_name]
        args = [_safe_eval_ast(arg, namespace) for arg in node.args]
        return func(*args)

    if isinstance(node, ast.Compare):
        left = _safe_eval_ast(node.left, namespace)
        for op_node, comparator in zip(node.ops, node.comparators):
            op = _CMPOP_MAP.get(type(op_node))
            if op is None:
                raise EvaluationError(f"Unsupported comparator: {type(op_node).__name__}")
            right = _safe_eval_ast(comparator, namespace)
            if not op(left, right):
                return False  # type: ignore[return-value]
            left = right
        return True  # type: ignore[return-value]

    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            return all(_safe_eval_ast(v, namespace) for v in node.values)  # type: ignore[return-value]
        # Or
        return any(_safe_eval_ast(v, namespace) for v in node.values)  # type: ignore[return-value]

    raise EvaluationError(f"Unsupported AST node type: {type(node).__name__}")


# ---------------------------------------------------------------------------
# FormulaEvaluator
# ---------------------------------------------------------------------------

def _if_func(condition: object, true_val: float, false_val: float) -> float:
    """Safe implementation of if(condition, true_val, false_val)."""
    return true_val if condition else false_val


class FormulaEvaluator:
    """
    Safely evaluates a formula expression given resolved variable values.

    Supports both legacy float dicts (kpi_values) and new Decimal dicts (variables).
    Returns Decimal for precision; callers using float() on the result are unaffected.

    Usage:
        result = FormulaEvaluator().evaluate(
            "(REVENUE - EXPENSES) / REVENUE * 100",
            {"REVENUE": Decimal("1200000"), "EXPENSES": Decimal("850000")},
        )
    """

    SAFE_NAMES: dict[str, object] = {
        "abs":     abs,
        "round":   round,
        "min":     min,
        "max":     max,
        "if_func": _if_func,
    }

    def evaluate(
        self,
        expression: str,
        variables: dict[str, float | Decimal],
        decimal_places: int = 4,
        zero_on_division: bool = True,
    ) -> Decimal:
        """
        Evaluate the formula expression with the given variable values.

        Args:
            expression:       Formula string (e.g. "(REVENUE - EXPENSES) / REVENUE * 100").
            variables:        Dict mapping variable/KPI-code names → numeric values.
                              Accepts float or Decimal; values are coerced to float internally.
            decimal_places:   Rounding precision for the result (default 4).
            zero_on_division: Return 0 on ZeroDivisionError (default True).

        Returns:
            Decimal: The computed result, rounded to ``decimal_places``.

        Raises:
            MissingVariableError: If a required variable is absent from ``variables``.
            EvaluationError: For any other runtime evaluation failure.
            FormulaValidationError: For syntax errors in ``expression``.
        """
        syntax_errors = FormulaParser().validate_syntax(expression)
        if syntax_errors:
            raise FormulaValidationError("; ".join(syntax_errors))

        normalised = _normalise(expression)

        # Build evaluation namespace: safe functions + variable values
        namespace: dict[str, object] = {**self.SAFE_NAMES}
        for name, value in variables.items():
            namespace[name] = float(value)

        # Validate all referenced names have values
        referenced = FormulaParser().extract_variable_names(expression)
        for name in referenced:
            if name not in namespace:
                raise MissingVariableError(name)

        try:
            tree = ast.parse(normalised, mode="eval")
            raw = _safe_eval_ast(tree.body, namespace)
            result = Decimal(str(raw)).quantize(Decimal(10) ** -decimal_places)
            return result
        except (MissingVariableError, FormulaValidationError, EvaluationError):
            raise
        except ZeroDivisionError:
            if zero_on_division:
                return Decimal("0")
            raise EvaluationError("Formula evaluation error: division by zero")
        except (InvalidOperation, ValueError) as exc:
            raise EvaluationError(f"Formula produced a non-numeric result: {exc}") from exc
        except Exception as exc:
            raise EvaluationError(f"Formula evaluation error: {exc}") from exc


# ---------------------------------------------------------------------------
# Period-aware formula evaluation  (convenience wrapper — backward compat)
# ---------------------------------------------------------------------------

def evaluate_formula_for_period(
    formula_expression: str,
    kpi_values: dict[str, float | Decimal],
) -> float:
    """
    Evaluate a formula expression with pre-resolved variable values.

    Thin wrapper around FormulaEvaluator.evaluate() for use by the actuals
    service when computing AUTO_FORMULA actuals during scheduled runs.

    Args:
        formula_expression: The formula string (e.g. "(REVENUE - COST) / REVENUE * 100").
        kpi_values:         Mapping of variable/KPI-code name → numeric value.

    Returns:
        float: The computed result.

    Raises:
        EvaluationError: On division by zero, missing values, or unsafe expressions.
    """
    return float(FormulaEvaluator().evaluate(formula_expression, kpi_values))
