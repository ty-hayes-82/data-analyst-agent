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
Comprehensive Statistical Summary Tool

Computes all key statistics in pure Python/pandas/numpy:
- Per-account metrics (avg, std, CV, slopes)
- Anomaly detection (z-scores)
- Correlations between accounts
- Monthly totals and rankings
"""

import pandas as pd
import numpy as np
from scipy import stats as scipy_stats
from typing import Dict, Any, List
import json
import os
import time
from io import StringIO
from config.statistical_analysis_config import (
    get_analysis_toggle_summary,
    get_skip_tools,
)


def _json_default(value):
    if isinstance(value, np.generic):
        return value.item()
    return str(value)


async def compute_statistical_summary() -> str:
    """
    Compute comprehensive statistical summary from validated data.
    """
    # Import here to avoid circular dependencies
    from ...data_cache import resolve_data_and_columns
    from .compute_seasonal_decomposition import compute_seasonal_decomposition
    from .detect_change_points import detect_change_points
    from .detect_mad_outliers import detect_mad_outliers
    from .compute_forecast_baseline import compute_forecast_baseline
    from .compute_derived_metrics import compute_derived_metrics
    from .compute_new_lost_same_store import compute_new_lost_same_store
    from .compute_concentration_analysis import compute_concentration_analysis
    from .compute_cross_metric_correlation import compute_cross_metric_correlation
    from .compute_lagged_correlation import compute_lagged_correlation
    from .compute_variance_decomposition import compute_variance_decomposition
    from .compute_outlier_impact import compute_outlier_impact
    from .compute_distribution_analysis import compute_distribution_analysis
    from .compute_cross_dimension_analysis import compute_cross_dimension_analysis
    from ....semantic.lag_utils import resolve_effective_latest_period, get_effective_lag_or_default
    
    try:
        # 1. Get data from context or legacy cache
        t_resolve_start = time.perf_counter()
        try:
            df, time_col, metric_col, grain_col, name_col, ctx = resolve_data_and_columns("StatisticalSummary")
        except ValueError as e:
            return json.dumps({"error": str(e)}, indent=2, default=_json_default)
        print(f"[StatisticalSummary] [TIMER] resolve_data_and_columns: {time.perf_counter() - t_resolve_start:.2f}s", flush=True)

        # Ensure numeric metric column
        df[metric_col] = pd.to_numeric(df[metric_col], errors='coerce').fillna(0)
        
        # Get target metric name
        current_metric_name = None
        if "metric" in df.columns:
            u_metrics = [str(m).strip() for m in df["metric"].unique() if m]
            if len(u_metrics) == 1:
                current_metric_name = u_metrics[0]
            elif ctx and ctx.target_metric and ctx.target_metric.name in u_metrics:
                current_metric_name = ctx.target_metric.name
            else:
                try:
                    from .ratio_metrics_config import get_ratio_config_for_metric as _get_rc
                    for m in u_metrics:
                        if _get_rc(ctx.contract, m):
                            current_metric_name = m
                            break
                except Exception:
                    pass
        
        if not current_metric_name and ctx and ctx.target_metric:
            current_metric_name = ctx.target_metric.name

        # === CRITICAL: Filter df by target metric BEFORE creating pivot and account_stats ===
        # This ensures stats like avg, std, and top_drivers are computed on the correct metric series.
        if current_metric_name and "metric" in df.columns and df["metric"].nunique() > 1:
            if current_metric_name in [str(m).strip() for m in df["metric"].unique()]:
                print(f"[StatisticalSummary] Filtering input data to target metric: '{current_metric_name}'", flush=True)
                df = df[df["metric"].str.strip() == current_metric_name].copy()

        # Get names map for items
        names_map = dict(zip(df[grain_col], df[name_col]))
        
        # Pivot to grain x period matrix for analysis
        pivot = df.pivot_table(
            index=grain_col,
            columns=time_col,
            values=metric_col,
            aggfunc='sum',
            fill_value=0
        )
        
        # Sort periods chronologically
        pivot = pivot.reindex(sorted(pivot.columns), axis=1)

        # === Materiality pre-filter: null out terminal-periods where the denominator
        # (e.g. Truck Count) represents less than materiality_min_share of the network total.
        # This must happen before account_stats so max/avg/anomaly values are not skewed
        # by terminals winding down (e.g. 1-3 trucks representing < 0.1% of network).
        _current_metric_name_pre = None
        if "metric" in df.columns:
            _u_metrics_pre = [str(m).strip() for m in df["metric"].unique() if m]
            if len(_u_metrics_pre) == 1:
                _current_metric_name_pre = _u_metrics_pre[0]
            elif ctx and ctx.target_metric and ctx.target_metric.name in _u_metrics_pre:
                _current_metric_name_pre = ctx.target_metric.name
            else:
                # If target_metric.name is generic (e.g. "value"), try to find if any unique metric is a ratio
                try:
                    from .ratio_metrics_config import get_ratio_config_for_metric as _get_rc
                    for _m in _u_metrics_pre:
                        if _get_rc(ctx.contract, _m):
                            _current_metric_name_pre = _m
                            break
                except Exception:
                    pass
        
        if not _current_metric_name_pre and ctx and ctx.target_metric:
            _current_metric_name_pre = ctx.target_metric.name

        if ctx and ctx.contract and _current_metric_name_pre:
            try:
                from .ratio_metrics_config import get_ratio_config_for_metric as _get_rc
                _rc_pre = _get_rc(ctx.contract, _current_metric_name_pre)
                _min_share_pre = (_rc_pre or {}).get("materiality_min_share") if _rc_pre else None
                _denom_metric_pre = (_rc_pre or {}).get("denominator_metric") if _rc_pre else None
                if _min_share_pre is not None and _min_share_pre > 0 and _denom_metric_pre:
                    from ....tools.validation_data_loader import load_validation_data as _lvd
                    _gcol = grain_col if grain_col in df.columns else "terminal"
                    _tcol = time_col if time_col in df.columns else "week_ending"
                    # Respect partial week exclusion flag
                    _exclude_partial = os.environ.get("DATA_ANALYST_EXCLUDE_PARTIAL_WEEK", "false").lower() == "true"
                    _denom_df = _lvd(metric_filter=[_denom_metric_pre], exclude_partial_week=_exclude_partial)
                    if not _denom_df.empty:
                        _denom_df["value"] = pd.to_numeric(_denom_df["value"], errors="coerce").fillna(0)
                        # 1. Compute network total denominator per period (ALL terminals)
                        _net_denom = _denom_df.groupby(_tcol)["value"].sum()
                        
                        # 2. Filter to just the terminals in the current analysis
                        _grain_vals = set(df[_gcol].astype(str).unique())
                        _denom_df_filtered = _denom_df[_denom_df[_gcol].astype(str).isin(_grain_vals)]
                        
                        # 3. Compute per-terminal-period denominator share
                        _grain_denom = _denom_df_filtered.groupby([_tcol, _gcol])["value"].sum()
                        _denom_share = _grain_denom / _net_denom.reindex(_grain_denom.index, level=0)
                        
                        # 4. Identify low-share pairs
                        _low_pairs = _denom_share[_denom_share < _min_share_pre].reset_index()
                        _low_set = set(
                            zip(_low_pairs[_gcol].astype(str), _low_pairs[_tcol].astype(str))
                        )
                        if _low_set:
                            for _col in list(pivot.columns):
                                _col_str = str(_col)
                                for _term in pivot.index:
                                    if (str(_term), _col_str) in _low_set:
                                        pivot.at[_term, _col] = float('nan')
            except Exception:
                pass
        
        # Precompute helpers for upgrades
        temporal_grain = "monthly"
        periods = sorted(pivot.columns)
        lag = get_effective_lag_or_default(ctx.contract, ctx.target_metric) if ctx and ctx.contract and ctx.target_metric else 0
        
        effective_latest, lag_window = resolve_effective_latest_period(periods, lag)
        
        latest_period = str(effective_latest) if effective_latest else "N/A"
        temporal_grain = "monthly"
        ctx_temporal_grain = getattr(ctx, "temporal_grain", None) if ctx else None
        if isinstance(ctx_temporal_grain, str) and ctx_temporal_grain:
            temporal_grain = ctx_temporal_grain
        period_unit = "week" if temporal_grain == "weekly" else "month"
        
        # Find index of effective_latest to get prev_period
        try:
            latest_idx = list(pivot.columns).index(effective_latest)
            prev_period = str(pivot.columns[latest_idx - 1]) if latest_idx > 0 else None
        except ValueError:
            prev_period = None

        # Contribution to change (latest vs prev)
        # For ratio metrics the "total change" comes from monthly_totals (aggregate-then-derive),
        # not from summing per-entity ratio deltas. We compute the correct total after monthly_totals
        # is resolved, so contribution_share is deferred and filled after section 4.
        contribution_share = {}
        if prev_period is not None:
            change_series = (pivot[latest_period] - pivot[prev_period])
            # Preliminary denom (overridden after monthly_totals for ratio metrics)
            _raw_change_denom = float(change_series.sum()) if float(change_series.sum()) != 0 else 1e-9

        # 3M baseline for pattern label
        pattern_label_by_account = {}
        if pivot.shape[1] >= 3:
            mean3 = pivot.iloc[:, -3:].mean(axis=1)
            std3 = pivot.iloc[:, -3:].std(axis=1)
            for account in pivot.index:
                latest_val = float(pivot.loc[account, latest_period])
                m3 = float(mean3.loc[account])
                s3 = float(std3.loc[account])
                is_spike = (abs(latest_val - m3) > 2.0 * s3) if s3 > 0 else False
                pattern_label_by_account[account] = "spike" if is_spike else "run_rate_change"
        else:
            for account in pivot.index:
                pattern_label_by_account[account] = "run_rate_change"

        # === 1. Per-Item Metrics ===
        account_stats = []
        for account in pivot.index:
            values = pivot.loc[account].values
            # Drop NaN values introduced by min_denominator materiality filter
            values_clean = values[~np.isnan(values)]
            if len(values_clean) == 0:
                continue

            # Basic stats (use clean non-NaN values)
            avg = float(np.mean(values_clean))
            std = float(np.std(values_clean))
            cv = abs(std / avg) if avg != 0 else 0
            
            # Last 3-month slope (linear regression via scipy for p-value)
            # Use last 3 non-NaN values to avoid regression on NaN periods
            last_values = values_clean[-3:] if len(values_clean) >= 3 else values_clean
            slope = 0.0
            slope_p_value = 1.0
            slope_r_value = 0.0
            if len(last_values) >= 3:
                x = np.arange(len(last_values), dtype=float)
                try:
                    lr = scipy_stats.linregress(x, last_values)
                    slope = float(lr.slope)
                    slope_p_value = float(lr.pvalue) if not np.isnan(lr.pvalue) else 1.0
                    slope_r_value = float(lr.rvalue) if not np.isnan(lr.rvalue) else 0.0
                except Exception:
                    slope = float(np.polyfit(x, last_values, 1)[0])

            # Previous 3-month slope for acceleration
            acceleration = 0.0
            if len(values_clean) >= 6:
                prev_3 = values_clean[-6:-3]
                x2 = np.arange(len(prev_3), dtype=float)
                try:
                    lr2 = scipy_stats.linregress(x2, prev_3)
                    slope_prev = float(lr2.slope)
                except Exception:
                    slope_prev = float(np.polyfit(x2, prev_3, 1)[0])
                acceleration = float(slope - slope_prev)
            
            # Get item name from names map
            item_name = names_map.get(account, account)
            
            account_stats.append({
                'item': account,
                'item_name': item_name,
                'avg': round(avg, 2),
                'std': round(std, 2),
                'cv': round(cv, 4),
                'slope_3mo': round(slope, 2),
                'slope_3mo_p_value': round(slope_p_value, 6),
                'slope_3mo_r_value': round(slope_r_value, 4),
                'acceleration_3mo': round(acceleration, 2),
                'min': round(float(np.min(values_clean)), 2),
                'max': round(float(np.max(values_clean)), 2)
            })
        
        # Sort by magnitude
        account_stats_sorted = sorted(account_stats, key=lambda x: abs(x['avg']), reverse=True)
        top_drivers = account_stats_sorted[:10]
        
        # Sort by volatility (CV)
        most_volatile = sorted(account_stats, key=lambda x: x['cv'], reverse=True)[:10]
        
        # Total share_of_total based on avg magnitude (avoid divide-by-zero)
        total_avg_mag = sum(abs(a['avg']) for a in account_stats) or 1e-9

        # === 2. Anomaly Detection (Z-scores) ===
        anomalies = []
        for account in pivot.index:
            values = pivot.loc[account].values
            values_nnan = values[~np.isnan(values)]
            if len(values_nnan) == 0:
                continue
            mean = np.mean(values_nnan)
            std = np.std(values_nnan)
            
            if std > 0:
                # Compute z-scores only for non-NaN periods
                for i, (period, val) in enumerate(zip(pivot.columns, values)):
                    if np.isnan(val):
                        continue
                    z = (val - mean) / std
                    if abs(z) >= 2.0:
                        item_name = names_map.get(account, account)
                        p_value = float(scipy_stats.norm.sf(abs(z)) * 2)
                        anomalies.append({
                            'period': str(period),
                            'item': account,
                            'item_name': item_name,
                            'value': round(float(val), 2),
                            'z_score': round(float(z), 2),
                            'p_value': round(p_value, 6),
                            'avg': round(float(mean), 2),
                            'std': round(float(std), 2)
                        })
        
        # Sort anomalies: recency-first (last N periods), then by |z_score|. Cap at 20.
        focus_periods = max(1, int(os.environ.get("ANALYSIS_FOCUS_PERIODS", "4")))
        periods_list = list(pivot.columns)
        recent_periods = set(periods_list[-focus_periods:]) if len(periods_list) >= focus_periods else set(periods_list)

        def _anomaly_rank(a):
            z = abs(a.get("z_score", 0))
            recency = 1 if str(a.get("period", "")) in recent_periods else 0
            return (recency, z)

        anomalies_sorted = sorted(anomalies, key=_anomaly_rank, reverse=True)[:20]
        
        # Build quick lookup for latest-period anomaly per account
        anomaly_latest_flag = {}
        for a in anomalies:
            if a['period'] == latest_period:
                anomaly_latest_flag[a['item']] = True

        # === 3. Correlations ===
        correlations = {}
        
        # Find key items for correlation (based on 'revenue' tag or policies)
        correlation_items = []
        
        # Method: Check for items with the 'revenue' tag or policy classification
        if ctx and ctx.contract:
            policies = ctx.contract.policies
            classification = policies.get("item_classification", {})
            revenue_policy = classification.get("revenue", {})
            
            starts_with = revenue_policy.get("starts_with", [])
            if isinstance(starts_with, str): starts_with = [starts_with]
            
            keywords = revenue_policy.get("keywords", [])
            
            correlation_items = [
                item for item in pivot.index 
                if any(str(item).startswith(s) for s in starts_with) or
                   any(kw in names_map.get(item, "").lower() for kw in keywords)
            ]
        
        if not correlation_items:
            # Fallback: use top 5 items by magnitude
            correlation_items = list(pivot.iloc[:5].index)
        
        if len(correlation_items) >= 2:
            # Calculate correlation between top correlation items using pearsonr for p-values
            for i in range(min(3, len(correlation_items))):
                for j in range(i + 1, min(4, len(correlation_items))):
                    acc1 = correlation_items[i]
                    acc2 = correlation_items[j]
                    
                    a_vals = pivot.loc[acc1].values
                    b_vals = pivot.loc[acc2].values
                    # Drop periods where either series is NaN
                    mask = ~(np.isnan(a_vals) | np.isnan(b_vals))
                    a_vals = a_vals[mask]
                    b_vals = b_vals[mask]
                    try:
                        corr, p_val = scipy_stats.pearsonr(a_vals, b_vals)
                        corr = float(corr) if not np.isnan(corr) else 0.0
                        p_val = float(p_val) if not np.isnan(p_val) else 1.0
                    except Exception:
                        corr = float(np.corrcoef(a_vals, b_vals)[0, 1]) if len(a_vals) > 1 else 0.0
                        p_val = 1.0
                    
                    # Only report strong correlations that are statistically significant
                    if abs(corr) > 0.7 and p_val < 0.05:
                        key = f"{acc1}_vs_{acc2}"
                        correlations[key] = {"r": round(corr, 3), "p_value": round(p_val, 6)}
        
        # Compute data-quality flag for uniform growth: % of pairs with |rho|>=0.95 among top N accounts
        suspected_uniform_growth = False
        try:
            corr_matrix = np.corrcoef(pivot.values)
            n = corr_matrix.shape[0]
            if n >= 2:
                upper = []
                for i in range(n):
                    for j in range(i+1, n):
                        if not np.isnan(corr_matrix[i, j]):
                            upper.append(abs(float(corr_matrix[i, j])))
                if upper:
                    high = len([v for v in upper if v >= 0.95])
                    suspected_uniform_growth = (high / len(upper)) > 0.5
        except Exception:
            pass

        # === 4. Period Totals (aggregate-then-derive for ratio metrics) ===
        monthly_totals = {}
        ratio_config = None
        if ctx and ctx.contract and current_metric_name:
            from .ratio_metrics_config import get_ratio_config_for_metric
            ratio_config = get_ratio_config_for_metric(ctx.contract, current_metric_name)
        
        if ratio_config:
            num_metric = ratio_config.get("numerator_metric")
            denom_metric = ratio_config.get("denominator_metric")
            min_share = ratio_config.get("materiality_min_share")
            try:
                # 1. Check if numerator and denominator columns are already in df (WIDE format)
                # NEVER use validation_data.csv fallback for Tableau - that mixes data from a different source.
                is_tableau = (
                    ctx.contract
                    and getattr(ctx.contract, "data_source", None)
                    and getattr(ctx.contract.data_source, "type", None) == "tableau_hyper"
                )
                if num_metric in df.columns and denom_metric in df.columns:
                    nd_df = df.copy()
                    # Mock metric column for consistency with the block below
                    nd_df["metric"] = "mock"
                    # Use provided columns directly later
                elif is_tableau:
                    # Tableau dataset but missing ratio columns - skip ratio config, use simple sum
                    ratio_config = None
                else:
                    # 2. Fall back to loading from validation data (LONG format) - validation_ops only
                    from ....tools.validation_data_loader import load_validation_data
                    _exclude_partial = os.environ.get("DATA_ANALYST_EXCLUDE_PARTIAL_WEEK", "false").lower() == "true"
                    nd_df = load_validation_data(metric_filter=[num_metric, denom_metric], exclude_partial_week=_exclude_partial)
                
                if not nd_df.empty:
                    tcol = time_col if time_col in nd_df.columns else "week_ending"
                    gcol = grain_col if grain_col in nd_df.columns else "terminal"
                    use_network_truck_denominator = (
                        denom_metric == "Truck Count"
                        and "truck_count" in nd_df.columns
                        and "days_in_period" in nd_df.columns
                    )
                    
                    # Resolve numerator/denominator series based on WIDE or LONG format
                    if num_metric in nd_df.columns and denom_metric in nd_df.columns:
                        # WIDE format
                        num_series = pd.to_numeric(nd_df[num_metric], errors="coerce").fillna(0)
                        denom_series = pd.to_numeric(nd_df[denom_metric], errors="coerce").fillna(0)
                        if "truck_count" in nd_df.columns:
                            nd_df["truck_count"] = pd.to_numeric(nd_df["truck_count"], errors="coerce").fillna(0)
                        if "days_in_period" in nd_df.columns:
                            nd_df["days_in_period"] = pd.to_numeric(nd_df["days_in_period"], errors="coerce").fillna(0)
                    else:
                        # LONG format (legacy)
                        nd_df["value"] = pd.to_numeric(nd_df["value"], errors="coerce").fillna(0)
                        num_series = nd_df[nd_df["metric"].str.strip() == num_metric]["value"]
                        denom_series = nd_df[nd_df["metric"].str.strip() == denom_metric]["value"]
                    
                    # 1. Compute network total denominator per period (ALL terminals)
                    # For WIDE format, use groupby on the full nd_df
                    if num_metric in nd_df.columns and denom_metric in nd_df.columns:
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
                            num_agg = nd_df.groupby(tcol)[num_metric].sum()
                            denom_agg = net_denom
                        elif use_network_truck_denominator:
                            _period_totals = nd_df.groupby(tcol).agg(
                                truck_total=("truck_count", "sum"),
                                days_max=("days_in_period", "max"),
                            )
                            net_denom = _period_totals["truck_total"] / _period_totals["days_max"].replace(0, float("nan"))
                            num_agg = nd_df.groupby(tcol)[num_metric].sum()
                            denom_agg = net_denom
                        else:
                            net_denom = nd_df.groupby(tcol)[denom_metric].sum()
                            num_agg = nd_df.groupby(tcol)[num_metric].sum()
                            denom_agg = nd_df.groupby(tcol)[denom_metric].sum()
                    else:
                        # For LONG format
                        net_denom = nd_df[nd_df["metric"].str.strip() == denom_metric].groupby(tcol)["value"].sum()
                        num_agg = nd_df[nd_df["metric"].str.strip() == num_metric].groupby(tcol)["value"].sum()
                        denom_agg = nd_df[nd_df["metric"].str.strip() == denom_metric].groupby(tcol)["value"].sum()
                    
                    for period in pivot.columns:
                        p = str(period)
                        denom = float(denom_agg.get(p, 0)) or 1e-9
                        total = float(num_agg.get(p, 0)) / denom
                        monthly_totals[p] = round(total, 2)
                else:
                    ratio_config = None
            except Exception:
                ratio_config = None
        if not ratio_config:
            for period in pivot.columns:
                total = float(pivot[period].sum())
                monthly_totals[str(period)] = round(total, 2)
        
        # Finalize contribution_share using monthly_totals (correct for ratio metrics)
        if prev_period is not None and monthly_totals:
            latest_mt = monthly_totals.get(latest_period, 0)
            prev_mt = monthly_totals.get(prev_period, 0)
            correct_total_change = latest_mt - prev_mt
            total_change_denom = correct_total_change if correct_total_change != 0 else 1e-9
            for account in pivot.index:
                contribution_share[account] = float(change_series.loc[account] / total_change_denom)

        # === 5. Summary Statistics ===
        total_accounts = len(pivot.index)
        total_periods = len(pivot.columns)
        
        # Find highest/lowest totals across detected period grain
        sorted_months = sorted(monthly_totals.items(), key=lambda x: x[1])
        highest_month = sorted_months[-1] if sorted_months else ("N/A", 0)
        lowest_month = sorted_months[0] if sorted_months else ("N/A", 0)
        
        summary_stats = {
            'total_items': int(total_accounts),
            'total_periods': int(total_periods),
            'period_range': f"{pivot.columns[0]} to {pivot.columns[-1]}",
            'highest_total_month': {'period': str(highest_month[0]), 'total': float(highest_month[1])},
            'lowest_total_month': {'period': str(lowest_month[0]), 'total': float(lowest_month[1])},
            'highest_total_period': {'period': str(highest_month[0]), 'total': float(highest_month[1])},
            'lowest_total_period': {'period': str(lowest_month[0]), 'total': float(lowest_month[1])},
            'total_anomalies_detected': int(len(anomalies_sorted)),
            'items_with_high_volatility': int(len([a for a in account_stats if a['cv'] > 0.5])),
            'temporal_grain': temporal_grain,
            'period_unit': period_unit,
        }
        
        # === Compile enhanced drivers with contribution, pattern, flags ===
        enhanced_top_drivers = []
        for d in top_drivers:
            acc = d['item']
            enhanced_top_drivers.append({
                'item': acc,
                'item_name': d['item_name'],
                'avg': d['avg'],
                'std': d['std'],
                'cv': d['cv'],
                'slope_3mo': d['slope_3mo'],
                'slope_3mo_p_value': d.get('slope_3mo_p_value', 1.0),
                'slope_3mo_r_value': d.get('slope_3mo_r_value', 0.0),
                'acceleration_3mo': d.get('acceleration_3mo', 0),
                'min': d['min'],
                'max': d['max'],
                'share_of_total': round(abs(d['avg']) / total_avg_mag, 4),
                'contribution_share': round(float(contribution_share.get(acc, 0.0)), 4),
                'pattern_label': pattern_label_by_account.get(acc, 'run_rate_change'),
                'per_unit_change': None,  # No ops metrics available in this tool
                'anomaly_latest': bool(anomaly_latest_flag.get(acc, False)),
            })

        # Delta attribution list (uses monthly_totals for correct ratio metric denom)
        delta_attribution = []
        if prev_period is not None:
            deltas_sorted = change_series.sort_values(key=lambda s: s.abs(), ascending=False)
            latest_mt = monthly_totals.get(latest_period, 0)
            prev_mt = monthly_totals.get(prev_period, 0)
            correct_total_change = latest_mt - prev_mt
            da_denom = correct_total_change if correct_total_change != 0 else 1e-9
            for acc, delta in deltas_sorted.items():
                item_name = names_map.get(acc, acc)
                delta_attribution.append({
                    'item': acc,
                    'item_name': item_name,
                    'delta': round(float(delta), 2),
                    'share': round(float(delta) / da_denom, 4),
                    'pattern_label': pattern_label_by_account.get(acc, 'run_rate_change')
                })

        # === ENHANCED: Call Advanced Analysis Tools in Parallel (bounded concurrency) ===
        import asyncio
        from ._resolved_data import build_resolved_bundle

        skip_tools = get_skip_tools()
        toggle_summary = get_analysis_toggle_summary()
        print(
            f"[StatisticalSummary] Profile: {toggle_summary.get('profile', 'unknown')} "
            f"(source={toggle_summary.get('source', 'unknown')})"
        )
        if toggle_summary.get("enabled_tools"):
            print(
                f"[StatisticalSummary] Enabled: {toggle_summary.get('enabled_tools')}"
            )
        if skip_tools:
            print(f"[StatisticalSummary] Disabled: {sorted(skip_tools)}")
        if toggle_summary.get("overrides"):
            print(
                f"[StatisticalSummary] Overrides: {toggle_summary.get('overrides')}"
            )
        print("[StatisticalSummary] Running advanced analysis...")
        
        # Build shared data bundle to avoid redundant resolve_data_and_columns in each tool
        lag_meta = {
            'lag_periods': lag,
            'effective_latest': latest_period,
            'lag_window': [str(p) for p in lag_window]
        } if lag > 0 else None
        
        resolved_bundle = build_resolved_bundle(
            df=df,
            pivot=pivot,
            time_col=time_col,
            metric_col=metric_col,
            grain_col=grain_col,
            name_col=name_col,
            ctx=ctx,
            names_map=names_map,
            monthly_totals=monthly_totals,
            lag_metadata=lag_meta,
        )
        
        concurrency = int(os.environ.get("STATISTICAL_ADVANCED_CONCURRENCY", "3"))
        sem = asyncio.Semaphore(concurrency)
        
        async def _run_with_sem(coro):
            async with sem:
                return await coro

        async def _timed_tool(name: str, coro):
            t0 = time.perf_counter()
            try:
                r = await coro
                elapsed = time.perf_counter() - t0
                print(f"[StatisticalSummary] [TIMER] {name}: {elapsed:.2f}s", flush=True)
                return r
            except Exception as e:
                elapsed = time.perf_counter() - t0
                print(f"[StatisticalSummary] [TIMER] {name}: {elapsed:.2f}s FAILED: {e}", flush=True)
                raise

        async def _skipped_placeholder(name: str):
            t0 = time.perf_counter()
            r = json.dumps({"skipped": True, "reason": "disabled"}, default=_json_default)
            elapsed = time.perf_counter() - t0
            print(f"[StatisticalSummary] [TIMER] {name}: {elapsed:.2f}s (skipped)", flush=True)
            return r

        # Tool defs: (env_name, display_name, coro_factory)
        tool_defs = [
            ("seasonal_decomposition", "SeasonalDecomposition", lambda: compute_seasonal_decomposition(pre_resolved=resolved_bundle)),
            ("change_points", "ChangePoints", lambda: detect_change_points(pre_resolved=resolved_bundle)),
            ("mad_outliers", "MADOutliers", lambda: detect_mad_outliers(pre_resolved=resolved_bundle)),
            ("forecast_baseline", "ForecastBaseline", lambda: compute_forecast_baseline(pre_resolved=resolved_bundle)),
            ("derived_metrics", "DerivedMetrics", lambda: compute_derived_metrics(pre_resolved=resolved_bundle)),
            ("new_lost_same_store", "NewLostSameStore", lambda: compute_new_lost_same_store(pre_resolved=resolved_bundle)),
            ("concentration_analysis", "ConcentrationAnalysis", lambda: compute_concentration_analysis(pre_resolved=resolved_bundle)),
            ("cross_metric_correlation", "CrossMetricCorrelation", lambda: compute_cross_metric_correlation(pre_resolved=resolved_bundle)),
            ("lagged_correlation", "LaggedCorrelation", lambda: compute_lagged_correlation(pre_resolved=resolved_bundle)),
            ("variance_decomposition", "VarianceDecomposition", lambda: compute_variance_decomposition(pre_resolved=resolved_bundle)),
            ("outlier_impact", "OutlierImpact", lambda: compute_outlier_impact(pre_resolved=resolved_bundle)),
            ("distribution_analysis", "DistributionAnalysis", lambda: compute_distribution_analysis(pre_resolved=resolved_bundle)),
        ]

        # Cross-dimension analysis follows the unified tool-toggle system.
        _cross_dim_enabled = "cross_dimension_analysis" not in skip_tools
        cross_dims = ctx.contract.cross_dimensions if (_cross_dim_enabled and ctx and ctx.contract and isinstance(getattr(ctx.contract, "cross_dimensions", None), (list, tuple))) else []
        if cross_dims:
            for cd_cfg in cross_dims:
                _cd_name = cd_cfg.name
                tool_defs.append((
                    "cross_dimension_analysis",
                    f"CrossDimension_{_cd_name}",
                    lambda _n=_cd_name, _ms=cd_cfg.min_sample_size, _mc=cd_cfg.max_cardinality: (
                        compute_cross_dimension_analysis(
                            hierarchy_level=0,
                            auxiliary_dimension=_n,
                            min_sample_size=_ms,
                            max_cardinality=_mc,
                            pre_resolved=resolved_bundle,
                        )
                    ),
                ))

        task_coros = []
        for env_name, display_name, coro_fn in tool_defs:
            if env_name in skip_tools:
                task_coros.append(_run_with_sem(_skipped_placeholder(display_name)))
            else:
                task_coros.append(_run_with_sem(_timed_tool(display_name, coro_fn())))
        
        t_adv_start = time.perf_counter()
        results = await asyncio.gather(*task_coros, return_exceptions=True)
        t_adv_elapsed = time.perf_counter() - t_adv_start
        print(f"[StatisticalSummary] [TIMER] Advanced analysis total: {t_adv_elapsed:.2f}s", flush=True)
        
        # Helper to parse JSON or handle exception
        def _parse_result(res, name):
            if isinstance(res, Exception):
                print(f"[StatisticalSummary] Warning: {name} failed: {res}")
                return {"error": str(res)}
            try:
                return json.loads(res)
            except Exception as e:
                print(f"[StatisticalSummary] Warning: {name} returned invalid JSON: {e}")
                return {"error": "Invalid JSON"}

        # Extract results -- first 12 are the fixed tools, remaining are cross-dim
        seasonal_data = _parse_result(results[0], "SeasonalDecomposition")
        changepoint_data = _parse_result(results[1], "ChangePoints")
        mad_data = _parse_result(results[2], "MADOutliers")
        forecast_data = _parse_result(results[3], "ForecastBaseline")
        ratio_data = _parse_result(results[4], "DerivedMetrics")
        nlss_data = _parse_result(results[5], "NewLostSameStore")
        concentration_data = _parse_result(results[6], "ConcentrationAnalysis")
        cross_metric_data = _parse_result(results[7], "CrossMetricCorrelation")
        lagged_data = _parse_result(results[8], "LaggedCorrelation")
        variance_data = _parse_result(results[9], "VarianceDecomposition")
        outlier_impact_data = _parse_result(results[10], "OutlierImpact")
        distribution_data = _parse_result(results[11], "DistributionAnalysis")

        cross_dim_data = {}
        _fixed_tool_count = 12
        for idx in range(_fixed_tool_count, len(results)):
            td = tool_defs[idx]
            cross_dim_data[td[1]] = _parse_result(results[idx], td[1])
        
        print("[StatisticalSummary] Advanced analysis complete")
        
        # === Compile Results (Original + Enhanced) ===
        result = {
            # Original analysis
            'top_drivers': top_drivers,
            'most_volatile': most_volatile,
            'anomalies': anomalies_sorted,
            'correlations': correlations,
            'monthly_totals': monthly_totals,
            'period_totals': monthly_totals,
            'summary_stats': summary_stats,
            'enhanced_top_drivers': enhanced_top_drivers,
            'normalization_unavailable': True,
            'normalization_readiness': {'ready': False, 'missing_metrics': ['miles', 'loads', 'stops']},
            'delta_attribution': delta_attribution,
            'dq_flags': {'suspected_uniform_growth': suspected_uniform_growth},
            'lag_metadata': {
                'lag_periods': lag,
                'effective_latest': latest_period,
                'lag_window': [str(p) for p in lag_window]
            } if lag > 0 else None,
            
            # NEW: Advanced analysis results
            'seasonal_analysis': seasonal_data,
            'change_points': changepoint_data,
            'mad_outliers': mad_data,
            'forecasts': forecast_data,
            'operational_ratios': ratio_data,
            'new_lost_same_store': nlss_data,
            'concentration_analysis': concentration_data,
            'cross_metric_correlations': cross_metric_data,
            'lagged_correlations': lagged_data,
            'variance_decomposition': variance_data,
            'outlier_impact': outlier_impact_data,
            'distribution_analysis': distribution_data,
            'cross_dimension_analysis': cross_dim_data if cross_dim_data else None,
            
            'metadata': {
                'computation_method': 'pandas/numpy statistical analysis + advanced methods',
                'anomaly_threshold': 'z-score >= 2.0',
                'slope_method': f'last 3 {period_unit}s linear regression',
                'temporal_grain': temporal_grain,
                'period_unit': period_unit,
                'advanced_methods': [
                    'STL seasonal decomposition',
                    'PELT change point detection',
                    'MAD robust outlier detection',
                    'ARIMA forecasting',
                    'Operational ratio analysis',
                    'New/Lost/Same-Store decomposition',
                    'Concentration / Pareto analysis (HHI, Gini)',
                    'Cross-metric correlation matrix',
                    'Lagged cross-correlation (leading indicators)',
                    'Variance decomposition (ANOVA)',
                    'Outlier impact quantification',
                    'Distribution shape analysis',
                    'Cross-dimension analysis (auxiliary dimension interaction)',
                ]
            }
        }
        
        return json.dumps(result, indent=2, default=_json_default)
        
    except Exception as e:
        return json.dumps({
            "error": f"Failed to compute statistical summary: {str(e)}",
            "traceback": str(e)
        }, indent=2, default=_json_default)
