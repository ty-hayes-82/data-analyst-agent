"""Temporal aggregation utilities for focus-based data rollup."""

from __future__ import annotations

import pandas as pd
from typing import Optional


def aggregate_to_temporal_grain(
    df: pd.DataFrame,
    time_column: str,
    target_grain: str,
    metric_columns: list[str],
    dimension_columns: list[str],
    time_format: str = "%Y-%m-%d",
) -> pd.DataFrame:
    """Aggregate data to a target temporal grain (weekly, monthly, yearly).
    
    Args:
        df: Input DataFrame with time-series data
        time_column: Name of the time column
        target_grain: Target grain ('weekly', 'monthly', 'yearly')
        metric_columns: List of metric column names to aggregate (sum)
        dimension_columns: List of dimension columns to group by
        time_format: Format of the time column (default: '%Y-%m-%d')
    
    Returns:
        Aggregated DataFrame with the target temporal grain
    """
    if df.empty:
        return df
    
    if time_column not in df.columns:
        print(f"[TemporalAggregation] WARNING: Time column '{time_column}' not found")
        return df
    
    # Parse time column
    df = df.copy()
    df[time_column] = pd.to_datetime(df[time_column], format=time_format, errors="coerce")
    
    # Determine current grain by checking date differences
    sorted_df = df.sort_values(time_column)
    unique_dates = sorted_df[time_column].dropna().unique()
    
    if len(unique_dates) < 2:
        print(f"[TemporalAggregation] Not enough data points for aggregation (n={len(unique_dates)})")
        return df
    
    # Detect current grain
    date_diffs = pd.Series(unique_dates).diff().dropna()
    median_diff = date_diffs.median()
    
    if median_diff <= pd.Timedelta(days=1):
        current_grain = "daily"
    elif median_diff <= pd.Timedelta(days=7):
        current_grain = "weekly"
    elif median_diff <= pd.Timedelta(days=31):
        current_grain = "monthly"
    else:
        current_grain = "yearly"
    
    print(f"[TemporalAggregation] Detected current grain: {current_grain} (median diff: {median_diff})")
    
    # If already at target grain or finer, no aggregation needed
    grain_hierarchy = ["daily", "weekly", "monthly", "yearly"]
    current_idx = grain_hierarchy.index(current_grain) if current_grain in grain_hierarchy else 0
    target_idx = grain_hierarchy.index(target_grain) if target_grain in grain_hierarchy else 2
    
    if current_idx >= target_idx:
        print(f"[TemporalAggregation] Data already at {current_grain}, no aggregation needed for {target_grain}")
        return df
    
    # Create period column based on target grain
    if target_grain == "weekly":
        # Week ending (Sunday)
        df["_period"] = df[time_column].dt.to_period("W").apply(lambda x: x.end_time.date())
    elif target_grain == "monthly":
        # Month ending (last day of month)
        df["_period"] = df[time_column] + pd.offsets.MonthEnd(0)
        df["_period"] = df["_period"].dt.date
    elif target_grain == "yearly":
        # Year ending (Dec 31)
        df["_period"] = df[time_column].dt.year.apply(lambda y: pd.Timestamp(f"{y}-12-31").date())
    else:
        print(f"[TemporalAggregation] WARNING: Unsupported grain '{target_grain}'")
        return df
    
    # Filter out valid metric columns
    valid_metrics = [col for col in metric_columns if col in df.columns]
    if not valid_metrics:
        print(f"[TemporalAggregation] WARNING: No valid metric columns found")
        return df
    
    # Group by dimensions and period, sum metrics
    group_cols = dimension_columns + ["_period"]
    group_cols = [col for col in group_cols if col in df.columns]
    
    if not group_cols:
        print(f"[TemporalAggregation] WARNING: No grouping columns available")
        return df
    
    # Aggregate
    agg_dict = {col: "sum" for col in valid_metrics}
    aggregated = df.groupby(group_cols, as_index=False).agg(agg_dict)
    
    # Rename _period back to time_column
    aggregated = aggregated.rename(columns={"_period": time_column})
    
    # Convert back to string format
    aggregated[time_column] = pd.to_datetime(aggregated[time_column]).dt.strftime(time_format)
    
    print(f"[TemporalAggregation] Aggregated {len(df)} rows → {len(aggregated)} rows ({current_grain} → {target_grain})")
    
    return aggregated
