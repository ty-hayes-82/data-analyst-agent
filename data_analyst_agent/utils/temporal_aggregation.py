"""Temporal aggregation utilities for focus-based data rollup."""

from __future__ import annotations

import pandas as pd
from typing import Optional


def aggregate_temporal_data(
    df: pd.DataFrame,
    time_column: str,
    target_grain: str,
    metric_columns: list[str],
    dimension_columns: list[str],
    time_format: str = "%Y-%m-%d",
) -> pd.DataFrame:
    """Aggregate time-series data to a coarser temporal grain (daily → weekly → monthly → yearly).
    
    This function intelligently detects the current temporal grain of the data
    and aggregates it to the target grain if needed. It uses median date differences
    to infer the current grain (daily/weekly/monthly/yearly).
    
    Aggregation only happens when rolling up to a coarser grain. If data is already
    at or coarser than the target grain, it's returned unchanged.
    
    Grain Hierarchy:
        daily → weekly → monthly → yearly
    
    Use Cases:
        - Focus directives: User requests "monthly trends" but data is daily
        - Performance optimization: Reduce data volume for high-level analysis
        - Standardization: Normalize mixed-grain datasets to common grain
    
    Args:
        df: Input DataFrame with time-series data. Must contain time_column,
            metric_columns, and dimension_columns.
        time_column: Name of the date/time column (e.g., "week_ending", "date").
            Will be parsed to datetime using time_format.
        target_grain: Desired temporal grain. Valid values:
            - "daily": Daily observations
            - "weekly": Week-ending (Sunday) aggregation
            - "monthly": Month-ending (last day of month) aggregation
            - "yearly": Year-ending (Dec 31) aggregation
        metric_columns: List of metric columns to aggregate (summed).
            Only columns present in df will be aggregated.
        dimension_columns: List of dimension columns to group by (e.g., "lob",
            "terminal"). Aggregation is performed within each dimension group.
        time_format: strptime format string for parsing time_column.
            Default: "%Y-%m-%d". Common formats:
            - "%Y-%m-%d": 2025-03-12
            - "%Y-%m": 2025-03
            - "%Y%m%d": 20250312
    
    Returns:
        pd.DataFrame: Aggregated DataFrame with same columns as input.
            If aggregation performed, row count will be reduced.
            If no aggregation needed, returns original df.
    
    Algorithm:
        1. Parse time_column to datetime
        2. Detect current grain by computing median date difference:
           * ≤1 day: daily
           * ≤7 days: weekly
           * ≤31 days: monthly
           * >31 days: yearly
        3. Compare current grain to target grain using hierarchy
        4. If current ≥ target (already at or coarser), return unchanged
        5. Otherwise, create period column based on target grain:
           * weekly: Week ending (Sunday)
           * monthly: Month ending (last day of month)
           * yearly: Year ending (Dec 31)
        6. Group by [dimension_columns, period], sum metric_columns
        7. Rename period back to time_column
    
    Example:
        >>> df = pd.DataFrame({
        ...     'date': ['2025-01-01', '2025-01-02', '2025-01-03'],
        ...     'lob': ['Retail', 'Retail', 'Wholesale'],
        ...     'revenue': [100, 150, 200]
        ... })
        >>> agg = aggregate_temporal_data(
        ...     df, 'date', 'weekly', ['revenue'], ['lob']
        ... )
        >>> # Returns weekly aggregated data with 2 rows (1 per LOB)
    
    Note:
        - Empty DataFrames returned unchanged
        - Missing time_column triggers warning and returns original df
        - Requires ≥2 unique dates to detect grain
        - Invalid metric_columns (not in df) are skipped
        - Time column converted back to string format on return
        - Logs current grain detection and aggregation results
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


# Alias for backward compatibility
aggregate_to_temporal_grain = aggregate_temporal_data
