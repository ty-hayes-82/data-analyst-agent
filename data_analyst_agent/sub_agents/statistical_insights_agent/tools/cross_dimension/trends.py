"""Trend overlay helpers."""
from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats


def compute_trend_overlay(
    df: pd.DataFrame,
    aux_col: str,
    metric_col: str,
    time_col: str,
    trend_periods: int,
) -> List[dict]:
    """Compute per-aux-value trends and compare to overall trend."""
    periods = sorted(df[time_col].unique())
    if len(periods) < max(3, trend_periods):
        return []

    recent_periods = periods[-trend_periods:]
    recent = df[df[time_col].isin(recent_periods)]

    overall_by_period = recent.groupby(time_col)[metric_col].sum().sort_index()
    if len(overall_by_period) < 3:
        return []

    x = np.arange(len(overall_by_period), dtype=float)
    try:
        overall_lr = scipy_stats.linregress(x, overall_by_period.values)
        overall_slope = float(overall_lr.slope)
    except Exception:
        overall_slope = 0.0

    pivot = (
        recent.pivot_table(index=aux_col, columns=time_col, values=metric_col, aggfunc="sum")
        .reindex(columns=recent_periods)
        .fillna(0)
    )

    if pivot.empty:
        return []

    results = []
    ax = np.arange(pivot.shape[1], dtype=float)

    for aux_val in pivot.index:
        row_vals = pivot.loc[aux_val].values
        non_zero = np.count_nonzero(row_vals)
        if non_zero < 3:
            continue
        try:
            lr = scipy_stats.linregress(ax, row_vals)
            slope = float(lr.slope)
            r_sq = float(lr.rvalue**2) if not np.isnan(lr.rvalue) else 0
        except Exception:
            continue

        if r_sq < 0.3:
            continue

        direction = "declining" if slope < 0 else "increasing"
        if overall_slope != 0:
            same_sign = np.sign(slope) == np.sign(overall_slope)
            magnitude_ratio = abs(slope) / abs(overall_slope) if overall_slope != 0 else 999
            vs_overall = "aligned" if (same_sign and 0.5 < magnitude_ratio < 2) else "diverging"
        else:
            vs_overall = "diverging" if abs(slope) > 0 else "aligned"

        if vs_overall == "diverging":
            results.append(
                {
                    "auxiliary_value": str(aux_val),
                    "slope_per_period": round(slope, 2),
                    "r_squared": round(r_sq, 2),
                    "direction": direction,
                    "vs_overall_trend": vs_overall,
                    "label": (
                        f"{aux_val} {direction} at {abs(slope):,.0f}/period "
                        f"while network trend is {'flat' if abs(overall_slope) < abs(slope) * 0.1 else 'different'}"
                    ),
                }
            )

    results.sort(key=lambda r: abs(r["slope_per_period"]), reverse=True)
    return results
