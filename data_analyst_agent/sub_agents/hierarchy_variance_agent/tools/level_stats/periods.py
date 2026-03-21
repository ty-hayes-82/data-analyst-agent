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
    raw = df[time_col].unique()
    # Filter NaT/null before sorting
    periods = sorted([p for p in raw if pd.notna(p) and str(p).strip() not in ('', 'NaT', 'nan')])
    lag = (
        get_effective_lag_or_default(ctx.contract, ctx.target_metric)
        if ctx and ctx.contract and ctx.target_metric
        else 0
    )
    effective_current, lag_window = resolve_effective_latest_period(periods, lag)
    if analysis_period == "latest":
        current_period = effective_current
    else:
        # Normalize: strip time component and try to match data periods
        clean = str(analysis_period).split(" ")[0].split("T")[0]
        # Find matching period in data (prefix match handles format differences)
        matched = next((p for p in periods if str(p).startswith(clean)), None)
        current_period = matched if matched is not None else clean
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
    current_date = pd.to_datetime(current_period, errors="coerce")
    if pd.isna(current_date):
        return str(current_period)
    # Filter out NaT values before sorting
    parsed = pd.to_datetime(df[time_col].unique(), errors="coerce")
    all_periods = sorted([p for p in parsed if pd.notna(p)])
    fmt = _resolve_time_format(ctx)
    if not all_periods:
        return str(current_period)

    vtype = variance_type.lower()
    if vtype == "wow":
        prior_date = current_date - pd.DateOffset(weeks=1)
    elif vtype == "yoy":
        prior_date = current_date - pd.DateOffset(years=1)
    elif vtype == "mom":
        prior_date = current_date - pd.DateOffset(months=1)
    elif vtype == "qoq":
        prior_date = current_date - pd.DateOffset(months=3)
    else:
        prior_date = current_date - pd.DateOffset(years=1)

    # Build a map from parsed dates back to original string representation
    # to avoid format mismatches (e.g., "2026-03-07" vs "2026-03-07 00:00:00")
    raw_periods = sorted(df[time_col].unique())
    parsed_to_raw = {}
    for raw_p in raw_periods:
        try:
            parsed_to_raw[pd.to_datetime(raw_p)] = str(raw_p)
        except Exception:
            pass

    if all_periods:
        best_prior = min(all_periods, key=lambda d: abs((d - prior_date).total_seconds()) if pd.notna(d) else float('inf'))
        max_gap = 3 if vtype == "wow" else 7
        diff = best_prior - prior_date
        if pd.notna(diff) and abs(diff.days) <= max_gap:
            # Return the ORIGINAL string from the data, not a reformatted version
            return parsed_to_raw.get(best_prior, best_prior.strftime(fmt))

    # Fallback for wow: use the immediately preceding period in the data
    if vtype == "wow" and all_periods:
        earlier = [p for p in all_periods if p < current_date]
        if earlier:
            return parsed_to_raw.get(earlier[-1], earlier[-1].strftime(fmt))

    return prior_date.strftime(fmt)


def resolve_rolling_average(
    df,
    time_col: str,
    metric_col: str,
    level_col: str,
    current_period: str,
    window: int = 4,
) -> pd.DataFrame:
    """Compute N-period rolling average per entity for comparison context.

    Returns DataFrame with columns: item, rolling_avg, periods_used.
    """
    current_date = pd.to_datetime(current_period, errors="coerce")
    if pd.isna(current_date):
        return pd.DataFrame(columns=["item", "rolling_avg", "periods_used"])
    parsed = pd.to_datetime(df[time_col].unique(), errors="coerce")
    all_periods = sorted([p for p in parsed if pd.notna(p)])
    earlier = [p for p in all_periods if p < current_date]
    lookback = earlier[-window:] if len(earlier) >= window else earlier

    if not lookback:
        return pd.DataFrame(columns=["item", "rolling_avg", "periods_used"])

    lookback_strs = [p.strftime("%Y-%m-%d") for p in lookback]
    mask = df[time_col].astype(str).isin(lookback_strs)
    avg_df = (
        df[mask]
        .groupby(level_col)[metric_col]
        .mean()
        .reset_index()
        .rename(columns={level_col: "item", metric_col: "rolling_avg"})
    )
    avg_df["periods_used"] = len(lookback)
    return avg_df


def _resolve_time_format(ctx: Any) -> str:
    try:
        return ctx.contract.time.format  # type: ignore[attr-defined]
    except Exception:
        return _DEFAULT_TIME_FORMAT
