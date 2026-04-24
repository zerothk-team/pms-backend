# 03 — Formula Engine

← [Back to Index](index.md)

---

## Overview

The formula engine is a **safe, sandboxed expression evaluator** that allows computed KPIs to derive their values from other KPI codes at runtime. It is implemented in `app/kpis/formula.py` and consists of three cooperating classes:

| Class | Responsibility |
|-------|----------------|
| `FormulaParser` | Validates syntax, extracts referenced KPI codes |
| `FormulaDependencyResolver` | Detects circular dependencies with DFS |
| `FormulaEvaluator` | Safely evaluates formulas against a values map |

**Security guarantee**: The engine never calls `exec`, never imports modules, and rejects any construct that is not a numeric expression. It uses Python's `ast` module to parse and whitelist every node in the expression before any evaluation occurs.

---

## Supported Syntax

### Operands

| Type | Example | Notes |
|------|---------|-------|
| Integer literals | `42` | |
| Float literals | `3.14`, `0.001` | |
| KPI code references | `REVENUE`, `SALES_COST` | Must be `UPPER_SNAKE_CASE` |

### Operators

| Symbol | Operation | Example |
|--------|-----------|---------|
| `+` | Addition | `REVENUE + BONUS` |
| `-` | Subtraction | `REVENUE - COST` |
| `*` | Multiplication | `UNITS * PRICE` |
| `/` | Division | `PROFIT / REVENUE * 100` |
| `**` | Exponentiation | `BASE_VALUE ** 2` |
| `-` (unary) | Negation | `-COST_DELTA` |
| `+` (unary) | Identity | `+VALUE` |

### Built-in Functions

| Function | Signature | Purpose |
|----------|-----------|---------|
| `abs(x)` | Absolute value | `abs(PROFIT_DELTA)` |
| `round(x, n)` | Round to n decimals | `round(RATE * 100, 2)` |
| `min(a, b, ...)` | Minimum | `min(QUOTA, ACTUAL)` |
| `max(a, b, ...)` | Maximum | `max(0, GROWTH)` |
| `if(cond, t, f)` | Conditional | `if(REVENUE > 0, PROFIT / REVENUE, 0)` |

> **Important**: `if()` uses **function call syntax**, not Python's `if...else` keyword. This is by design — the engine preprocesses `if(...)` into an internal `_if_(...)` call, since `if` is not a valid Python expression on its own.

### Comparison Operators (inside `if()`)

| Symbol | Meaning |
|--------|---------|
| `==` | Equal |
| `!=` | Not equal |
| `<` | Less than |
| `<=` | Less than or equal |
| `>` | Greater than |
| `>=` | Greater than or equal |

---

## AST Whitelist

Before evaluation, `FormulaParser.validate()` walks every node in the parsed AST and rejects anything not in the whitelist. This prevents any code injection or unexpected behaviour.

### Allowed AST Node Types

```python
_SAFE_NODES = {
    ast.Expression,   # top-level expression wrapper
    ast.BinOp,        # a + b, a * b, etc.
    ast.UnaryOp,      # -x, +x
    ast.BoolOp,       # and / or (inside if comparisons)
    ast.Compare,      # a < b, a == b
    ast.Call,         # func(args)
    ast.IfExp,        # internal x if cond else y (from preprocessed if())
    ast.Constant,     # numeric literals
    ast.Name,         # symbol references (KPI codes, _if_ function)
    ast.Add,          # +
    ast.Sub,          # -
    ast.Mult,         # *
    ast.Div,          # /
    ast.Pow,          # **
    ast.USub,         # unary -
    ast.UAdd,         # unary +
    ast.Eq, ast.NotEq,
    ast.Lt, ast.LtE,
    ast.Gt, ast.GtE,
    ast.And, ast.Or,
}
```

If any other node type is encountered (e.g. `ast.Import`, `ast.Attribute`, `ast.Subscript`, `ast.Lambda`, string literals), `FormulaValidationError` is raised immediately.

---

## `if()` Preprocessing

### The Problem

Python's `ast.parse()` in expression mode cannot parse `if(...)` as a function call without ambiguity. The formula engine uses the following transform:

**Step 1**: Replace `if(` with `_if_(` in the raw formula string.

```python
# Input formula:
"if(REVENUE > 0, PROFIT / REVENUE * 100, 0)"

# After preprocessing:
"_if_(REVENUE > 0, PROFIT / REVENUE * 100, 0)"
```

**Step 2**: `ast.parse("_if_(...)", mode="eval")` succeeds — it is now a valid Python call expression.

**Step 3**: During validation, `ast.Name(id="_if_")` is in the allowed names, so it passes the whitelist check.

**Step 4**: During evaluation, `_if_` is resolved from the safe builtins injected into the eval context:

```python
def _if_(condition, true_val, false_val):
    return true_val if condition else false_val

_SAFE_BUILTINS = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "_if_": _if_,
}
```

**Step 5**: The formula is evaluated with `eval(expr, {"__builtins__": {}}, context)`, where `context` contains the safe builtins plus the KPI code values.

---

## Circular Dependency Detection

### The Problem

A formula KPI can reference other formula KPIs, which may in turn reference others. If a cycle exists — e.g. `A` depends on `B` which depends on `A` — it would cause infinite recursion during evaluation.

### DFS Algorithm

`FormulaDependencyResolver` builds an adjacency map of **all existing formula KPIs** in the organisation, then performs a Depth-First Search to detect cycles.

```
adjacency = {
    "KPI_A": {"KPI_B"},     # A's formula references B
    "KPI_B": {"KPI_C"},     # B's formula references C
    "KPI_C": {},             # C is manual, no dependencies
}
```

When a new KPI is being created that will depend on `KPI_B`:

1. Add the *proposed* KPI to the adjacency map with its dependencies
2. Run DFS from the proposed KPI's code
3. If DFS revisits any node already in the current path → **cycle detected** → raise `CircularDependencyError`

### Implementation Detail: `_FakeKPI`

To detect cycles **before writing to the database**, the service creates a lightweight fake object representing the KPI being created:

```python
class _FakeKPI:
    def __init__(self, code: str, deps: list[str]):
        self.code = code
        self.formula_dependencies = [
            type("_Dep", (), {"code": d})() for d in deps
        ]
```

This allows `FormulaDependencyResolver.check_no_cycle()` to work identically for both existing DB records and not-yet-persisted ones.

### Example: Cycle Detected

Existing KPIs:
```
PROFIT = REVENUE - COST           # depends on REVENUE, COST
MARGIN = PROFIT / REVENUE * 100   # depends on PROFIT, REVENUE
```

Attempting to create `REVENUE = MARGIN * FACTOR`:
```
Adjacency graph:
  REVENUE → MARGIN
  MARGIN  → PROFIT, REVENUE
  PROFIT  → REVENUE, COST

DFS from REVENUE:
  Visit REVENUE  (path: [REVENUE])
  → Visit MARGIN (path: [REVENUE, MARGIN])
    → Visit PROFIT (path: [REVENUE, MARGIN, PROFIT])
      → Visit REVENUE  ← already in path!  ✗ CYCLE DETECTED
```

**Response** (`422 Unprocessable Entity`):
```json
{
  "detail": "Circular dependency detected: REVENUE → MARGIN → PROFIT → REVENUE"
}
```

---

## Formula Validation Flow

```
Client submits formula
        │
        ▼
FormulaParser.preprocess()
  "if(" → "_if_("
        │
        ▼
ast.parse(formula, mode="eval")
        │
  ┌─────┴─────┐
  │ SyntaxError│
  │  detected  │
  └─────┬──────┘
        │ (on error)
 FormulaValidationError("Invalid syntax: ...")
        │ (on success)
        ▼
FormulaParser._walk_ast(node)
  Check each AST node type
        │
  ┌─────┴──────────────┐
  │ Node not in         │
  │ _SAFE_NODES         │
  └──────┬──────────────┘
         │ (on error)
  FormulaValidationError("Unsafe node: ...")
         │ (on success)
         ▼
FormulaParser.extract_kpi_codes()
  Find all ast.Name nodes not in _SAFE_BUILTINS
  Return list of referenced KPI codes
         │
         ▼
KPIService._validate_and_resolve_formula()
  Load all formula KPIs in org from DB
  Build adjacency map
  Add proposed (fake) KPI
  Run DFS cycle check
         │
  ┌──────┴────────────────┐
  │ Cycle detected         │
  │ Or missing KPI code    │
  └──────┬────────────────┘
         │ (on error)
  CircularDependencyError / 404 for missing code
         │ (on success)
         ▼
  Write kpi_formula_dependency rows
```

---

## FormulaEvaluator

While formula *validation* is handled at KPI creation time, formula *evaluation* (computing a numeric result from concrete values) is done by `FormulaEvaluator` — used by downstream modules (actuals, scoring) to compute derived values.

### Usage

```python
from app.kpis.formula import FormulaEvaluator

evaluator = FormulaEvaluator()
result = evaluator.evaluate(
    formula="(REVENUE - COST) / REVENUE * 100",
    values={
        "REVENUE": 500000.0,
        "COST": 300000.0,
    }
)
# result → 40.0
```

### Error Handling

| Exception | When Raised |
|-----------|------------|
| `FormulaValidationError` | Formula fails AST whitelist |
| `EvaluationError` | Runtime error during eval (e.g. division by zero) |

```python
# Division by zero
evaluator.evaluate("PROFIT / REVENUE", {"PROFIT": 100, "REVENUE": 0})
# → EvaluationError("Evaluation failed: division by zero")
```

---

## Error Reference

All formula errors are raised as Python exceptions in `app/kpis/formula.py` and translated to HTTP responses by the service layer.

| Exception Class | Module Path | HTTP Status | When |
|----------------|------------|-------------|------|
| `FormulaValidationError` | `app.kpis.formula` | `422` | Syntax error or unsafe AST node |
| `CircularDependencyError` | `app.kpis.formula` | `422` | Cycle in dependency graph |
| `EvaluationError` | `app.kpis.formula` | `422` | Runtime evaluation failure |

---

## Formula Examples

### Simple Arithmetic

```
REVENUE - COST
```
Returns: `REVENUE` minus `COST`. Both must be manual KPIs in the same organisation.

---

### Percentage Calculation

```
(REVENUE - COST) / REVENUE * 100
```

**Step-by-step** with `REVENUE=500000`, `COST=300000`:
```
1. REVENUE - COST         = 500000 - 300000 = 200000
2. 200000 / REVENUE       = 200000 / 500000 = 0.4
3. 0.4 * 100              = 40.0
```

**Result**: `40.0` (i.e. 40% gross profit margin)

---

### Conditional Formula

```
if(REVENUE > 0, (REVENUE - COST) / REVENUE * 100, 0)
```

Returns the margin percentage, or `0` if `REVENUE` is zero (prevents division by zero at runtime).

**Step-by-step**:
```
1. Preprocess: _if_(REVENUE > 0, (REVENUE - COST) / REVENUE * 100, 0)
2. Evaluate condition: 500000 > 0 → True
3. Return true branch: (500000 - 300000) / 500000 * 100 = 40.0
```

---

### Nested Functions

```
round(max(0, REVENUE - COST) / REVENUE * 100, 2)
```

Clamps the numerator to ≥0, computes percentage, rounds to 2 decimal places.

---

### Chained Dependencies

Given:
- `REVENUE` = manual
- `COST` = manual
- `GROSS_PROFIT = REVENUE - COST`
- `GROSS_MARGIN = GROSS_PROFIT / REVENUE * 100`

Dependency chain:
```
GROSS_MARGIN
    └── GROSS_PROFIT
            ├── REVENUE
            └── COST
```

All three referenced KPIs (`GROSS_PROFIT`, `REVENUE`, `COST`) will be recorded in `kpi_formula_dependency` for `GROSS_MARGIN`.

> **Note**: `kpi_formula_dependency` stores *direct* dependencies only (the codes literally appearing in the formula expression). The evaluator resolves the full chain recursively at compute time.

---

← [Back to Index](index.md) | Previous: [02 — Data Models](02-data-models.md) | Next: [04 — API Reference →](04-api-reference.md)
