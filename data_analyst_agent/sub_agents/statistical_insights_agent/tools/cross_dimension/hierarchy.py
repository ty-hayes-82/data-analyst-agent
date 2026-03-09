"""Hierarchy helpers for cross-dimension analysis."""
from __future__ import annotations

from typing import Optional

import pandas as pd


def resolve_hierarchy_col(contract, level: int, grain_col: str, df: pd.DataFrame) -> Optional[str]:
    """Map hierarchy level to a physical column name."""
    hierarchies = contract.hierarchies if contract else None
    if not hierarchies:
        return grain_col if level == 0 else None

    hierarchy = hierarchies[0]
    if level == 0:
        if "_total_agg" not in df.columns:
            df["_total_agg"] = "Total"
        return "_total_agg"

    if level <= len(hierarchy.children):
        semantic = hierarchy.children[level - 1]
        try:
            return contract.get_dimension(semantic).column
        except KeyError:
            return semantic if semantic in df.columns else None

    return None
