"""Level statistics tool orchestrator."""
from __future__ import annotations

import json
import os
from typing import Optional

import pandas as pd

from data_analyst_agent.sub_agents.data_cache import resolve_data_and_columns
from .hierarchy import resolve_level_metadata
from .materiality import get_materiality_thresholds
from .periods import (
    determine_period_context,
    resolve_full_year_yoy,
    resolve_prior_period_str,
    resolve_rolling_average,
)
from .ratio_metrics import compute_ratio_aggregations


async def compute_level_statistics_impl(
    level: int,
    analysis_period: str = "latest",
    variance_type: str = "yoy",
    top_n: int = 10,
    cumulative_threshold: float = 80.0,
    hierarchy_name: Optional[str] = None,
) -> str:
    try:
        df, time_col, metric_col, grain_col, name_col, ctx = resolve_data_and_columns(
            "LevelStatistics"
        )
    except ValueError as exc:
        return json.dumps(
            {
                "error": "ContextNotFound",
                "message": str(exc),
                "level": level,
            }
        )

    if not ctx or not ctx.contract:
        return json.dumps(
            {
                "error": "ContractNotFound",
                "message": "No semantic contract found.",
                "level": level,
            }
        )

    level_col, level_name, is_last_level, skip_info = resolve_level_metadata(
        df, ctx, level, hierarchy_name, grain_col
    )
    if level_col not in df.columns:
        return json.dumps(
            {
                "error": "InvalidDimension",
                "message": f"Column '{level_col}' (for dimension '{level_name}') not found in data.",
                "level": level,
            }
        )

    if skip_info:
        payload = {
            "level": level,
            "level_name": level_name,
            "is_last_level": is_last_level,
            "is_duplicate": True,
            "skip_reason": skip_info.get("reason"),
            "dimension_filter_applied": True,
            "filter_value": skip_info.get("filter_value"),
            "dimension": skip_info.get("dimension"),
        }
        return json.dumps(payload, indent=2)

    (
        current_period,
        effective_current,
        lag_window,
        lag,
        _,
    ) = determine_period_context(df, ctx, time_col, analysis_period)

    # Auto-detect grain and override variance_type for weekly/daily data
    grain = getattr(ctx, "temporal_grain", None) or ""
    if variance_type.lower() == "yoy" and grain.lower() in ("weekly", "daily", "w", "d"):
        all_periods = sorted(pd.to_datetime(df[time_col].unique()))
        if len(all_periods) >= 2:
            median_gap = pd.Series(all_periods).diff().median()
            if median_gap and median_gap.days <= 8:
                variance_type = "wow"
                print(f"[LevelStats] Auto-switched to WoW comparison for {grain} grain (median gap: {median_gap.days}d)")

    full_year_payload = None
    if variance_type.lower() == "yoy":
        full_year_payload = resolve_full_year_yoy(
            df,
            level,
            level_col,
            level_name,
            metric_col,
            time_col,
            current_period,
            top_n,
            is_last_level,
        )
    if full_year_payload:
        return json.dumps(full_year_payload, indent=2)

    prior_period_str = resolve_prior_period_str(
        df, ctx, time_col, variance_type, current_period
    )

    df[time_col] = df[time_col].astype(str)

    ratio_config, current_agg, prior_agg, network_variance = compute_ratio_aggregations(
        df,
        ctx,
        level_col,
        time_col,
        grain_col,
        metric_col,
        current_period,
        prior_period_str,
    )

    if current_agg.empty:
        return json.dumps(
            {
                "error": "PeriodNotFound",
                "message": f"Period {current_period} not found.",
                "level": level,
            }
        )

    merged = current_agg.merge(prior_agg, on="item", how="outer").fillna(0)
    merged["variance_dollar"] = merged.get("current", 0) - merged.get("prior", 0)

    prior_abs = merged["prior"].abs().replace(0, float("nan"))
    merged["variance_pct"] = (merged["current"] - merged["prior"]) / prior_abs * 100
    merged["is_new_from_zero"] = (merged["prior"] == 0) & (merged["current"] != 0)

    total_current = merged["current"].sum() or 1e-9
    total_prior = merged["prior"].sum() or 1e-9
    merged["share_current"] = merged["current"] / total_current
    merged["share_prior"] = merged["prior"] / total_prior
    merged["share_change"] = merged["share_current"] - merged["share_prior"]

    pct_threshold, dollar_threshold = get_materiality_thresholds(ctx)
    merged["exceeds_threshold"] = (
        (merged["variance_dollar"].abs() >= dollar_threshold)
        | (merged["variance_pct"].abs() >= pct_threshold)
    )
    merged["materiality"] = merged["exceeds_threshold"].apply(
        lambda exceeded: "HIGH" if exceeded else "LOW"
    )

    share_mode = os.environ.get("LAG_METRIC_SHARE_MODE", "true").lower() == "true"
    if lag > 0 and share_mode:
        merged = merged.sort_values(
            "share_change", key=lambda series: series.abs(), ascending=False
        )
    else:
        merged = merged.sort_values(
            "variance_dollar", key=lambda series: series.abs(), ascending=False
        )

    total_abs_variance = merged["variance_dollar"].abs().sum() or 1e-9
    merged["cumulative_pct"] = (
        merged["variance_dollar"].abs().cumsum() / total_abs_variance * 100
    )
    merged["rank"] = range(1, len(merged) + 1)

    top_items = merged.head(top_n)
    variance_explained = (
        float(top_items["cumulative_pct"].iloc[-1]) if not top_items.empty else 0
    )

    # Vectorized top drivers processing (avoid iterrows)
    top_drivers = []
    if not top_items.empty:
        top_items_copy = top_items.copy()
        top_items_copy['variance_pct_clean'] = top_items_copy['variance_pct'].apply(
            lambda x: None if pd.isna(x) else float(x)
        )
        top_drivers = top_items_copy.apply(
            lambda row: {
                "rank": int(row["rank"]),
                "item": str(row["item"]),
                "current": float(row["current"]),
                "prior": float(row["prior"]),
                "variance_dollar": float(row["variance_dollar"]),
                "variance_pct": row["variance_pct_clean"],
                "is_new_from_zero": bool(row.get("is_new_from_zero", False)),
                "share_current": float(row["share_current"]),
                "share_prior": float(row["share_prior"]),
                "share_change": float(row["share_change"]),
                "cumulative_pct": float(row["cumulative_pct"]),
                "exceeds_threshold": bool(row["exceeds_threshold"]),
                "materiality": row["materiality"],
                **({"ratio_current": float(row["ratio_current"])} if "ratio_current" in row and not pd.isna(row["ratio_current"]) else {}),
                **({"ratio_prior": float(row["ratio_prior"])} if "ratio_prior" in row and not pd.isna(row["ratio_prior"]) else {}),
                **({"ratio_variance": float(row["ratio_variance"])} if "ratio_variance" in row and not pd.isna(row["ratio_variance"]) else {}),
            },
            axis=1
        ).tolist()

    # Enrich top drivers with rolling average context
    try:
        rolling_df = resolve_rolling_average(
            df, time_col, metric_col, level_col, current_period, window=4
        )
        if not rolling_df.empty:
            avg_map = dict(zip(rolling_df["item"].astype(str), rolling_df["rolling_avg"]))
            periods_used = int(rolling_df["periods_used"].iloc[0]) if not rolling_df.empty else 0
            for driver in top_drivers:
                item = str(driver.get("item", ""))
                if item in avg_map:
                    avg_val = avg_map[item]
                    driver["rolling_avg"] = round(float(avg_val), 2)
                    driver["rolling_avg_window"] = periods_used
                    current_val = driver.get("current", 0)
                    if avg_val and avg_val != 0:
                        driver["vs_rolling_avg_pct"] = round(
                            (current_val - avg_val) / abs(avg_val) * 100, 2
                        )
    except Exception as e:
        print(f"[LevelStats] Rolling average enrichment failed: {e}")

    total_variance_dollar = (
        network_variance
        if network_variance is not None
        else float(merged["variance_dollar"].sum())
    )

    result = {
        "level": level,
        "level_name": level_name,
        "metric": metric_col,
        "analysis_period": current_period,
        "prior_period": prior_period_str,
        "lag_metadata": (
            {
                "lag_periods": lag,
                "effective_latest_period": str(effective_current),
                "lag_window": [str(period) for period in lag_window],
            }
            if lag > 0
            else None
        ),
        "variance_type": variance_type.upper(),
        "total_variance_dollar": total_variance_dollar,
        "current_total": float(total_current),
        "prior_total": float(total_prior),
        "top_drivers": top_drivers,
        "items_analyzed": len(merged),
        "variance_explained_pct": round(variance_explained, 2),
        "is_last_level": is_last_level,
    }

    return json.dumps(result, indent=2)

