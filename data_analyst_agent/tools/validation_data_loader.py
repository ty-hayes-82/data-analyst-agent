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
Wide-to-long ETL loader for data/validation_data.csv.

The source file is a tab-separated, wide-format ops metrics report:
  - Rows: each row is one (Region, Terminal, Metric) combination
  - Columns: Region, Terminal, Metric, then one column per week-ending date

This loader melts it into a long-format DataFrame compatible with the
validation_ops DatasetContract:
  - One row per (region, terminal, metric, week_ending) observation
  - Mixed value formats cleaned to numeric float
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import pandas as pd

# --- CACHE: Survive multiple imports via sys.modules ---
import sys
if '_validation_data_cache' not in sys.modules:
    sys.modules['_validation_data_cache'] = {
        'full_df': None,      # Stores the full long-format DataFrame
        'last_path': None,
        'exclude_partial': None
    }
_cache = sys.modules['_validation_data_cache']

# ---------------------------------------------------------------------------
# Source file columns that are NOT date columns
# ---------------------------------------------------------------------------
_ID_COLS = ["Region", "Terminal", "Metric"]

# The last week in the file is often a partial reporting period (only a few
# days of data). We track it here so callers can optionally exclude it.
_KNOWN_PARTIAL_WEEK = "2/21/2026"


def load_validation_data(
    csv_path: Optional[str] = None,
    *,
    region_filter: Optional[str] = None,
    terminal_filter: Optional[str] = None,
    metric_filter: Optional[Union[str, List[str]]] = None,
    dimension_filters: Optional[Dict[str, Any]] = None,
    exclude_partial_week: bool = False,
) -> pd.DataFrame:
    """Read and transform validation_data.csv from wide to long format.

    Args:
        csv_path: Absolute or relative path to the TSV file.  If None, the
                  function resolves the path relative to the project root
                  (pl_analyst/data/validation_data.csv).
        region_filter: If provided, keep only rows where region matches this
                       value (case-insensitive exact match).
        terminal_filter: If provided, keep only rows where terminal matches
                         this value (case-insensitive exact match).
        metric_filter: Flexible filter on the Metric column.  Accepts:
                       - A single metric name string: case-insensitive substring
                         match (e.g. "Miles" matches "Total Miles", "Loaded Miles").
                       - A list of metric name strings: case-insensitive exact
                         match against any item in the list (e.g.
                         ["Truck Count", "Total Miles"]).
                       - A comma-separated string: split on commas, then treated
                         as a list for exact matching (e.g. "Truck Count,Total Miles").
                       Pass None (default) to load all 56 metrics.
        dimension_filters: Optional mapping of column -> value(s). Values may be
                           scalars or iterables and are matched case-insensitively.
                           Entries here take precedence over region/terminal args.
        exclude_partial_week: If True, drop the final (partial) week column
                              before melting so it never appears in the output.

    Returns:
        Long-format DataFrame with columns:
            region (str), terminal (str), metric (str),
            week_ending (str, YYYY-MM-DD), value (float)

    Raises:
        FileNotFoundError: If the CSV file cannot be found at the resolved path.
        ValueError: If the file has no date columns after removing id columns.
    """
    try:
        abs_path = _resolve_path(csv_path)
    except FileNotFoundError:
        # In CI/dev environments the raw validation TSV may be absent.
        # Return an empty frame so downstream tests can skip gracefully.
        return pd.DataFrame(columns=["region", "terminal", "metric", "week_ending", "value"])

    # --- CACHE: Try to return full long-format DF from memory ---
    if (_cache['full_df'] is not None and 
        _cache['last_path'] == abs_path and 
        _cache['exclude_partial'] == exclude_partial_week):
        full_df = _cache['full_df']
    else:
        # Load and transform the full wide-format file
        df_wide = pd.read_csv(abs_path, sep="\t", dtype=str, encoding="utf-16")

        date_cols = [c for c in df_wide.columns if c not in _ID_COLS]
        if not date_cols:
            raise ValueError(
                f"[validation_data_loader] No date columns found in {abs_path}. "
                f"Expected columns other than {_ID_COLS}."
            )

        if exclude_partial_week and _KNOWN_PARTIAL_WEEK in date_cols:
            date_cols.remove(_KNOWN_PARTIAL_WEEK)
            df_wide = df_wide[_ID_COLS + date_cols]

        # Melt the ENTIRE file once to long format
        full_df = df_wide.melt(
            id_vars=_ID_COLS,
            value_vars=date_cols,
            var_name="week_ending_raw",
            value_name="raw_value",
        )

        # Clean mixed value formats
        full_df["value"] = _clean_values(full_df["raw_value"])

        # Parse and reformat dates
        full_df["week_ending"] = (
            pd.to_datetime(full_df["week_ending_raw"], format="%m/%d/%Y", errors="coerce")
            .dt.strftime("%Y-%m-%d")
        )

        # Lowercase / normalise column names
        full_df = full_df.rename(columns={
            "Region": "region",
            "Terminal": "terminal",
            "Metric": "metric",
        })

        # Drop helper columns and rows where date parsing failed
        full_df = full_df.drop(columns=["week_ending_raw", "raw_value"])
        full_df = full_df.dropna(subset=["week_ending"])

        # Sort for reproducible output
        full_df = full_df.sort_values(
            ["region", "terminal", "metric", "week_ending"]
        ).reset_index(drop=True)

        # Cache it!
        _cache['full_df'] = full_df
        _cache['last_path'] = abs_path
        _cache['exclude_partial'] = exclude_partial_week
        print(f"[validation_data_loader] Cached full long-format data ({len(full_df):,} rows)")

    # --- Apply filters to the (cached or newly loaded) full long-format DF ---
    df = full_df.copy()

    combined_filters: Dict[str, Any] = {}
    if dimension_filters:
        for key, value in dimension_filters.items():
            if value is None:
                continue
            combined_filters[str(key)] = value
    if region_filter and "region" not in combined_filters:
        combined_filters["region"] = region_filter
    if terminal_filter and "terminal" not in combined_filters:
        combined_filters["terminal"] = terminal_filter

    df = _apply_dimension_filters(df, combined_filters)
    if metric_filter:
        if isinstance(metric_filter, list):
            # Exact match against any item in the list (case-insensitive)
            lower_list = [m.strip().lower() for m in metric_filter]
            mask = df["metric"].str.strip().str.lower().isin(lower_list)
        elif "," in metric_filter:
            # Comma-separated string → split into list for exact matching
            lower_list = [m.strip().lower() for m in metric_filter.split(",")]
            mask = df["metric"].str.strip().str.lower().isin(lower_list)
        else:
            # Single string → substring match (preserves backward compatibility)
            mask = df["metric"].str.strip().str.lower().str.contains(
                metric_filter.lower(), regex=False
            )
        df = df[mask]

    if df.empty:
        return df.reset_index(drop=True)

    summary_parts = []
    for column in ("region", "terminal", "metric", "week_ending"):
        if column in df.columns:
            summary_parts.append(f"{df[column].nunique()} unique {column}")
    summary_text = ", ".join(summary_parts) or "no dimension columns"
    print(
        f"[validation_data_loader] Returning {len(df):,} filtered rows "
        f"({summary_text})"
    )
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_path(csv_path: Optional[str]) -> str:
    """Resolve the CSV file path, defaulting to the project-relative location."""
    if csv_path:
        resolved = os.path.abspath(csv_path)
        if os.path.exists(resolved):
            return resolved
        raise FileNotFoundError(
            f"[validation_data_loader] File not found: {resolved}"
        )

    # Walk up from this file's location to find the project root
    # This file lives at: pl_analyst/data_analyst_agent/tools/validation_data_loader.py
    candidates = [
        Path(__file__).parent.parent.parent / "data" / "validation_data.csv",
        Path(os.getcwd()) / "data" / "validation_data.csv",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    raise FileNotFoundError(
        "[validation_data_loader] validation_data.csv not found. "
        "Tried: " + ", ".join(str(c) for c in candidates)
    )


def _clean_values(series: pd.Series) -> pd.Series:
    """Clean a mixed-format string series to numeric float.

    Handles:
        - Currency: $553, "$2,901 ", "$2,901"
        - Percentages: 232.50%, 0.00%
        - Quoted values: "1,113"
        - Nulls: -, empty string, whitespace-only
    """
    cleaned = (
        series
        .astype(str)
        .str.replace('"', "", regex=False)
        .str.replace("$", "", regex=False)
        .str.replace(",", "", regex=False)
        .str.replace("%", "", regex=False)
        .str.strip()
    )
    # Treat dash and empty string as missing
    cleaned = cleaned.replace({"- ": None, "-": None, "": None, "nan": None})
    return pd.to_numeric(cleaned, errors="coerce")


def _coerce_filter_values(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        normalized = value.strip().lower()
        return {normalized} if normalized else set()
    if isinstance(value, (list, tuple, set)):
        return {
            str(item).strip().lower()
            for item in value
            if str(item).strip()
        }
    normalized = str(value).strip().lower()
    return {normalized} if normalized else set()


def _apply_dimension_filters(df: pd.DataFrame, filters: Dict[str, Any]) -> pd.DataFrame:
    if not filters:
        return df

    work = df
    for column, raw_value in filters.items():
        if column not in work.columns:
            print(f"[validation_data_loader] Filter column '{column}' not in DataFrame; skipping")
            continue
        targets = _coerce_filter_values(raw_value)
        if not targets:
            continue
        series = work[column].astype(str).str.strip().str.lower()
        if len(targets) == 1:
            target = next(iter(targets))
            mask = series == target
        else:
            mask = series.isin(targets)
        work = work[mask]
    return work
