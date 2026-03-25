"""Expand contract ``derived_kpis`` YAML into pandas-evaluable formulas (base columns only)."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

# Names that can appear in pandas eval expressions but are not column identifiers.
_PANDAS_EVAL_RESERVED = frozenset(
    {
        "and",
        "or",
        "not",
        "True",
        "False",
        "inf",
        "nan",
        "e",
    }
)


def _expand_numerator(
    token: str,
    by_name: Dict[str, Dict[str, Any]],
    visiting: Set[str],
    base_metric_names: Set[str],
) -> str:
    """Expand a token that may be another KPI name or a base metric/column name."""
    if token in by_name and token not in base_metric_names:
        if token in visiting:
            raise ValueError(f"derived_kpis: circular reference involving '{token}'")
        visiting.add(token)
        try:
            return f"({kpi_to_formula(by_name[token], by_name, base_metric_names, visiting)})"
        finally:
            visiting.discard(token)
    return token


def kpi_to_formula(
    kpi: Dict[str, Any],
    by_name: Dict[str, Dict[str, Any]],
    base_metric_names: Set[str],
    visiting: Optional[Set[str]] = None,
) -> str:
    """Build a single expression using only physical column names (additive metrics)."""
    visiting = visiting if visiting is not None else set()
    name = kpi.get("name")
    if not name:
        raise ValueError("derived_kpi entry missing 'name'")

    if "subtract" in kpi:
        num = _expand_numerator(str(kpi["numerator"]), by_name, visiting, base_metric_names)
        sub = _expand_numerator(str(kpi["subtract"]), by_name, visiting, base_metric_names)
        return f"({num} - {sub})"

    if "add" in kpi:
        num = _expand_numerator(str(kpi["numerator"]), by_name, visiting, base_metric_names)
        add_tok = _expand_numerator(str(kpi["add"]), by_name, visiting, base_metric_names)
        return f"({num} + {add_tok})"

    if "denominator" in kpi:
        num = _expand_numerator(str(kpi["numerator"]), by_name, visiting, base_metric_names)
        den = _expand_numerator(str(kpi["denominator"]), by_name, visiting, base_metric_names)
        mult = kpi.get("multiply", 1)
        try:
            mult_f = float(mult)
        except (TypeError, ValueError):
            mult_f = 1.0
        if mult_f == 1.0:
            return f"(({num}) / ({den}))"
        return f"({mult_f} * ({num}) / ({den}))"

    if "divide_by" in kpi:
        num = _expand_numerator(str(kpi["numerator"]), by_name, visiting, base_metric_names)
        div = kpi["divide_by"]
        return f"(({num}) / ({div}))"

    if "multiply_by" in kpi:
        num = _expand_numerator(str(kpi["numerator"]), by_name, visiting, base_metric_names)
        mul = _expand_numerator(str(kpi["multiply_by"]), by_name, visiting, base_metric_names)
        scale = kpi.get("multiply", 1)
        try:
            scale_f = float(scale)
        except (TypeError, ValueError):
            scale_f = 1.0
        if scale_f == 1.0:
            return f"(({num}) * ({mul}))"
        return f"({scale_f} * ({num}) * ({mul}))"

    raise ValueError(f"derived_kpi '{name}': unsupported shape (need subtract/add/denominator/divide_by/multiply_by)")


def kpi_to_aggregate_ratio_parts(
    kpi: Dict[str, Any],
    by_name: Dict[str, Dict[str, Any]],
    base_metric_names: Set[str],
) -> Optional[Tuple[str, str, float]]:
    """When a KPI is a ratio, return (numerator_expr, denominator_expr, multiply) for aggregate-then-divide.

    Expressions use only physical (additive) column names and numeric literals. They are intended
    to be evaluated on a DataFrame where each row is already ``groupby(...).sum()`` of those bases.

    Returns None for structurally additive KPIs (subtract / add only) or unsupported shapes.
    """
    if "denominator" in kpi:
        num = _expand_numerator(str(kpi["numerator"]), by_name, set(), base_metric_names)
        den = _expand_numerator(str(kpi["denominator"]), by_name, set(), base_metric_names)
        mult = kpi.get("multiply", 1)
        try:
            mult_f = float(mult)
        except (TypeError, ValueError):
            mult_f = 1.0
        return (f"({num})", f"({den})", mult_f)

    if "divide_by" in kpi:
        num = _expand_numerator(str(kpi["numerator"]), by_name, set(), base_metric_names)
        div = kpi["divide_by"]
        try:
            div_f = float(div)
        except (TypeError, ValueError):
            raise ValueError(f"derived_kpi '{kpi.get('name')}': divide_by must be numeric") from None
        if div_f == 0:
            raise ValueError(f"derived_kpi '{kpi.get('name')}': divide_by cannot be zero")
        return (f"({num})", str(div_f), 1.0)

    if "multiply_by" in kpi:
        # Product of two metrics — treat as (numerator * multiply_by) / 1
        # This is structurally additive when both inputs are additive
        num = _expand_numerator(str(kpi["numerator"]), by_name, set(), base_metric_names)
        mul = _expand_numerator(str(kpi["multiply_by"]), by_name, set(), base_metric_names)
        return (f"(({num}) * ({mul}))", "1", 1.0)

    return None


def column_refs_in_expr(expr: str, available_columns: Set[str]) -> Set[str]:
    """Return dataset column names referenced in a pandas-eval expression."""
    found: Set[str] = set()
    for m in re.finditer(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\b", expr):
        name = m.group(1)
        if name in _PANDAS_EVAL_RESERVED:
            continue
        if name in available_columns:
            found.add(name)
    return found


def derived_kpis_to_metric_definitions(
    derived_kpis: List[Dict[str, Any]],
    base_metric_names: Set[str],
) -> List[Dict[str, Any]]:
    """Return MetricDefinition-shaped dicts for each derived KPI (for merging into contract.metrics)."""
    by_name = {k["name"]: k for k in derived_kpis if k.get("name")}
    out: List[Dict[str, Any]] = []
    for kpi in derived_kpis:
        nm = kpi.get("name")
        if not nm or nm in base_metric_names:
            continue
        formula = kpi_to_formula(kpi, by_name, base_metric_names, set())
        fmt = kpi.get("format") or "float"
        if fmt == "percentage":
            fmt = "percent"
        if fmt not in ("currency", "percent", "integer", "float"):
            fmt = "float"
        out.append({
            "name": nm,
            "column": None,
            "type": "derived",
            "format": fmt,
            "optimization": "maximize",
            "description": kpi.get("description"),
            "formula": formula,
            "computed_by": "pipeline",
        })
    return out
