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
Generic statistical analysis tool for recursive hierarchy decomposition.

This tool is domain-agnostic and uses the hierarchies defined in the 
DatasetContract to perform multi-level variance analysis.
"""

import json
import pandas as pd
import os
from typing import Dict, Any, List, Optional
from pathlib import Path
from data_analyst_agent.sub_agents.data_cache import (
    get_analysis_context,
    resolve_data_and_columns,
)
from data_analyst_agent.semantic.lag_utils import (
    get_effective_lag_or_default,
    resolve_effective_latest_period,
)
from config.materiality_loader import get_thresholds_for_category, get_global_defaults


def _get_materiality_thresholds(ctx) -> tuple:
    """Get thresholds from contract, falling back to global defaults."""
    pct_threshold = 5.0
    dollar_threshold = 50000.0

    if ctx and ctx.contract:
        materiality = getattr(ctx.contract, 'materiality', {})
        pct_threshold = materiality.get("variance_pct", pct_threshold)
        dollar_threshold = materiality.get("variance_absolute", dollar_threshold)
    else:
        try:
            defaults = get_global_defaults()
            pct_threshold = defaults.get("variance_pct", pct_threshold)
            dollar_threshold = defaults.get("variance_dollar", dollar_threshold)
        except Exception:
            pass
            
    return pct_threshold, dollar_threshold


async def compute_level_statistics_impl(
    level: int,
    analysis_period: str = "latest",
    variance_type: str = "yoy",
    top_n: int = 10,
    cumulative_threshold: float = 80.0,
    hierarchy_name: Optional[str] = None
) -> str:
    """
    Compute statistical analysis for a specific level in the hierarchy.

    Args:
        level: The index of the dimension in the hierarchy list (0-based).
        analysis_period: Period to analyze ("latest" or "YYYY-MM").
        variance_type: Type of variance ("yoy", "mom", "qoq", "3mma", "6mma").
        top_n: Maximum number of items to return.
        cumulative_threshold: Return items explaining this % of variance.
        hierarchy_name: Optional name of the hierarchy to use from the contract.
    """
    try:
        # 1. Get data and context
        try:
            df, time_col, metric_col, grain_col, name_col, ctx = resolve_data_and_columns("LevelStatistics")
        except ValueError as e:
            return json.dumps({"error": "ContextNotFound", "message": str(e), "level": level})

        if not ctx or not ctx.contract:
            return json.dumps({"error": "ContractNotFound", "message": "No semantic contract found.", "level": level})

        # 2. Determine grouping dimension
        # Use the first hierarchy if none specified
        hierarchies = ctx.contract.hierarchies
        if not hierarchies:
            # Fallback to grain if no hierarchies defined
            level_col = grain_col
            level_name = "Grain"
            is_last_level = True
        else:
            selected_hierarchy = next((h for h in hierarchies if h.name == hierarchy_name), hierarchies[0])
            dimensions = selected_hierarchy.children
            level_names = getattr(selected_hierarchy, 'level_names', {})
            
            if level == 0:
                # Level 0 is special: Top-level aggregation (Total)
                level_col = "_total_agg"
                df["_total_agg"] = "Total"
                level_name = level_names.get(0, "Total")
                is_last_level = False
            elif level <= len(dimensions):
                # Level 1-N corresponds to children[0-N-1]
                semantic_name = dimensions[level-1]
                level_name = level_names.get(level, semantic_name)
                
                # Resolve semantic name -> physical column
                try:
                    dim = ctx.contract.get_dimension(semantic_name)
                    level_col = dim.column
                except KeyError:
                    # Fallback to semantic name as column if not in dimensions
                    level_col = semantic_name
                
                is_last_level = (level == len(dimensions))
            else:
                # Beyond hierarchy depth, use grain
                level_col = grain_col
                level_name = "Detail"
                is_last_level = True

        # Ensure level_col exists in data
        if level_col not in df.columns:
            return json.dumps({
                "error": "InvalidDimension",
                "message": f"Column '{level_col}' (for dimension '{level_name}') not found in data. Available columns: {list(df.columns)}",
                "level": level
            })

        # 3. Period Analysis
        periods = sorted(df[time_col].unique())
        lag = get_effective_lag_or_default(ctx.contract, ctx.target_metric) if ctx and ctx.contract and ctx.target_metric else 0
        
        effective_current, lag_window = resolve_effective_latest_period(periods, lag)
        
        if analysis_period == "latest":
            current_period = effective_current
        else:
            current_period = analysis_period

        # Special mode: year-over-year by full-year totals (used by insight-quality E2E)
        import re
        if variance_type.lower() == "yoy" and re.fullmatch(r"\d{4}", str(current_period)):
            current_year = int(current_period)
            prior_year = current_year - 1

            if "year" not in df.columns:
                df["year"] = pd.to_datetime(df[time_col], errors="coerce").dt.year

            cur = df[df["year"] == current_year].copy()
            pri = df[df["year"] == prior_year].copy()

            if cur.empty or pri.empty:
                return json.dumps({"error": "YearNotFound", "message": f"Year {current_year} or {prior_year} not found.", "level": level})

            cur_grp = cur.groupby(level_col)[metric_col].sum()
            pri_grp = pri.groupby(level_col)[metric_col].sum()

            drivers = []
            for item, cur_val in cur_grp.items():
                prior_val = float(pri_grp.get(item, 0.0))
                cur_val = float(cur_val)
                var_d = cur_val - prior_val
                var_pct = (var_d / prior_val * 100.0) if prior_val else 0.0
                drivers.append({
                    "item": str(item),
                    "current": cur_val,
                    "prior": prior_val,
                    "variance_dollar": var_d,
                    "variance_pct": var_pct,
                })

            drivers.sort(key=lambda d: abs(d.get("variance_dollar", 0.0)), reverse=True)

            total_var = sum(d["variance_dollar"] for d in drivers)
            # Keep existing schema shape
            return json.dumps(
                {
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
                },
                indent=2,
            )

        # 4 & 5. Prior period for variance
        current_date = pd.to_datetime(current_period)
        if variance_type.lower() == "yoy":
            prior_date = current_date - pd.DateOffset(years=1)
        elif variance_type.lower() == "mom":
            prior_date = current_date - pd.DateOffset(months=1)
        elif variance_type.lower() == "qoq":
            prior_date = current_date - pd.DateOffset(months=3)
        else:
            prior_date = current_date - pd.DateOffset(years=1)
        
        # Resolve best prior period string from data
        all_periods = sorted(pd.to_datetime(df[time_col].unique()))
        # Find the period in all_periods that is closest to prior_date
        if all_periods:
            best_prior = min(all_periods, key=lambda d: abs(d - prior_date))
            # Only use it if it's within a reasonable range (e.g. 7 days for weekly data)
            if abs((best_prior - prior_date).days) <= 7:
                prior_period_str = best_prior.strftime(ctx.contract.time.format)
            else:
                prior_period_str = prior_date.strftime(ctx.contract.time.format)
        else:
            prior_period_str = prior_date.strftime(ctx.contract.time.format)

        # 4. Aggregation (aggregate-then-derive for ratio metrics)
        df[time_col] = df[time_col].astype(str)
        
        # Robust metric name resolution
        current_metric_name = None
        if "metric" in df.columns:
            u_metrics = [str(m).strip() for m in df["metric"].unique() if m]
            if len(u_metrics) == 1:
                current_metric_name = u_metrics[0]
            elif ctx and ctx.target_metric and ctx.target_metric.name in u_metrics:
                current_metric_name = ctx.target_metric.name
            else:
                # If target_metric.name is generic (e.g. "value"), try to find if any unique metric is a ratio
                try:
                    from data_analyst_agent.sub_agents.statistical_insights_agent.tools.ratio_metrics_config import get_ratio_config_for_metric
                    for m in u_metrics:
                        if get_ratio_config_for_metric(ctx.contract, m):
                            current_metric_name = m
                            break
                except Exception:
                    pass
        
        if not current_metric_name and ctx and ctx.target_metric:
            current_metric_name = ctx.target_metric.name

        # If we identified a specific metric name, filter the dataframe to isolate it.
        # This prevents summing multiple metrics if they were loaded into the same dataframe.
        if current_metric_name and "metric" in df.columns and df["metric"].nunique() > 1:
            if current_metric_name in [str(m).strip() for m in df["metric"].unique()]:
                df = df[df["metric"].str.strip() == current_metric_name].copy()

        current_df = df[df[time_col] == current_period].copy()
        if current_df.empty:
            return json.dumps({"error": "PeriodNotFound", "message": f"Period {current_period} not found.", "level": level})
        prior_df = df[df[time_col] == prior_period_str].copy()

        ratio_config = None
        _network_variance: Optional[float] = None
        if current_metric_name:
            try:
                from data_analyst_agent.sub_agents.statistical_insights_agent.tools.ratio_metrics_config import get_ratio_config_for_metric
                ratio_config = get_ratio_config_for_metric(ctx.contract, current_metric_name)
            except Exception:
                pass
        if ratio_config and level_col in df.columns:
            try:
                num_metric = ratio_config.get("numerator_metric")
                denom_metric = ratio_config.get("denominator_metric")
                
                # Use data from context if columns are already present (WIDE format)
                # NEVER use validation_data.csv fallback for Tableau/ops_metrics - that mixes
                # data from a different source (validation CSV) with the analysis context.
                is_tableau = (
                    ctx.contract
                    and getattr(ctx.contract, "data_source", None)
                    and getattr(ctx.contract.data_source, "type", None) == "tableau_hyper"
                )
                if is_tableau and (num_metric not in df.columns or denom_metric not in df.columns):
                    print(
                        f"[compute_level_statistics] WARNING: Tableau dataset but missing ratio columns "
                        f"({num_metric!r}, {denom_metric!r}). df.columns={list(df.columns)[:15]}... "
                        "Skipping ratio aggregation; using simple sum (may be incorrect for ratio metrics)."
                    )
                    ratio_config = None
                elif num_metric in df.columns and denom_metric in df.columns:
                    # WIDE format: use context df (Tableau/ops_metrics)
                    nd_df = df.copy()
                    tcol = time_col
                    gcol = grain_col
                    nd_df[tcol] = nd_df[tcol].astype(str)
                    
                    # Convert to numeric
                    numeric_cols = [num_metric, denom_metric]
                    for extra_col in ["truck_count", "days_in_period"]:
                        if extra_col in nd_df.columns:
                            numeric_cols.append(extra_col)
                    for col in sorted(set(numeric_cols)):
                        nd_df[col] = pd.to_numeric(nd_df[col], errors="coerce").fillna(0)

                    use_network_truck_denominator = (
                        denom_metric == "Truck Count"
                        and "truck_count" in nd_df.columns
                        and "days_in_period" in nd_df.columns
                    )

                    def _effective_denom_by_group(sub_df, group_key):
                        if use_network_truck_denominator:
                            # De-duplicate truck_count at terminal grain to avoid
                            # overcounting from auxiliary splits (driver/fleet/cost center).
                            if "terminal" in sub_df.columns:
                                if group_key == "terminal":
                                    dedup = sub_df.groupby([group_key], dropna=False).agg(
                                        truck_total=("truck_count", "max"),
                                        days_max=("days_in_period", "max"),
                                    ).reset_index()
                                else:
                                    dedup = sub_df.groupby([group_key, "terminal"], dropna=False).agg(
                                        truck_total=("truck_count", "max"),
                                        days_max=("days_in_period", "max"),
                                    ).reset_index()
                                truck_s = dedup.groupby(group_key)["truck_total"].sum()
                                days_s = dedup.groupby(group_key)["days_max"].max().replace(0, float("nan"))
                                return truck_s / days_s
                            truck_s = sub_df.groupby(group_key)["truck_count"].sum()
                            days_s = sub_df.groupby(group_key)["days_in_period"].max().replace(0, float("nan"))
                            return truck_s / days_s
                        return sub_df.groupby(group_key)[denom_metric].sum()

                    def _effective_denom_total(sub_df):
                        if use_network_truck_denominator:
                            if "terminal" in sub_df.columns:
                                dedup = sub_df.groupby("terminal", dropna=False).agg(
                                    truck_total=("truck_count", "max"),
                                    days_max=("days_in_period", "max"),
                                )
                                days = float(dedup["days_max"].max()) if not dedup.empty else 0.0
                                return (float(dedup["truck_total"].sum()) / days) if days > 0 else 0.0
                            days = float(sub_df["days_in_period"].max()) if not sub_df.empty else 0.0
                            return (float(sub_df["truck_count"].sum()) / days) if days > 0 else 0.0
                        return float(sub_df[denom_metric].sum())
                    
                    # Compute network total denominator per period
                    if use_network_truck_denominator and "terminal" in nd_df.columns:
                        _period_terminal = nd_df.groupby([tcol, "terminal"], dropna=False).agg(
                            truck_total=("truck_count", "max"),
                            days_max=("days_in_period", "max"),
                        ).reset_index()
                        _period_totals = _period_terminal.groupby(tcol).agg(
                            truck_total=("truck_total", "sum"),
                            days_max=("days_max", "max"),
                        )
                        net_denom = _period_totals["truck_total"] / _period_totals["days_max"].replace(0, float("nan"))
                    elif use_network_truck_denominator:
                        _period_totals = nd_df.groupby(tcol).agg(
                            truck_total=("truck_count", "sum"),
                            days_max=("days_in_period", "max"),
                        )
                        net_denom = _period_totals["truck_total"] / _period_totals["days_max"].replace(0, float("nan"))
                    else:
                        net_denom = nd_df.groupby(tcol)[denom_metric].sum()
                    
                    # Materiality filter
                    min_share = ratio_config.get("materiality_min_share")
                    if min_share is not None and min_share > 0:
                        # Use level_col for share if it's not the total aggregate
                        m_col = level_col if level_col != "_total_agg" else gcol
                        if use_network_truck_denominator and "terminal" in nd_df.columns:
                            if m_col == "terminal":
                                _grain_totals = nd_df.groupby([tcol, m_col], dropna=False).agg(
                                    truck_total=("truck_count", "max"),
                                    days_max=("days_in_period", "max"),
                                )
                                grain_denom = _grain_totals["truck_total"] / _grain_totals["days_max"].replace(0, float("nan"))
                            else:
                                _grain_terminal = nd_df.groupby([tcol, m_col, "terminal"], dropna=False).agg(
                                    truck_total=("truck_count", "max"),
                                    days_max=("days_in_period", "max"),
                                ).reset_index()
                                _grain_totals = _grain_terminal.groupby([tcol, m_col]).agg(
                                    truck_total=("truck_total", "sum"),
                                    days_max=("days_max", "max"),
                                )
                                grain_denom = _grain_totals["truck_total"] / _grain_totals["days_max"].replace(0, float("nan"))
                        elif use_network_truck_denominator:
                            _grain_totals = nd_df.groupby([tcol, m_col]).agg(
                                truck_total=("truck_count", "sum"),
                                days_max=("days_in_period", "max"),
                            )
                            grain_denom = _grain_totals["truck_total"] / _grain_totals["days_max"].replace(0, float("nan"))
                        else:
                            grain_denom = nd_df.groupby([tcol, m_col])[denom_metric].sum()
                        share = grain_denom / net_denom.reindex(grain_denom.index, level=0)
                        material_idx = share[share >= min_share].reset_index()[[tcol, m_col]]
                        nd_df = nd_df.merge(material_idx, on=[tcol, m_col], how="inner")
                    
                    if level_col == "_total_agg":
                        nd_df["_total_agg"] = "Total"
                    
                    def _ratio_agg(period_str):
                        sub = nd_df[nd_df[tcol] == period_str]
                        if sub.empty:
                            return pd.DataFrame(columns=["item", "val"])
                        num_s = sub.groupby(level_col)[num_metric].sum()
                        den_s = _effective_denom_by_group(sub, level_col)
                        r = (num_s / den_s.replace(0, float('nan'))).reset_index()
                        r.columns = ["item", "val"]
                        return r

                    def _network_ratio(period_str):
                        sub = nd_df[nd_df[tcol] == period_str]
                        if sub.empty:
                            return 0.0
                        num_total = sub[num_metric].sum()
                        den_total = _effective_denom_total(sub)
                        return float(num_total / den_total) if den_total > 0 else 0.0

                    current_agg = _ratio_agg(str(current_period))
                    current_agg.columns = ["item", "current"]
                    prior_agg = _ratio_agg(prior_period_str)
                    prior_agg.columns = ["item", "prior"]
                    _net_cur = _network_ratio(str(current_period))
                    _net_pri = _network_ratio(prior_period_str)
                    _network_variance = _net_cur - _net_pri
                
                else:
                    # Fallback to loading from validation data (LONG format).
                    # ONLY for validation_ops / CSV datasets. NEVER for Tableau - that would mix
                    # data/validation_data.csv with the analysis context (different source).
                    if is_tableau:
                        print(
                            f"[compute_level_statistics] Tableau dataset: skipping validation fallback. "
                            f"Missing {num_metric!r} or {denom_metric!r} in df. Using simple aggregation."
                        )
                        ratio_config = None
                    else:
                        # validation_ops: load numerator/denominator from same CSV source
                        from data_analyst_agent.tools.validation_data_loader import load_validation_data
                        _exclude_partial = os.environ.get("DATA_ANALYST_EXCLUDE_PARTIAL_WEEK", "false").lower() == "true"
                        nd_df = load_validation_data(metric_filter=[num_metric, denom_metric], exclude_partial_week=_exclude_partial)
                        if not nd_df.empty and "metric" in nd_df.columns and "value" in nd_df.columns:
                            tcol = time_col if time_col in nd_df.columns else "week_ending"
                            gcol = grain_col if grain_col in nd_df.columns else "terminal"
                            nd_df[tcol] = nd_df[tcol].astype(str)
                            nd_df["value"] = pd.to_numeric(nd_df["value"], errors="coerce").fillna(0)
                            
                            # 1. Compute network total denominator per period (ALL terminals)
                            net_denom = nd_df[nd_df["metric"].str.strip() == denom_metric].groupby(tcol)["value"].sum()
                            
                            # 2. Filter to just the terminals in the current analysis
                            grain_vals = set(current_df[grain_col].unique())
                            nd_df = nd_df[nd_df[gcol].isin(grain_vals)]
                            
                            # 3. Apply share-based materiality filter
                            min_share = ratio_config.get("materiality_min_share")
                            if min_share is not None and min_share > 0:
                                # Use level_col for share if it's not the total aggregate
                                m_col = level_col if level_col != "_total_agg" else gcol
                                grain_denom = (
                                    nd_df[nd_df["metric"].str.strip() == denom_metric]
                                    .groupby([tcol, m_col])["value"].sum()
                                )
                                share = grain_denom / net_denom.reindex(grain_denom.index, level=0)
                                material_idx = share[share >= min_share].reset_index()[[tcol, m_col]]
                                nd_df = nd_df.merge(material_idx, on=[tcol, m_col], how="inner")
                            if level_col == "_total_agg":
                                nd_df["_total_agg"] = "Total"
                            elif level_col not in nd_df.columns:
                                ratio_config = None
                            if ratio_config:
                                def _ratio_agg(period_str):
                                    sub = nd_df[nd_df[tcol] == period_str]
                                    if sub.empty:
                                        return pd.DataFrame(columns=["item", "val"])
                                    num_s = sub[sub["metric"].str.strip() == num_metric].groupby(level_col)["value"].sum()
                                    den_s = sub[sub["metric"].str.strip() == denom_metric].groupby(level_col)["value"].sum()
                                    r = (num_s / den_s.replace(0, float('nan'))).reset_index()
                                    r.columns = ["item", "val"]
                                    return r

                                def _network_ratio(period_str):
                                    """Aggregate-then-derive at the network (total) level."""
                                    sub = nd_df[nd_df[tcol] == period_str]
                                    if sub.empty:
                                        return 0.0
                                    num_total = sub[sub["metric"].str.strip() == num_metric]["value"].sum()
                                    den_total = sub[sub["metric"].str.strip() == denom_metric]["value"].sum()
                                    return float(num_total / den_total) if den_total > 0 else 0.0

                                current_agg = _ratio_agg(str(current_period))
                                current_agg.columns = ["item", "current"]
                                prior_agg = _ratio_agg(prior_period_str)
                                prior_agg.columns = ["item", "prior"]
                                _net_cur = _network_ratio(str(current_period))
                                _net_pri = _network_ratio(prior_period_str)
                                _network_variance = _net_cur - _net_pri
                        else:
                            ratio_config = None
            except Exception:
                ratio_config = None
        if not ratio_config:
            current_agg = current_df.groupby(level_col)[metric_col].sum().reset_index()
            current_agg.columns = ["item", "current"]
            prior_agg = prior_df.groupby(level_col)[metric_col].sum().reset_index()
            prior_agg.columns = ["item", "prior"]

        # 6. Merge and Variance
        merged = current_agg.merge(prior_agg, on="item", how="outer").fillna(0)
        merged["variance_dollar"] = merged["current"] - merged["prior"]
        
        # Handle zero-baseline percentage variance
        # We use NaN to represent undefined percentage (prior=0)
        prior_abs = merged["prior"].abs().replace(0, float('nan'))
        merged["variance_pct"] = (merged["current"] - merged["prior"]) / prior_abs * 100
        
        # Flag new items from zero baseline
        merged["is_new_from_zero"] = (merged["prior"] == 0) & (merged["current"] != 0)

        # Share-based metrics
        total_current = merged["current"].sum() or 1e-9
        total_prior = merged["prior"].sum() or 1e-9
        merged["share_current"] = merged["current"] / total_current
        merged["share_prior"] = merged["prior"] / total_prior
        merged["share_change"] = merged["share_current"] - merged["share_prior"]

        # 7. Materiality (Domain-Agnostic)
        pct_threshold, dollar_threshold = _get_materiality_thresholds(ctx)
        
        merged["exceeds_threshold"] = (merged["variance_dollar"].abs() >= dollar_threshold) | \
                                      (merged["variance_pct"].abs() >= pct_threshold)
        merged["materiality"] = merged["exceeds_threshold"].apply(lambda x: "HIGH" if x else "LOW")

        # 8. Ranking and Cumulative
        share_mode = os.environ.get("LAG_METRIC_SHARE_MODE", "true").lower() == "true"
        if lag > 0 and share_mode:
            # Rank by absolute share change for lagging metrics
            merged = merged.sort_values("share_change", key=lambda x: x.abs(), ascending=False)
        else:
            # Standard: Rank by absolute dollar variance
            merged = merged.sort_values("variance_dollar", key=lambda x: x.abs(), ascending=False)
            
        total_abs_variance = merged["variance_dollar"].abs().sum() or 1e-9
        merged["cumulative_pct"] = (merged["variance_dollar"].abs().cumsum() / total_abs_variance * 100)
        merged["rank"] = range(1, len(merged) + 1)

        # 9. Selection
        top_items = merged.head(top_n)
        
        top_drivers = []
        for _, row in top_items.iterrows():
            var_pct = row["variance_pct"]
            if pd.isna(var_pct):
                var_pct = None
                
            top_drivers.append({
                "rank": int(row["rank"]),
                "item": str(row["item"]),
                "current": float(row["current"]),
                "prior": float(row["prior"]),
                "variance_dollar": float(row["variance_dollar"]),
                "variance_pct": var_pct,
                "is_new_from_zero": bool(row.get("is_new_from_zero", False)),
                "share_current": float(row["share_current"]),
                "share_prior": float(row["share_prior"]),
                "share_change": float(row["share_change"]),
                "cumulative_pct": float(row["cumulative_pct"]),
                "exceeds_threshold": bool(row["exceeds_threshold"]),
                "materiality": row["materiality"]
            })

        # 10. Summary
        variance_explained = float(top_items["cumulative_pct"].iloc[-1]) if not top_items.empty else 0
        
        # For ratio metrics, total_variance_dollar is the network-level change
        # (aggregate-then-derive at total level), not the sum of per-group ratio changes
        # which would meaninglessly inflate the figure (e.g. summing 3 regional ratios
        # of ~$3,750 each would give ~$11,250, which looks like a Rev/Trk/Wk value).
        if _network_variance is not None:
            total_variance_dollar = _network_variance
        else:
            total_variance_dollar = float(merged["variance_dollar"].sum())

        result = {
            "level": level,
            "level_name": level_name,
            "metric": metric_col,
            "analysis_period": current_period,
            "lag_metadata": {
                "lag_periods": lag,
                "effective_latest_period": str(effective_current),
                "lag_window": [str(p) for p in lag_window]
            } if lag > 0 else None,
            "variance_type": variance_type.upper(),
            "total_variance_dollar": total_variance_dollar,
            "top_drivers": top_drivers,
            "items_analyzed": len(merged),
            "variance_explained_pct": round(variance_explained, 2),
            "is_last_level": is_last_level
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        import traceback
        return json.dumps({
            "error": "ComputationFailed",
            "message": f"Failed to compute level statistics: {str(e)}",
            "traceback": traceback.format_exc(),
            "level": level
        })
