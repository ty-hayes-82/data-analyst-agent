"""Hierarchy helpers for level statistics computations."""
from __future__ import annotations

from typing import Optional, Tuple, Any

import pandas as pd  # noqa: F401 (type checking / future helpers)


def resolve_level_metadata(
    df,
    ctx: Any,
    level: int,
    hierarchy_name: Optional[str],
    grain_col: str,
):
    """Return (level_col, level_name, is_last_level) for the requested level."""
    hierarchies = getattr(ctx.contract, "hierarchies", None) if ctx and ctx.contract else None
    if not hierarchies:
        return grain_col, "Grain", True

    selected_hierarchy = next(
        (h for h in hierarchies if getattr(h, "name", None) == hierarchy_name),
        hierarchies[0],
    )
    dimensions = getattr(selected_hierarchy, "children", []) or []
    level_names = getattr(selected_hierarchy, "level_names", {}) or {}

    if level == 0:
        df["_total_agg"] = "Total"
        return "_total_agg", level_names.get(0, "Total"), False

    if level <= len(dimensions):
        semantic_name = dimensions[level - 1]
        level_name = level_names.get(level, semantic_name)
        try:
            dim = ctx.contract.get_dimension(semantic_name)
            level_col = dim.column
        except Exception:
            level_col = semantic_name
        return level_col, level_name, level == len(dimensions)

    return grain_col, "Detail", True
