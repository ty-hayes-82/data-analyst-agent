"""Time-period helpers for level statistics."""
from __future__ import annotations

import re
from typing import Any, List, Optional, Sequence, Tuple

import pandas as pd

from data_analyst_agent.semantic.lag_utils import (
    get_effective_lag_or_default,
    resolve_effective_latest_period,
)

_DEFAULT_TIME_FORMAT = "%Y-%m-%d"


def determine_period_context(
    df,
    ctx: Any,
    time_col: str,
    analysis_period: str,
) -> Tuple[str, Optional[str], Optional[Sequence[str]], int, List[str]]:
    """Return current_period plus lag metadata."""
    periods = sorted(df[time_col].unique())
    lag = (
        get_effective_lag_or_default(ctx.contract, ctx.target_metric)
        if ctx and ctx.contract and ctx.target_metric
        else 0
    )
    effective_current, lag_window = resolve_effective_latest_period(periods, lag)
    current_period = effective_current if analysis_period == "latest" else analysis_period
    return current_period, effective_current, lag_window, lag, periods


def resolve_full_year_yoy(
    df,
    level: int,
    level_col: str,
    level_name: str,
    metric_col: str,
    time_col: str,
    current_period: str,
    top_n: int,
    is_last_level: bool,
):
    """Handle the special YOY full-year aggregation mode."""
    if not re.fullmatch(r"\d{4}", str(current_period)):
        return None

    current_year = int(current_period)
    prior_year = current_year - 1

    if "year" not in df.columns:
        df["year"] = pd.to_datetime(df[time_col], errors="coerce").dt.year

    cur = df[df["year"] == current_year].copy()
    pri = df[df["year"] == prior_year].copy()

    if cur.empty or pri.empty:
        return {
            "error": "YearNotFound",
            "message": f"Year {current_year} or {prior_year} not found.",
            "level": level,
        }

    cur_grp = cur.groupby(level_col)[metric_col].sum()
    pri_grp = pri.groupby(level_col)[metric_col].sum()

    drivers = []
    for item, cur_val in cur_grp.items():
        prior_val = float(pri_grp.get(item, 0.0))
        cur_val = float(cur_val)
        var_d = cur_val - prior_val
        var_pct = (var_d / prior_val * 100.0) if prior_val else 0.0
        drivers.append(
            {
                "item": str(item),
                "current": cur_val,
                "prior": prior_val,
                "variance_dollar": var_d,
                "variance_pct": var_pct,
            }
        )

    drivers.sort(key=lambda d: abs(d.get("variance_dollar", 0.0)), reverse=True)

    total_var = sum(d["variance_dollar"] for d in drivers)
    return {
        "level": level,
        "level_name": level_name,
        "metric": metric_col,
        "analysis_period": str(current_year),
        "variance_type": "yoy_full_year",
        "total_variance_dollar": total_var,
        "top_drivers": [{"rank": i + 1, **d} for i, d in enumerate(drivers[:top_n])],
        "items_analyzed": int(len(drivers)),
        "variance_explained_pct": 100.0,
        "is_last_level": is_last_level,
    }


def resolve_prior_period_str(
    df,
    ctx: Any,
    time_col: str,
    variance_type: str,
    current_period: str,
) -> str:
    """Return the best prior-period string for the variance calc."""
    current_date = pd.to_datetime(current_period)
    if variance_type.lower() == "yoy":
        prior_date = current_date - pd.DateOffset(years=1)
    elif variance_type.lower() == "mom":
        prior_date = current_date - pd.DateOffset(months=1)
    elif variance_type.lower() == "qoq":
        prior_date = current_date - pd.DateOffset(months=3)
    else:
        prior_date = current_date - pd.DateOffset(years=1)

    all_periods = sorted(pd.to_datetime(df[time_col].unique()))
    if all_periods:
        best_prior = min(all_periods, key=lambda d: abs(d - prior_date))
        if abs((best_prior - prior_date).days) <= 7:
            return best_prior.strftime(_resolve_time_format(ctx))
    return prior_date.strftime(_resolve_time_format(ctx))


def _resolve_time_format(ctx: Any) -> str:
    try:
        return ctx.contract.time.format  # type: ignore[attr-defined]
    except Exception:
        return _DEFAULT_TIME_FORMAT
