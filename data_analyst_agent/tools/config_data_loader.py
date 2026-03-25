# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Config-driven universal data loader.

Reads dataset-specific loader.yaml to perform ETL (wide-to-long, cleaning, parsing)
and returns a standardized long-format DataFrame.
"""

import os
import sys
from pathlib import Path
from typing import List, Optional, Union, Dict, Any

import pandas as pd
import yaml

# --- CACHE: Survive multiple imports via sys.modules ---
if '_config_data_loader_cache' not in sys.modules:
    sys.modules['_config_data_loader_cache'] = {}
_cache = sys.modules['_config_data_loader_cache']

# --- AGGREGATION THRESHOLD ---
# Default; overridden by contract.analysis.aggregation_row_threshold
AUTO_AGGREGATION_ROW_THRESHOLD = 100_000  # Auto-aggregate datasets with >100K rows


def _aggregate_to_grain(
    df: pd.DataFrame,
    dataset_name: str,
    config: Dict[str, Any],
    dimension_filters: Optional[Dict[str, Any]] = None,
) -> pd.DataFrame:
    """Intelligent data aggregation to reduce row volume and improve performance.
    
    Aggregates data in two dimensions:
    1. Temporal: daily → weekly/monthly based on contract or env var
    2. Dimensional: county → state using hierarchy metadata
    
    Aggregation methods determined by metric type from contract:
    - additive: sum (e.g., revenue, cases)
    - ratio/non_additive: mean (e.g., conversion_rate, temperature)
    
    Args:
        df: Raw long-format DataFrame from ETL
        dataset_name: Dataset name for contract lookup
        config: Loader config with metric_column info
        dimension_filters: Optional dimension filters to inform aggregation level
    
    Returns:
        Aggregated DataFrame, potentially much smaller than input
    """
    if df.empty:
        return df
    
    original_rows = len(df)
    
    # Skip aggregation if dataset is already small
    if original_rows < AUTO_AGGREGATION_ROW_THRESHOLD:
        return df
    
    # Load contract to get metadata
    try:
        from config.dataset_resolver import get_dataset_dir
        from ..utils.contract_cache import load_contract_cached
        
        dataset_dir = get_dataset_dir(dataset_name)
        contract_path = dataset_dir / "contract.yaml"
        
        if not contract_path.exists():
            print(f"[Aggregation] Contract not found, skipping aggregation")
            return df
        
        contract = load_contract_cached(str(contract_path))
    except Exception as e:
        print(f"[Aggregation] Failed to load contract: {e}, skipping aggregation")
        return df
    
    # --- TEMPORAL AGGREGATION ---
    time_col = contract.time.column
    current_freq = contract.time.frequency
    
    # Determine target grain from env var or contract
    target_grain = os.getenv("DATA_ANALYST_AGGREGATION_GRAIN")
    
    if not target_grain:
        # Auto-infer: if daily data with >100K rows, aggregate to weekly
        if current_freq == "daily" and original_rows > AUTO_AGGREGATION_ROW_THRESHOLD:
            target_grain = "weekly"
        else:
            # Data already at coarse grain, no temporal aggregation needed
            target_grain = current_freq
    
    # Only aggregate if we're rolling up to coarser grain
    grain_hierarchy = ["daily", "weekly", "monthly", "quarterly", "yearly"]
    try:
        current_idx = grain_hierarchy.index(current_freq)
        target_idx = grain_hierarchy.index(target_grain)
    except ValueError:
        # Unknown grain, skip temporal aggregation
        current_idx = target_idx = 0
    
    if target_idx > current_idx:
        # Need temporal aggregation
        df = _aggregate_temporal_grain(df, contract, time_col, target_grain, config)
    
    # --- DIMENSIONAL AGGREGATION ---
    # Check if we have hierarchies defined and can aggregate
    if contract.hierarchies:
        df = _aggregate_dimensional_grain(df, contract, dimension_filters or {})
    
    final_rows = len(df)
    if final_rows < original_rows:
        reduction_pct = (1 - final_rows / original_rows) * 100
        print(f"[Aggregation] {original_rows:,} rows → {final_rows:,} rows ({reduction_pct:.1f}% reduction)")
    
    return df


def _aggregate_temporal_grain(
    df: pd.DataFrame,
    contract,
    time_col: str,
    target_grain: str,
    config: Dict[str, Any],
) -> pd.DataFrame:
    """Aggregate time dimension (daily → weekly/monthly)."""
    if time_col not in df.columns:
        return df
    
    # Parse time column
    df = df.copy()
    df[time_col] = pd.to_datetime(df[time_col], errors="coerce")
    
    # Create period column based on target grain
    if target_grain == "weekly":
        # Week ending (Sunday)
        df["_period"] = df[time_col].dt.to_period("W").apply(lambda x: x.end_time.date())
    elif target_grain == "monthly":
        # Month ending (last day of month)
        df["_period"] = df[time_col] + pd.offsets.MonthEnd(0)
        df["_period"] = df["_period"].dt.date
    elif target_grain == "quarterly":
        # Quarter ending
        df["_period"] = df[time_col].dt.to_period("Q").apply(lambda x: x.end_time.date())
    elif target_grain == "yearly":
        # Year ending (Dec 31)
        df["_period"] = df[time_col].dt.year.apply(lambda y: pd.Timestamp(f"{y}-12-31").date())
    else:
        return df  # Unsupported grain
    
    # Determine data format (long vs wide)
    metric_col = config.get("metric_column") or "metric"
    value_col = config.get("melt", {}).get("value_name", "value")
    
    # Check if this is long format (has metric + value columns)
    is_long_format = metric_col in df.columns and value_col in df.columns
    
    if is_long_format:
        # --- LONG FORMAT: metric column identifies different metrics ---
        # Convert value column to numeric BEFORE aggregation
        df[value_col] = pd.to_numeric(df[value_col], errors="coerce")
        
        dimension_cols = [col for col in df.columns if col not in [time_col, "_period", value_col, metric_col]]
        
        # Determine aggregation method per metric
        agg_methods = _get_metric_aggregation_methods(contract, df, metric_col)
        
        # Group by period + dimensions + metric
        group_cols = ["_period"] + dimension_cols + [metric_col]
        group_cols = [col for col in group_cols if col in df.columns]
        
        # Aggregate each metric separately with its own method
        aggregated_dfs = []
        for metric_name, agg_method in agg_methods.items():
            metric_df = df[df[metric_col] == metric_name]
            if metric_df.empty:
                continue
            
            agg_dict = {value_col: agg_method}
            aggregated = metric_df.groupby(group_cols, as_index=False).agg(agg_dict)
            aggregated_dfs.append(aggregated)
        
        if aggregated_dfs:
            df = pd.concat(aggregated_dfs, ignore_index=True)
        else:
            # Fallback: sum all values
            df = df.groupby(group_cols, as_index=False).agg({value_col: "sum"})
    else:
        # --- WIDE FORMAT: each metric is a separate column ---
        # Identify metric columns from contract and convert to numeric
        metric_columns = [m.column for m in contract.metrics if m.column and m.column in df.columns]
        
        # Convert metric columns to numeric BEFORE aggregation
        for col in metric_columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        
        # Build aggregation dict based on metric types
        agg_dict = {}
        for metric in contract.metrics:
            if not metric.column or metric.column not in df.columns:
                continue
            
            # Check if this is a cumulative metric
            is_cumulative = "cumulative" in [tag.lower() for tag in metric.tags]
            
            if metric.type == "additive":
                if is_cumulative:
                    # Cumulative additive: take max value (last observation)
                    agg_dict[metric.column] = "max"
                else:
                    # Incremental additive: sum
                    agg_dict[metric.column] = "sum"
            elif metric.type in ["ratio", "non_additive"]:
                agg_dict[metric.column] = "mean"
            else:
                # Derived: use sum as default
                agg_dict[metric.column] = "sum"
        
        # Get dimension columns (everything except time, period, and metrics)
        dimension_cols = [
            col for col in df.columns 
            if col not in [time_col, "_period"] + metric_columns
        ]
        
        # Group by period + dimensions
        group_cols = ["_period"] + dimension_cols
        group_cols = [col for col in group_cols if col in df.columns]
        
        if agg_dict:
            df = df.groupby(group_cols, as_index=False).agg(agg_dict)
        else:
            # Fallback: sum all numeric columns
            numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
            numeric_cols = [col for col in numeric_cols if col != "_period"]
            if numeric_cols:
                agg_dict = {col: "sum" for col in numeric_cols}
                df = df.groupby(group_cols, as_index=False).agg(agg_dict)
    
    # Rename _period back to time_col
    df = df.rename(columns={"_period": time_col})
    
    # Convert back to string format
    time_format = contract.time.format
    df[time_col] = pd.to_datetime(df[time_col]).dt.strftime(time_format)
    
    return df


def _aggregate_dimensional_grain(
    df: pd.DataFrame,
    contract,
    dimension_filters: Dict[str, Any],
) -> pd.DataFrame:
    """Aggregate dimensions up hierarchy (county → state).
    
    Detects when analyzing at a higher level than the data grain and automatically
    rolls up granular dimensions to parent levels.
    
    Examples:
        - Data grain: [date, state, county]
        - No filters → aggregate county → state (national view)
        - Filter state=California → aggregate county → state (state view)
        - Filter county=Los Angeles → no aggregation (already at leaf)
    
    Args:
        df: DataFrame with granular dimension data
        contract: DatasetContract with hierarchy definitions
        dimension_filters: Dimension filters that determine analysis level
    
    Returns:
        DataFrame aggregated to appropriate dimension level
    """
    if df.empty or not contract.hierarchies:
        return df
    
    original_rows = len(df)
    
    # Process each hierarchy
    for hierarchy in contract.hierarchies:
        if not hierarchy.children or len(hierarchy.children) < 2:
            continue  # Need at least 2 levels to aggregate
        
        # Hierarchy children are ordered from parent to child (e.g., ["state", "county"])
        parent_dim = hierarchy.children[0]
        child_dims = hierarchy.children[1:]
        
        # Check if parent dimension column exists in data
        if parent_dim not in df.columns:
            continue
        
        # Determine if we should aggregate based on filters
        should_aggregate = False
        target_level_dims = []
        
        if not dimension_filters:
            # No filters → aggregate to top level (parent only)
            should_aggregate = True
            target_level_dims = [parent_dim]
        else:
            # Check if any child dimensions are in the filter
            # If filtering on a child, we need that granularity
            has_child_filter = any(child in dimension_filters for child in child_dims)
            has_parent_filter = parent_dim in dimension_filters
            
            if has_parent_filter and not has_child_filter:
                # Filtering to a parent (e.g., state=California) but no child filter
                # → aggregate child dimensions to parent level
                should_aggregate = True
                target_level_dims = [parent_dim]
            elif not has_child_filter and not has_parent_filter:
                # No filter on this hierarchy at all → aggregate to parent
                should_aggregate = True
                target_level_dims = [parent_dim]
            # else: has_child_filter → don't aggregate, need child granularity
        
        if not should_aggregate:
            continue
        
        # Check if aggregation would actually reduce rows
        # (no point aggregating if data is already at parent level)
        all_child_cols_present = all(child in df.columns for child in child_dims)
        if not all_child_cols_present:
            continue  # Data already aggregated or missing child dimensions
        
        # Perform aggregation
        df = _perform_dimension_rollup(df, contract, parent_dim, child_dims, hierarchy.name)
    
    final_rows = len(df)
    if final_rows < original_rows:
        reduction_pct = (1 - final_rows / original_rows) * 100
        print(f"[Aggregation] Dimension roll-up: {original_rows:,} rows → {final_rows:,} rows ({reduction_pct:.1f}% reduction)")
    
    return df


def _perform_dimension_rollup(
    df: pd.DataFrame,
    contract,
    parent_dim: str,
    child_dims: List[str],
    hierarchy_name: str,
) -> pd.DataFrame:
    """Roll up child dimensions to parent level.
    
    Args:
        df: Input DataFrame
        contract: DatasetContract for metric aggregation methods
        parent_dim: Parent dimension to keep (e.g., "state")
        child_dims: Child dimensions to aggregate away (e.g., ["county"])
        hierarchy_name: Name of hierarchy for logging
    
    Returns:
        DataFrame with child dimensions aggregated to parent level
    """
    # Identify columns to group by (everything except child dimensions)
    group_cols = [col for col in df.columns if col not in child_dims]
    
    # Separate numeric and non-numeric columns
    numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
    non_numeric_cols = [col for col in df.columns if col not in numeric_cols]
    
    # Remove child dimensions from grouping columns
    group_cols = [col for col in group_cols if col in non_numeric_cols or col not in numeric_cols]
    
    # Build aggregation dict for numeric columns
    agg_dict = {}
    
    # Determine aggregation method per column based on contract
    for col in numeric_cols:
        if col in child_dims:
            continue  # Don't aggregate child dimension columns
        
        # Find metric definition for this column
        metric_def = None
        for m in contract.metrics:
            if m.column == col or m.name == col:
                metric_def = m
                break
        
        if metric_def:
            # Use contract-defined aggregation method
            is_cumulative = "cumulative" in [tag.lower() for tag in metric_def.tags]
            
            if metric_def.type == "additive":
                if is_cumulative:
                    agg_dict[col] = "max"  # Take last/highest value
                else:
                    agg_dict[col] = "sum"  # Sum incremental values
            elif metric_def.type in ["ratio", "non_additive"]:
                agg_dict[col] = "mean"  # Average ratios
            else:
                agg_dict[col] = "sum"  # Default to sum
        else:
            # No metric definition, use safe default
            agg_dict[col] = "sum"
    
    if not agg_dict:
        # No numeric columns to aggregate
        return df.drop(columns=child_dims).drop_duplicates()
    
    print(f"[Aggregation] Dimension roll-up: {' → '.join(child_dims)} → {parent_dim} (hierarchy: {hierarchy_name})")
    
    # Perform aggregation
    df_agg = df.groupby(group_cols, as_index=False).agg(agg_dict)
    
    return df_agg


def _get_metric_aggregation_methods(contract, df: pd.DataFrame, metric_col: str) -> Dict[str, str]:
    """Determine aggregation method (sum/mean/max) for each metric based on contract type.
    
    Aggregation logic:
    - Cumulative additive metrics (e.g., total_cases): max (take last value in period)
    - Incremental additive metrics (e.g., revenue): sum
    - Ratio/non-additive metrics (e.g., conversion_rate): mean
    """
    agg_methods = {}
    
    for metric in contract.metrics:
        metric_name = metric.name
        
        # Check if this is a cumulative metric
        is_cumulative = "cumulative" in [tag.lower() for tag in metric.tags]
        
        # Determine aggregation based on metric type
        if metric.type == "additive":
            if is_cumulative:
                # Cumulative additive: take max value (last observation in period)
                agg_methods[metric_name] = "max"
            else:
                # Incremental additive: sum
                agg_methods[metric_name] = "sum"
        elif metric.type in ["ratio", "non_additive"]:
            # Ratios and non-additive: average
            agg_methods[metric_name] = "mean"
        else:
            # Derived metrics: use sum as default
            agg_methods[metric_name] = "sum"
    
    return agg_methods


def load_from_config(
    dataset_name: str,
    *,
    csv_path: Optional[str] = None,
    dimension_filters: Optional[Dict[str, Any]] = None,
    metric_filter: Optional[Union[str, List[str]]] = None,
    metric_column: Optional[str] = None,
    exclude_partial_week: bool = False,
) -> pd.DataFrame:
    """Load data using declarative rules from config/datasets/<dataset_name>/loader.yaml.

    Args:
        dataset_name: Folder name in config/datasets/ (e.g. "validation_ops").
        csv_path: Optional override for the source file path.
        dimension_filters: Mapping of physical column -> value derived from the dataset contract.
        metric_filter: Substring or exact match on the metric identifier column (legacy behaviour).
        metric_column: Override for the metric identifier column name (defaults to loader.yaml or 'metric').
        exclude_partial_week: If True, drop dates defined in partial_period.known_dates.

    Returns:
        Standardized long-format DataFrame.
    """
    from config.dataset_resolver import get_dataset_dir
    dataset_dir = get_dataset_dir(dataset_name)
    loader_path = dataset_dir / "loader.yaml"
    
    if not loader_path.exists():
        raise FileNotFoundError(f"[config_data_loader] loader.yaml not found at {loader_path}")

    with open(loader_path, "r") as f:
        config = yaml.safe_load(f) or {}

    config = _normalize_loader_config(config)

    metric_col = metric_column or (config.get("metric_column") if isinstance(config, dict) else None) or "metric"

    # Resolve source file path
    project_root = _find_project_root()
    source_file = csv_path or config["source"]["file"]
    abs_csv_path = _resolve_csv_path(source_file, project_root)

    # --- CACHE: key includes dataset, path, partial_week flag, AND aggregation grain ---
    # This ensures we cache the aggregated version separately from raw data
    # Also include dimension_filters in cache key to cache different aggregation levels separately
    aggregation_grain = os.getenv("DATA_ANALYST_AGGREGATION_GRAIN", "auto")
    dimension_filters = dimension_filters or {}
    
    # Create hashable version of dimension_filters for cache key
    dim_filter_key = tuple(sorted(dimension_filters.items())) if dimension_filters else ()
    cache_key = (dataset_name, abs_csv_path, exclude_partial_week, aggregation_grain, dim_filter_key)
    
    if cache_key in _cache:
        full_df = _cache[cache_key]
    else:
        full_df = _perform_etl(abs_csv_path, config, exclude_partial_week)
        
        # --- INTELLIGENT AGGREGATION: Reduce row volume BEFORE caching ---
        # This dramatically improves performance on large datasets (2.5M → 356K rows)
        full_df = _aggregate_to_grain(full_df, dataset_name, config, dimension_filters)
        
        _cache[cache_key] = full_df
        print(f"[config_data_loader] Cached {dataset_name} data ({len(full_df):,} rows)")

    # --- Apply filters to the cached (possibly aggregated) long-format DF ---
    df = full_df.copy()
    dimension_filters = dimension_filters or {}

    for column, value in dimension_filters.items():
        if column not in df.columns:
            continue
        mask = (
            df[column]
            .astype(str)
            .str.strip()
            .str.lower()
            == str(value).strip().lower()
        )
        df = df[mask]
    if metric_filter and metric_col in df.columns:
        if isinstance(metric_filter, list):
            lower_list = [m.strip().lower() for m in metric_filter]
            mask = df[metric_col].astype(str).str.strip().str.lower().isin(lower_list)
        elif isinstance(metric_filter, str) and "," in metric_filter:
            lower_list = [m.strip().lower() for m in metric_filter.split(",")]
            mask = df[metric_col].astype(str).str.strip().str.lower().isin(lower_list)
        else:
            mask = df[metric_col].astype(str).str.strip().str.lower().str.contains(
                str(metric_filter).lower(), regex=False
            )
        df = df[mask]

    if df.empty:
        # Return empty DF with correct columns
        return pd.DataFrame(columns=config.get("output_columns", []))

    return df.reset_index(drop=True)


def _perform_etl(csv_path: str, config: Dict[str, Any], exclude_partial: bool) -> pd.DataFrame:
    """Core ETL pipeline defined by loader.yaml."""
    source_cfg = config["source"]
    
    # 1. Read
    df = pd.read_csv(
        csv_path,
        sep=source_cfg.get("delimiter", ","),
        dtype=str,
        encoding=source_cfg.get("encoding", "utf-8")
    )

    # 2. Wide-to-long Melt
    if source_cfg.get("format") == "wide":
        id_cols = config["id_columns"]
        melt_cfg = config["melt"]
        
        date_cols = [c for c in df.columns if c not in id_cols]
        
        # Partial period handling (before melt, like in validation_data_loader)
        if exclude_partial and "partial_period" in config:
            known_partial = config["partial_period"].get("known_dates", [])
            date_cols = [c for c in date_cols if c not in known_partial]
            df = df[id_cols + date_cols]

        df = df.melt(
            id_vars=id_cols,
            value_vars=date_cols,
            var_name=melt_cfg["var_name"],
            value_name=melt_cfg["value_name"],
        )

    # 3. Value Cleaning
    clean_cfg = config.get("value_cleaning", {})
    if clean_cfg:
        series = df[config["melt"]["value_name"]].astype(str)
        for char in clean_cfg.get("strip_characters", []):
            series = series.str.replace(char, "", regex=False)
        series = series.str.strip()
        
        # Map null markers
        null_map = {m: None for m in clean_cfg.get("null_markers", [])}
        series = series.replace(null_map)
        
        if clean_cfg.get("coerce") == "numeric":
            df["value"] = pd.to_numeric(series, errors="coerce")
        else:
            df["value"] = series

    # 4. Date Parsing
    date_cfg = config.get("date_parsing")
    if date_cfg:
        df[date_cfg["output_column"]] = (
            pd.to_datetime(df[date_cfg["source_column"]], format=date_cfg["input_format"], errors="coerce")
            .dt.strftime(date_cfg["output_format"])
        )
        # Drop source column only if it differs from output (avoid dropping the just-parsed column)
        if date_cfg["source_column"] != date_cfg["output_column"]:
            df = df.drop(columns=[date_cfg["source_column"]])
        df = df.dropna(subset=[date_cfg["output_column"]])

    # 5. Column Renaming
    if "column_mapping" in config:
        df = df.rename(columns=config["column_mapping"])

    # 6. Optional numeric coercion
    numeric_cols = config.get("numeric_columns", []) or []
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 7. Sort and final selection
    if "sort_columns" in config:
        df = df.sort_values(config["sort_columns"])
        
    if "output_columns" in config:
        df = df[config["output_columns"]]

    return df.reset_index(drop=True)


def _find_project_root() -> Path:
    """Walk up from this file to find pl_analyst/."""
    curr = Path(__file__).resolve()
    # current: pl_analyst/data_analyst_agent/tools/config_data_loader.py
    return curr.parent.parent.parent


def _resolve_csv_path(path_str: str, project_root: Path) -> str:
    """Resolve path relative to project root, with dataset-local priority.
    
    Prioritizes:
    1. Absolute paths
    2. File within the active dataset's config directory
    3. File relative to project root (legacy data/ folder)
    """
    path = Path(path_str)
    if path.is_absolute():
        return str(path)
    
    # Try dataset-local first
    from config.dataset_resolver import get_dataset_dir
    try:
        local_dir = get_dataset_dir()
        resolved = local_dir / path
        if resolved.exists():
            return str(resolved)
    except Exception:
        pass

    # Try relative to project root (Legacy)
    resolved = project_root / path
    if resolved.exists():
        return str(resolved)
    
    raise FileNotFoundError(f"[config_data_loader] CSV file not found: {path_str}")


def _normalize_loader_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure loader configs always expose a dict-like `source`."""

    if not isinstance(config, dict):
        raise ValueError("loader.yaml must deserialize into a mapping")

    raw_source = config.get("source") or {}
    if not isinstance(raw_source, dict):
        raw_source = {}

    legacy_keys = ("file", "encoding", "delimiter", "format")
    for key in legacy_keys:
        if key in config and key not in raw_source and config[key] is not None:
            raw_source[key] = config[key]

    if "file" not in raw_source or not raw_source["file"]:
        raise KeyError("loader.yaml is missing a source.file entry")

    config["source"] = raw_source
    return config
