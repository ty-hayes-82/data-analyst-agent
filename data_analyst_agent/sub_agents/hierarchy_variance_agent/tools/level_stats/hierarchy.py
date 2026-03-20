"""Hierarchy helpers for level statistics computations."""
from __future__ import annotations

from typing import Optional, Tuple, Any

import pandas as pd  # noqa: F401 (type checking / future helpers)


def _coerce_filter_value(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    if isinstance(raw, (list, tuple, set)):
        cleaned = []
        for val in raw:
            if val is None:
                continue
            text = str(val).strip()
            if text:
                cleaned.append(text)
        unique = []
        for val in cleaned:
            if val not in unique:
                unique.append(val)
        if len(unique) == 1:
            return unique[0]
        return None
    return str(raw).strip() if str(raw).strip() else None


def _lookup_filter_value(filters: Any, column: str) -> Optional[str]:
    if not isinstance(filters, dict) or not column:
        return None
    if column not in filters:
        return None
    return _coerce_filter_value(filters[column])


def resolve_level_metadata(
    df,
    ctx: Any,
    level: int,
    hierarchy_name: Optional[str],
    grain_col: str,
):
    """Return (level_col, level_name, is_last_level, skip_info) for the requested level."""
    hierarchies = getattr(ctx.contract, "hierarchies", None) if ctx and ctx.contract else None
    if not hierarchies:
        level_col = grain_col
        level_name = "Grain"
        is_last = True
        skip_info = _build_skip_info(ctx, level, None, level_col, level_name)
        return level_col, level_name, is_last, skip_info

    selected_hierarchy = next(
        (h for h in hierarchies if getattr(h, "name", None) == hierarchy_name),
        hierarchies[0],
    )
    dimensions = getattr(selected_hierarchy, "children", []) or []
    level_names = getattr(selected_hierarchy, "level_names", {}) or {}

    semantic_name = None
    if level == 0:
        df["_total_agg"] = "Total"
        level_col = "_total_agg"
        level_name = level_names.get(0, "Total")
        is_last = False
        skip_info = None
        return level_col, level_name, is_last, skip_info

    if level <= len(dimensions):
        semantic_name = dimensions[level - 1]
        level_name = level_names.get(level, semantic_name)
        try:
            dim = ctx.contract.get_dimension(semantic_name)
            level_col = dim.column
        except Exception:
            level_col = semantic_name
        is_last = level == len(dimensions)
        skip_info = _build_skip_info(ctx, level, semantic_name, level_col, level_name)
        return level_col, level_name, is_last, skip_info

    level_col = grain_col
    level_name = "Detail"
    is_last = True
    skip_info = _build_skip_info(ctx, level, semantic_name, level_col, level_name)
    return level_col, level_name, is_last, skip_info


def _build_skip_info(ctx: Any, level: int, semantic_name: Optional[str], level_col: str, level_name: str) -> Optional[dict]:
    if level <= 0 or not level_col:
        return None
    dim_filters = getattr(ctx, "dimension_filters", {}) if ctx else {}
    hier_filters = getattr(ctx, "hierarchy_filters", {}) if ctx else {}
    filter_value = _lookup_filter_value(dim_filters, level_col)
    if filter_value is None:
        filter_value = _lookup_filter_value(hier_filters, level_col)
    if filter_value is None:
        return None

    dimension_label = level_name or level_col
    if ctx and ctx.contract and semantic_name:
        try:
            dim = ctx.contract.get_dimension(semantic_name)
            dimension_label = dim.name or dimension_label
        except Exception:
            dimension_label = semantic_name or dimension_label

    reason = (
        f"Dimension '{dimension_label}' is fixed to '{filter_value}' from upstream filters; skipping level."
    )
    return {
        "dimension": dimension_label,
        "column": level_col,
        "filter_value": filter_value,
        "reason": reason,
    }
