"""Per-item metrics for statistical summary."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..stat_summary.state import SummaryState


def compute_account_metrics(state: SummaryState) -> None:
    account_stats: list[dict] = []
    for account in state.pivot.index:
        values = state.pivot.loc[account].values
        values_clean = values[~np.isnan(values)]
        if len(values_clean) == 0:
            continue

        avg = float(np.mean(values_clean))
        std = float(np.std(values_clean))
        cv = abs(std / avg) if avg != 0 else 0

        last_values = values_clean[-3:] if len(values_clean) >= 3 else values_clean
        slope = 0.0
        slope_p_value = 1.0
        slope_r_value = 0.0
        if len(last_values) >= 3:
            x = np.arange(len(last_values), dtype=float)
            try:
                from scipy import stats as scipy_stats

                lr = scipy_stats.linregress(x, last_values)
                slope = float(lr.slope)
                slope_p_value = float(lr.pvalue) if not np.isnan(lr.pvalue) else 1.0
                slope_r_value = float(lr.rvalue) if not np.isnan(lr.rvalue) else 0.0
            except Exception:
                slope = float(np.polyfit(x, last_values, 1)[0])

        acceleration = 0.0
        if len(values_clean) >= 6:
            prev_3 = values_clean[-6:-3]
            x2 = np.arange(len(prev_3), dtype=float)
            try:
                from scipy import stats as scipy_stats

                lr2 = scipy_stats.linregress(x2, prev_3)
                slope_prev = float(lr2.slope)
            except Exception:
                slope_prev = float(np.polyfit(x2, prev_3, 1)[0])
            acceleration = float(slope - slope_prev)

        item_name = state.names_map.get(account, account)
        account_stats.append(
            {
                "item": account,
                "item_name": item_name,
                "avg": round(avg, 2),
                "std": round(std, 2),
                "cv": round(cv, 4),
                "slope_3mo": round(slope, 2),
                "slope_3mo_p_value": round(slope_p_value, 6),
                "slope_3mo_r_value": round(slope_r_value, 4),
                "acceleration_3mo": round(acceleration, 2),
                "min": round(float(np.min(values_clean)), 2),
                "max": round(float(np.max(values_clean)), 2),
            }
        )

    state.account_stats = account_stats
    state.top_drivers = sorted(account_stats, key=lambda x: abs(x["avg"]), reverse=True)[:10]
    state.most_volatile = sorted(account_stats, key=lambda x: x["cv"], reverse=True)[:10]
