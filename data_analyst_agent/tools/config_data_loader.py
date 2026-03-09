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


def load_from_config(
    dataset_name: str,
    *,
    csv_path: Optional[str] = None,
    region_filter: Optional[str] = None,
    terminal_filter: Optional[str] = None,
    metric_filter: Optional[Union[str, List[str]]] = None,
    exclude_partial_week: bool = False,
) -> pd.DataFrame:
    """Load data using declarative rules from config/datasets/<dataset_name>/loader.yaml.

    Args:
        dataset_name: Folder name in config/datasets/ (e.g. "validation_ops").
        csv_path: Optional override for the source file path.
        region_filter: Exact match on region (case-insensitive).
        terminal_filter: Exact match on terminal (case-insensitive).
        metric_filter: Substring or exact match on metric (matches validation_data_loader logic).
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
        config = yaml.safe_load(f)

    # Resolve source file path
    project_root = _find_project_root()
    source_file = csv_path or config["source"]["file"]
    abs_csv_path = _resolve_csv_path(source_file, project_root)

    # --- CACHE: key includes dataset, path, and partial_week flag ---
    cache_key = (dataset_name, abs_csv_path, exclude_partial_week)
    if cache_key in _cache:
        full_df = _cache[cache_key]
    else:
        full_df = _perform_etl(abs_csv_path, config, exclude_partial_week)
        _cache[cache_key] = full_df
        print(f"[config_data_loader] Cached {dataset_name} data ({len(full_df):,} rows)")

    # --- Apply filters to the cached full long-format DF ---
    df = full_df.copy()

    if region_filter:
        mask = df["region"].str.strip().str.lower() == region_filter.lower()
        df = df[mask]
    if terminal_filter:
        mask = df["terminal"].str.strip().str.lower() == terminal_filter.lower()
        df = df[mask]
    if metric_filter:
        if isinstance(metric_filter, list):
            lower_list = [m.strip().lower() for m in metric_filter]
            mask = df["metric"].str.strip().str.lower().isin(lower_list)
        elif "," in metric_filter:
            lower_list = [m.strip().lower() for m in metric_filter.split(",")]
            mask = df["metric"].str.strip().str.lower().isin(lower_list)
        else:
            mask = df["metric"].str.strip().str.lower().str.contains(
                metric_filter.lower(), regex=False
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
        # Drop helper column and rows with failed date parsing
        df = df.drop(columns=[date_cfg["source_column"]])
        df = df.dropna(subset=[date_cfg["output_column"]])

    # 5. Column Renaming
    if "column_mapping" in config:
        df = df.rename(columns=config["column_mapping"])

    # 6. Sort and final selection
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
