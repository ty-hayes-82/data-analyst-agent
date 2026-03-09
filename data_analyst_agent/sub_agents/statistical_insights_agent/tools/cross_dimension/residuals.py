"""Residual analysis helpers."""
from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd


def compute_residual_analysis(
    cell_agg: pd.DataFrame, hier_col: str, aux_col: str, top_n: int
) -> List[dict]:
    """Flag (entity, aux_value) cells that deviate from expected (row + col means)."""
    if cell_agg.empty or cell_agg["total"].std() == 0:
        return []

    pivot = cell_agg.pivot_table(index=hier_col, columns=aux_col, values="total", aggfunc="sum")
    if pivot.empty:
        return []

    vals = pivot.values
    mask = ~np.isnan(vals)
    if mask.sum() == 0:
        return []

    grand_mean = vals[mask].mean()
    row_means = np.nanmean(vals, axis=1, keepdims=True)
    col_means = np.nanmean(vals, axis=0, keepdims=True)

    expected = row_means + col_means - grand_mean
    residuals = vals - expected
    residual_std = float(np.nanstd(residuals)) or 1e-9
    z_scores = residuals / residual_std

    significant = np.abs(z_scores) >= 2.0
    significant &= mask
    rows_idx, cols_idx = np.where(significant)

    if len(rows_idx) == 0:
        return []

    z_vals = np.abs(z_scores[rows_idx, cols_idx])
    order = np.argsort(-z_vals)[:top_n]

    entities = pivot.index
    aux_vals = pivot.columns

    results = []
    for i in order:
        r, c = rows_idx[i], cols_idx[i]
        actual = float(vals[r, c])
        exp = float(expected[r, c])
        z = float(z_scores[r, c])
        entity = str(entities[r])
        aux_val = str(aux_vals[c])
        results.append(
            {
                "hierarchy_entity": entity,
                "auxiliary_value": aux_val,
                "actual": round(actual, 2),
                "expected": round(exp, 2),
                "residual": round(actual - exp, 2),
                "residual_z": round(z, 2),
                "label": (
                    f"{entity} + {aux_val} is {abs(actual - exp):,.0f} "
                    f"{'above' if actual > exp else 'below'} expected ({z:+.1f} sigma)"
                ),
            }
        )

    return results
