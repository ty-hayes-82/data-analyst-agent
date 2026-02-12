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
Pure Python tool for complete statistical analysis at hierarchy levels.

This tool replaces 4 separate tools (get_validated_csv_from_state, aggregate_by_level,
rank_level_items_by_variance, identify_top_level_drivers) with a single efficient function.

ALL statistics are computed in Python (not LLM):
- Aggregation by hierarchy level
- YoY, MoM, QoQ, 3MMA, 6MMA variance calculations
- Ranking by absolute dollar variance
- Cumulative variance percentage
- Materiality threshold checks (category-specific when empirical mode enabled)

LLM receives ONLY top 5-10 items with pre-computed statistics (not full dataset).
"""

import json
import pandas as pd
from typing import Dict, Any, List, Optional
from pathlib import Path
from ...data_cache import get_validated_records, get_validated_csv
from config.materiality_loader import get_thresholds_for_category, get_global_defaults
from config.chart_loader import get_account_category


# Global default thresholds (used when category lookup fails)
_global_defaults = None
_chart_of_accounts = None


def _get_global_thresholds() -> tuple:
    """Get global default thresholds (cached)."""
    global _global_defaults
    if _global_defaults is None:
        defaults = get_global_defaults()
        _global_defaults = (defaults.get("variance_pct", 5.0), defaults.get("variance_dollar", 50000))
    return _global_defaults


def _load_chart_of_accounts() -> Dict[str, Any]:
    """Load and cache chart of accounts from config."""
    global _chart_of_accounts
    if _chart_of_accounts is None:
        # Find chart_of_accounts.json
        config_path = Path(__file__).parent.parent.parent.parent.parent / "config" / "chart_of_accounts.json"
        with open(config_path, 'r') as f:
            _chart_of_accounts = json.load(f)
    return _chart_of_accounts


def _get_account_hierarchy(gl_account: str) -> Optional[List[str]]:
    """Get hierarchy levels for a GL account from chart of accounts.
    
    Returns:
        List of [level_1, level_2, level_3, level_4] or None if not found
    """
    chart = _load_chart_of_accounts()
    account_info = chart.get("accounts", {}).get(gl_account)
    if account_info:
        return account_info.get("levels", [])
    return None


async def compute_level_statistics(
    level: int,
    analysis_period: str = "latest",
    variance_type: str = "yoy",
    top_n: int = 10,
    cumulative_threshold: float = 80.0,
    data_source: str = "pl",
    metric_name: str = "amount"
) -> str:
    """
    Compute complete statistical analysis for specified hierarchy level.

    This is a pure Python function that:
    1. Retrieves data from cache (not from LLM context)
    2. Aggregates by the specified hierarchy level
    3. Calculates all variances (YoY, MoM, etc.)
    4. Ranks items by absolute variance
    5. Computes cumulative variance percentages
    6. Identifies material items exceeding thresholds
    7. Returns ONLY top N items (default 10) with pre-computed stats

    Args:
        level: Hierarchy level to analyze (2, 3, or 4)
        analysis_period: Period to analyze ("latest" or "YYYY-MM")
        variance_type: Type of variance ("yoy", "mom", "qoq", "3mma", "6mma")
        top_n: Maximum number of items to return (default 10)
        cumulative_threshold: Return items explaining this % of variance (default 80%)
        data_source: "pl" for P&L data (default) or "ops" for ops metrics utilization
        metric_name: Column to analyze - "amount" for P&L, or ops metric like "miles_per_truck"
    
    Returns:
        JSON string with top N drivers and pre-calculated statistics:
        {
          "level": 2,
          "analysis_period": "2025-09",
          "variance_type": "yoy",
          "total_variance_dollar": -125000,
          "total_variance_pct": -4.5,
          "top_drivers": [
            {
              "rank": 1,
              "item": "Freight Revenue",
              "current": 2500000,
              "prior": 2800000,
              "variance_dollar": -300000,
              "variance_pct": -10.7,
              "cumulative_pct": 42.3,
              "exceeds_threshold": true,
              "threshold_met": ["dollar", "percentage"],
              "materiality": "HIGH"
            },
            ...
          ],
          "items_analyzed": 12,
          "items_returned": 5,
          "variance_explained_pct": 87.5,
          "summary": "Top 5 of 12 Level 2 items explain 87.5% of variance"
        }
    """
    try:
        # === Ops metrics data source ===
        if data_source == "ops":
            from ...data_cache import get_ops_metrics_csv
            ops_csv = get_ops_metrics_csv()
            if not ops_csv or ops_csv.strip() == "":
                return json.dumps({
                    "error": "NoOpsDataAvailable",
                    "message": "No ops metrics data found in cache.",
                    "level": level
                })
            from io import StringIO as _SIO
            ops_df = pd.read_csv(_SIO(ops_csv))
            ops_df['value'] = pd.to_numeric(ops_df['value'], errors='coerce').fillna(0)

            # Load ops hierarchy config
            try:
                from config.ratios_config_loader import get_ops_hierarchy
                ops_hierarchy = get_ops_hierarchy()
            except Exception:
                ops_hierarchy = {"level_2": "location", "level_3": "lob"}

            # For ops data, the hierarchy is by location (level_2) and LOB (level_3)
            # We pivot the data to get the metric_name as the value column
            # First, filter to the requested metric if it exists in metric_name
            if metric_name != "amount" and "metric_name" in ops_df.columns:
                metric_df = ops_df[ops_df["metric_name"].str.lower().str.contains(metric_name.lower().replace("_", " "))]
                if metric_df.empty:
                    metric_df = ops_df  # fall back to all data
            else:
                metric_df = ops_df

            # For ops hierarchy, use location/cost_center column as grouping
            ops_level_col = None
            if level == 2:
                ops_level_col = ops_hierarchy.get("level_2", "location")
            elif level == 3:
                ops_level_col = ops_hierarchy.get("level_3", "lob")

            if ops_level_col and ops_level_col in metric_df.columns:
                # Aggregate by ops hierarchy level
                agg = metric_df.groupby(["period", ops_level_col])["value"].sum().reset_index()
                agg.columns = ["period", "item", "amount"]
                df = agg
                level_col = "item"
            else:
                # Fall back to metric_name as grouping
                agg = metric_df.groupby(["period", "metric_name"])["value"].sum().reset_index()
                agg.columns = ["period", "item", "amount"]
                df = agg
                level_col = "item"

            # Skip the P&L hierarchy enrichment for ops data
            # Jump directly to period analysis
            if "period_date" not in df.columns:
                df["period_date"] = pd.to_datetime(df["period"], errors="coerce")
                df = df.sort_values("period_date")

            # Determine analysis period
            if analysis_period == "latest":
                periods = sorted(df["period"].unique())
                current_period = periods[-1]
            else:
                current_period = analysis_period

            current_df = df[df["period"] == current_period].copy()
            if current_df.empty:
                return json.dumps({"error": "PeriodNotFound", "message": f"Period {current_period} not found", "level": level})

            current_agg = current_df.groupby("item")["amount"].sum().reset_index()
            current_agg.columns = ["item", "current"]

            # Prior period
            current_date = pd.to_datetime(current_period)
            if variance_type == "yoy":
                prior_date = current_date - pd.DateOffset(years=1)
            elif variance_type == "mom":
                prior_date = current_date - pd.DateOffset(months=1)
            elif variance_type == "qoq":
                prior_date = current_date - pd.DateOffset(months=3)
            else:
                prior_date = current_date - pd.DateOffset(years=1)

            prior_period_str = prior_date.strftime("%Y-%m")
            prior_df = df[df["period"] == prior_period_str].copy()
            prior_agg = prior_df.groupby("item")["amount"].sum().reset_index()
            prior_agg.columns = ["item", "prior"]

            merged = current_agg.merge(prior_agg, on="item", how="outer").fillna(0)
            merged["variance_dollar"] = merged["current"] - merged["prior"]
            merged["variance_pct"] = ((merged["current"] - merged["prior"]) / merged["prior"].abs()) * 100
            merged["variance_pct"] = merged["variance_pct"].replace([float('inf'), -float('inf')], 0)

            # Materiality for ops: use ops config thresholds
            try:
                from config.ratios_config_loader import get_ops_metric_thresholds
                thresholds = get_ops_metric_thresholds(metric_name)
                pct_threshold = thresholds.get("degradation_pct", 5.0)
            except Exception:
                pct_threshold = 5.0

            merged["exceeds_threshold"] = merged["variance_pct"].abs() >= pct_threshold
            merged["threshold_met"] = merged.apply(
                lambda r: (["percentage"] if abs(r["variance_pct"]) >= pct_threshold else []), axis=1
            )
            merged["materiality"] = merged["exceeds_threshold"].apply(
                lambda x: "HIGH" if x else "LOW"
            )

            merged = merged.sort_values("variance_dollar", key=lambda x: x.abs(), ascending=False)
            total_variance = merged["variance_dollar"].abs().sum()
            merged["abs_variance"] = merged["variance_dollar"].abs()
            merged["cumulative_variance"] = merged["abs_variance"].cumsum()
            merged["cumulative_pct"] = (merged["cumulative_variance"] / total_variance * 100) if total_variance > 0 else 0
            merged["rank"] = range(1, len(merged) + 1)

            top_items = merged.head(top_n)
            top_drivers = []
            for _, row in top_items.iterrows():
                top_drivers.append({
                    "rank": int(row["rank"]),
                    "item": str(row["item"]),
                    "current": float(row["current"]),
                    "prior": float(row["prior"]),
                    "variance_dollar": float(row["variance_dollar"]),
                    "variance_pct": float(row["variance_pct"]),
                    "cumulative_pct": float(row["cumulative_pct"]),
                    "exceeds_threshold": bool(row["exceeds_threshold"]),
                    "threshold_met": row["threshold_met"],
                    "materiality": row["materiality"],
                })

            variance_explained = float(top_items["cumulative_pct"].iloc[-1]) if not top_items.empty else 0
            return json.dumps({
                "level": level,
                "level_name": f"Ops Level {level}",
                "data_source": "ops",
                "metric": metric_name,
                "analysis_period": current_period,
                "variance_type": variance_type.upper(),
                "total_variance_dollar": float(merged["variance_dollar"].sum()),
                "total_variance_pct": float(merged["variance_pct"].mean()),
                "top_drivers": top_drivers,
                "items_analyzed": len(merged),
                "items_returned": len(top_items),
                "variance_explained_pct": variance_explained,
                "summary": f"Top {len(top_items)} of {len(merged)} ops Level {level} items explain {variance_explained:.1f}% of variance"
            }, indent=2)

        # === P&L data source (original logic) ===
        # Get data from cache (NOT from LLM)
        records = get_validated_records()

        if records:
            # Convert records (structured cache) to DataFrame
            df = pd.DataFrame(records)
        else:
            # Fallback: Parse CSV from legacy cache to avoid building large in-memory dict
            csv_data = get_validated_csv()
            if not csv_data or csv_data.strip() == "":
                return json.dumps({
                    "error": "NoDataAvailable",
                    "message": "No validated data found in cache. Ensure data_validation_agent ran successfully.",
                    "level": level
                })
            # Parse CSV string directly
            from io import StringIO
            df = pd.read_csv(StringIO(csv_data))
        
        # Enrich dataframe with hierarchy levels from chart of accounts
        # This ensures we use the authoritative hierarchy, not potentially duplicate CSV columns
        def enrich_with_hierarchy(row):
            """Add hierarchy levels from chart of accounts."""
            gl_account = row.get("gl_account")
            if pd.notna(gl_account):
                hierarchy = _get_account_hierarchy(str(gl_account))
                if hierarchy:
                    return pd.Series({
                        'coa_level_1': hierarchy[0] if len(hierarchy) > 0 else None,
                        'coa_level_2': hierarchy[1] if len(hierarchy) > 1 else None,
                        'coa_level_3': hierarchy[2] if len(hierarchy) > 2 else None,
                        'coa_level_4': hierarchy[3] if len(hierarchy) > 3 else None
                    })
            return pd.Series({
                'coa_level_1': None,
                'coa_level_2': None,
                'coa_level_3': None,
                'coa_level_4': None
            })
        
        # Apply hierarchy enrichment
        hierarchy_cols = df.apply(enrich_with_hierarchy, axis=1)
        df = pd.concat([df, hierarchy_cols], axis=1)
        
        # Determine grouping column based on level
        # Check for duplicate levels first (using chart of accounts hierarchy)
        # This is critical: if Level 4 is identical to Level 3, we should skip Level 4 analysis
        # and go straight to GL account detail (Level 5)
        if level > 2 and level <= 4:  # Check levels 3 and 4 for duplicates
            level_col_check = f"coa_level_{level}"
            parent_level_col = f"coa_level_{level - 1}"
            
            if level_col_check in df.columns and parent_level_col in df.columns:
                current_unique = set(df[level_col_check].dropna().unique())
                parent_unique = set(df[parent_level_col].dropna().unique())
                
                if current_unique == parent_unique:
                    # This level is redundant - same as parent, skip it
                    print(f"[compute_level_statistics] Level {level} is duplicate of Level {level-1} - skipping")
                    return json.dumps({
                        "level": level,
                        "is_duplicate": True,
                        "duplicate_of": level - 1,
                        "message": f"Level {level} is identical to Level {level - 1} - skipping to next level",
                        "recommendation": "SKIP_TO_NEXT",
                        "items_analyzed": 0,
                        "items_returned": 0
                    })
        
        # Now determine the actual grouping column
        # Level 4 uses coa_level_4 (if not duplicate), Level 5+ uses GL account
        if level >= 5:
            level_col = "gl_account"
            if level_col not in df.columns:
                return json.dumps({
                    "error": "InvalidLevel",
                    "message": f"GL account column not found in data. Available columns: {list(df.columns)}",
                    "level": level
                })
        else:
            # Use chart of accounts hierarchy columns (levels 2, 3, 4)
            level_col = f"coa_level_{level}"
            if level_col not in df.columns:
                return json.dumps({
                    "error": "InvalidLevel",
                    "message": f"Hierarchy level {level} not found in chart of accounts enrichment. Available columns: {list(df.columns)}",
                    "level": level
                })
        
        # Determine analysis period
        if analysis_period == "latest":
            periods = sorted(df["period"].unique())
            current_period = periods[-1]
        else:
            current_period = analysis_period
        
        # Aggregate by hierarchy level for current and prior periods
        df["period_date"] = pd.to_datetime(df["period"])
        df = df.sort_values("period_date")
        
        # Get current period data
        current_df = df[df["period"] == current_period].copy()
        
        if current_df.empty:
            return json.dumps({
                "error": "PeriodNotFound",
                "message": f"Period {current_period} not found in data",
                "level": level
            })
        
        # Aggregate current period by level
        current_agg = current_df.groupby(level_col)["amount"].sum().reset_index()
        current_agg.columns = ["item", "current"]
        
        # For Level 4 (GL accounts), add account_name from chart of accounts
        if level == 4:
            chart = _load_chart_of_accounts()
            account_name_map = {
                acc: info.get("name", acc) 
                for acc, info in chart.get("accounts", {}).items()
            }
            current_agg["account_name"] = current_agg["item"].map(account_name_map).fillna(current_agg["item"])
        
        # Calculate prior period based on variance type
        current_date = pd.to_datetime(current_period)
        
        if variance_type == "yoy":
            prior_date = current_date - pd.DateOffset(years=1)
        elif variance_type == "mom":
            prior_date = current_date - pd.DateOffset(months=1)
        elif variance_type == "qoq":
            prior_date = current_date - pd.DateOffset(months=3)
        elif variance_type == "3mma":
            # 3-month moving average: compare current to avg of prior 3 months
            prior_periods = [current_date - pd.DateOffset(months=i) for i in range(1, 4)]
            prior_date = None  # Special handling below
        elif variance_type == "6mma":
            # 6-month moving average
            prior_periods = [current_date - pd.DateOffset(months=i) for i in range(1, 7)]
            prior_date = None
        else:
            prior_date = current_date - pd.DateOffset(years=1)  # Default to YoY
        
        # Get prior period data
        if variance_type in ["3mma", "6mma"]:
            prior_periods_str = [p.strftime("%Y-%m") for p in prior_periods]
            prior_df = df[df["period"].isin(prior_periods_str)].copy()
            prior_agg = prior_df.groupby(level_col)["amount"].sum().reset_index()
            prior_agg["prior"] = prior_agg["amount"] / len(prior_periods_str)  # Average
            prior_agg = prior_agg[[level_col, "prior"]]
            prior_agg.columns = ["item", "prior"]
        else:
            prior_period_str = prior_date.strftime("%Y-%m")
            prior_df = df[df["period"] == prior_period_str].copy()
            prior_agg = prior_df.groupby(level_col)["amount"].sum().reset_index()
            prior_agg.columns = ["item", "prior"]
        
        # Merge current and prior
        merged = current_agg.merge(prior_agg, on="item", how="outer").fillna(0)
        
        # Calculate variances
        merged["variance_dollar"] = merged["current"] - merged["prior"]
        merged["variance_pct"] = ((merged["current"] - merged["prior"]) / merged["prior"].abs()) * 100
        merged["variance_pct"] = merged["variance_pct"].replace([float('inf'), -float('inf')], 0)
        
        # Check materiality thresholds (category-specific or global)
        # Try to determine category for level items to use category-specific thresholds
        def get_item_thresholds(item_name):
            """Get thresholds for a level item by checking its accounts' categories."""
            # Get accounts in this level item
            item_accounts = df[df[level_col] == item_name]["gl_account"].unique()
            
            if len(item_accounts) > 0:
                # Get category of first account (usually all in same category at given level)
                category = get_account_category(item_accounts[0])
                if category:
                    return get_thresholds_for_category(category)
            
            # Fall back to global defaults
            return _get_global_thresholds()
        
        # Apply thresholds per item
        for idx, row in merged.iterrows():
            pct_threshold, dollar_threshold = get_item_thresholds(row["item"])
            merged.at[idx, "exceeds_dollar"] = abs(row["variance_dollar"]) >= dollar_threshold
            merged.at[idx, "exceeds_pct"] = abs(row["variance_pct"]) >= pct_threshold
        
        merged["exceeds_threshold"] = merged["exceeds_dollar"] | merged["exceeds_pct"]
        
        # Build threshold_met list
        def get_thresholds_met(row):
            thresholds = []
            if row["exceeds_dollar"]:
                thresholds.append("dollar")
            if row["exceeds_pct"]:
                thresholds.append("percentage")
            return thresholds
        
        merged["threshold_met"] = merged.apply(get_thresholds_met, axis=1)
        
        # Assign materiality level
        def get_materiality(row):
            if row["exceeds_dollar"] and row["exceeds_pct"]:
                return "HIGH"
            elif row["exceeds_dollar"] or row["exceeds_pct"]:
                return "MEDIUM"
            else:
                return "LOW"
        
        merged["materiality"] = merged.apply(get_materiality, axis=1)
        
        # Sort by absolute variance (descending)
        merged = merged.sort_values("variance_dollar", key=lambda x: x.abs(), ascending=False)
        
        # Calculate cumulative variance percentage
        total_variance = merged["variance_dollar"].abs().sum()
        merged["abs_variance"] = merged["variance_dollar"].abs()
        merged["cumulative_variance"] = merged["abs_variance"].cumsum()
        merged["cumulative_pct"] = (merged["cumulative_variance"] / total_variance * 100) if total_variance > 0 else 0
        
        # Rank
        merged["rank"] = range(1, len(merged) + 1)
        
        # Select top N or items explaining cumulative_threshold% of variance
        top_items = merged.head(top_n)
        
        # Also include items until we reach cumulative threshold
        threshold_items = merged[merged["cumulative_pct"] <= cumulative_threshold]
        if len(threshold_items) > len(top_items):
            top_items = threshold_items
        
        # Ensure we return at least top_n items
        if len(top_items) < top_n and len(merged) >= top_n:
            top_items = merged.head(top_n)
        
        # Build response
        top_drivers = []
        for _, row in top_items.iterrows():
            top_drivers.append({
                "rank": int(row["rank"]),
                "item": str(row["item"]),
                "current": float(row["current"]),
                "prior": float(row["prior"]),
                "variance_dollar": float(row["variance_dollar"]),
                "variance_pct": float(row["variance_pct"]),
                "cumulative_pct": float(row["cumulative_pct"]),
                "exceeds_threshold": bool(row["exceeds_threshold"]),
                "threshold_met": row["threshold_met"],
                "materiality": row["materiality"]
            })
        
        # Calculate summary statistics
        variance_explained = float(top_items["cumulative_pct"].iloc[-1]) if not top_items.empty else 0
        total_variance_dollar = float(merged["variance_dollar"].sum())
        total_current = float(merged["current"].sum())
        total_prior = float(merged["prior"].sum())
        total_variance_pct = ((total_current - total_prior) / abs(total_prior) * 100) if total_prior != 0 else 0
        
        result = {
            "level": level,
            "level_name": f"Level {level}",
            "analysis_period": current_period,
            "variance_type": variance_type.upper(),
            "total_current": total_current,
            "total_prior": total_prior,
            "total_variance_dollar": total_variance_dollar,
            "total_variance_pct": float(total_variance_pct),
            "top_drivers": top_drivers,
            "items_analyzed": len(merged),
            "items_returned": len(top_items),
            "variance_explained_pct": variance_explained,
            "summary": f"Top {len(top_items)} of {len(merged)} Level {level} items explain {variance_explained:.1f}% of variance"
        }
        
        return json.dumps(result, indent=2)
        
    except Exception as e:
        return json.dumps({
            "error": "ComputationFailed",
            "message": f"Failed to compute level statistics: {str(e)}",
            "level": level,
            "details": str(e)
        })

