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
Outlier Impact Quantification Tool.

Quantifies the impact of outliers (z-score, MAD) on aggregate metrics
to reveal the underlying "organic" run rate and trend.
"""

import pandas as pd
import numpy as np
import json
from typing import Dict, Any, List, Optional
from scipy import stats as scipy_stats


async def compute_outlier_impact(
    replacement_method: str = "mean",
    outlier_sources: List[str] = ["z_score", "mad"],
    leave_k_out: int = 5,
    pre_resolved: Optional[dict] = None
) -> str:
    """
    Quantify the impact of outliers on aggregate metrics.

    Args:
        replacement_method: "mean", "interpolate", or "exclude".
        outlier_sources: List of detection methods ("z_score", "mad").
        leave_k_out: Number of top outlier items for incremental analysis.
        pre_resolved: Optional pre-resolved data bundle from compute_statistical_summary.
    """
    try:
        if pre_resolved:
            df = pre_resolved["df"].copy()
            time_col = pre_resolved["time_col"]
            metric_col = pre_resolved["metric_col"]
            grain_col = pre_resolved["grain_col"]
            pivot = pre_resolved["pivot"].copy()
        else:
            from ...data_cache import resolve_data_and_columns
            try:
                df, time_col, metric_col, grain_col, name_col, ctx = resolve_data_and_columns("OutlierImpact")
            except ValueError as e:
                return json.dumps({"error": str(e)}, indent=2)
            df[metric_col] = pd.to_numeric(df[metric_col], errors='coerce').fillna(0)
            pivot = df.pivot_table(
                index=grain_col,
                columns=time_col,
                values=metric_col,
                aggfunc='sum',
                fill_value=0
            )
            pivot = pivot.reindex(sorted(pivot.columns), axis=1)
        
        # 2. Identify Outliers

        outlier_points = [] # list of (item, period)
        
        # Z-score detection (same as statistical_summary)
        if "z_score" in outlier_sources:
            for item in pivot.index:
                vals = pivot.loc[item].values
                if len(vals) < 3: continue
                mean = np.mean(vals)
                std = np.std(vals)
                if std > 0:
                    for i, (period, val) in enumerate(zip(pivot.columns, vals)):
                        z = (val - mean) / std
                        if abs(z) >= 2.0:
                            outlier_points.append((item, period, "z_score", z))

        # MAD detection
        if "mad" in outlier_sources:
            for item in pivot.index:
                vals = pivot.loc[item].values
                if len(vals) < 3: continue
                median = np.median(vals)
                mad = np.median(np.abs(vals - median))
                if mad > 0:
                    # Consistency with detect_mad_outliers logic (using 3.0 scale factor)
                    # Actually simplified here:
                    threshold = 3.0 * mad
                    for i, (period, val) in enumerate(zip(pivot.columns, vals)):
                        if abs(val - median) > threshold:
                            outlier_points.append((item, period, "mad", (val - median) / mad))

        if not outlier_points:
            return json.dumps({"skipped": True, "reason": "No outliers detected"}, indent=2)

        # 3. Compute Aggregates
        # Original (With-Outlier) Aggregate
        with_outlier_series = pivot.sum(axis=0)
        
        # Prepare "Cleaned" Pivot
        cleaned_pivot = pivot.copy()
        
        # Load denominator if ratio metric for dollar impact calculation
        denominator_df = None
        denominator_metric_name = None
        if ctx and ctx.contract:
            try:
                from data_analyst_agent.semantic.ratio_metrics_config import get_ratio_config_for_metric
                current_metric_name = None
                if "metric" in df.columns:
                    u_metrics = [str(m).strip() for m in df["metric"].unique() if m]
                    if len(u_metrics) == 1:
                        current_metric_name = u_metrics[0]
                    elif ctx.target_metric and ctx.target_metric.name in u_metrics:
                        current_metric_name = ctx.target_metric.name
                
                if current_metric_name:
                    rc = get_ratio_config_for_metric(ctx.contract, current_metric_name)
                    if rc:
                        denominator_metric_name = rc.get("denominator_metric")
                        from ....tools.validation_data_loader import load_validation_data
                        _exclude_partial = os.environ.get("DATA_ANALYST_EXCLUDE_PARTIAL_WEEK", "false").lower() == "true"
                        denominator_df = load_validation_data(metric_filter=[denominator_metric_name], exclude_partial_week=_exclude_partial)
                        if not denominator_df.empty:
                            denominator_df["value"] = pd.to_numeric(denominator_df["value"], errors="coerce").fillna(0)
                            # Use contract-defined time column
                            contract_time_col = ctx.contract.time.column if ctx.contract.time else None
                            if not contract_time_col or contract_time_col not in denominator_df.columns:
                                raise ValueError(f"Outlier impact: time column '{contract_time_col or time_col}' not found in denominator data (available: {list(denominator_df.columns)})")
                            if grain_col not in denominator_df.columns:
                                raise ValueError(f"Outlier impact: grain column '{grain_col}' not found in denominator data (available: {list(denominator_df.columns)})")
                            denominator_pivot = denominator_df.pivot_table(
                                index=grain_col,
                                columns=contract_time_col,
                                values="value",
                                aggfunc="sum",
                                fill_value=0
                            )
                            denominator_df = denominator_pivot
                        else:
                            denominator_df = None
            except Exception:
                denominator_df = None

        # Replacement
        for item, period, source, score in outlier_points:
            if replacement_method == "mean":
                # Item's own mean excluding outliers
                # Simplified: use all points for mean for now, or improve to exclude
                all_vals = pivot.loc[item].values
                cleaned_pivot.at[item, period] = np.mean(all_vals)
            elif replacement_method == "interpolate":
                # Linear interpolation
                idx = list(pivot.columns).index(period)
                if 0 < idx < len(pivot.columns) - 1:
                    prev_val = pivot.iloc[pivot.index.get_loc(item), idx - 1]
                    next_val = pivot.iloc[pivot.index.get_loc(item), idx + 1]
                    cleaned_pivot.at[item, period] = (prev_val + next_val) / 2
                else:
                    cleaned_pivot.at[item, period] = np.mean(pivot.loc[item].values)
            elif replacement_method == "exclude":
                cleaned_pivot.at[item, period] = 0 # Or NaN? 0 for aggregate sum.

        without_outlier_series = cleaned_pivot.sum(axis=0)
        
        # 4. Compare Trends
        def get_slope(series):
            if len(series) < 2: return 0.0
            x = np.arange(len(series))
            return float(np.polyfit(x, series, 1)[0])

        with_slope = get_slope(with_outlier_series)
        without_slope = get_slope(without_outlier_series)
        
        # 5. Leave-K-Out Analysis
        # Rank outlier points by their absolute dollar impact on the latest period (or total)
        # For simplicity, we'll rank by absolute variance from the mean
        outlier_impacts = []
        for item, period, source, score in outlier_points:
            val = pivot.loc[item, period]
            replacement = cleaned_pivot.loc[item, period]
            raw_impact = val - replacement
            
            # If ratio metric, convert to dollar impact
            dollar_impact = float(raw_impact)
            impact_narrative = ""
            if denominator_df is not None and str(item) in denominator_df.index and str(period) in denominator_df.columns:
                denom_val = denominator_df.loc[str(item), str(period)]
                dollar_impact = float(raw_impact * denom_val)
                impact_narrative = f"Based on {denominator_metric_name} of {denom_val:,.0f}."

            outlier_impacts.append({
                "item": item,
                "item_name": dict(zip(df[grain_col], df[name_col])).get(item, item),
                "period": str(period),
                "impact": float(raw_impact),
                "dollar_impact": dollar_impact,
                "impact_narrative": impact_narrative,
                "source": source
            })
            
        # Group by item for leave-K-out
        item_total_impacts = {}
        for oi in outlier_impacts:
            item_total_impacts[oi['item']] = item_total_impacts.get(oi['item'], 0.0) + abs(oi['dollar_impact'])
        
        top_impact_items = sorted(item_total_impacts.items(), key=lambda x: x[1], reverse=True)[:leave_k_out]
        
        leave_k_results = []
        cumulative_excluded = []
        # Adjusted total uses dollar impact if available
        current_adjusted_total = with_outlier_series.iloc[-1]
        
        for item, total_abs_impact in top_impact_items:
            # Impact on the latest period
            item_points = [oi for oi in outlier_impacts if oi['item'] == item and oi['period'] == str(pivot.columns[-1])]
            marginal_raw_impact = sum(oi['impact'] for oi in item_points)
            marginal_dollar_impact = sum(oi['dollar_impact'] for oi in item_points)
            
            cumulative_excluded.append(item)
            # If we're working on ratios, the latest_total is also a ratio.
            # However, the user wants "dollar value".
            
            narrative = f"Excluding {item} {'reduces' if marginal_raw_impact > 0 else 'increases'} latest total by {abs(marginal_raw_impact):,.2f}"
            if marginal_dollar_impact != marginal_raw_impact:
                narrative += f" (Impact: ${abs(marginal_dollar_impact):,.2f})"
            
            leave_k_results.append({
                "excluded_item": item,
                "excluded_item_name": dict(zip(df[grain_col], df[name_col])).get(item, item),
                "cumulative_excluded": list(cumulative_excluded),
                "adjusted_total": float(with_outlier_series.iloc[-1] - marginal_raw_impact),
                "marginal_impact": float(marginal_raw_impact),
                "marginal_dollar_impact": float(marginal_dollar_impact),
                "marginal_impact_pct": float(marginal_raw_impact / with_outlier_series.iloc[-1] * 100) if with_outlier_series.iloc[-1] != 0 else 0,
                "narrative": narrative
            })

        # Final Result
        latest_period = str(pivot.columns[-1])
        with_val = float(with_outlier_series.iloc[-1])
        without_val = float(without_outlier_series.iloc[-1])
        
        # Aggregate dollar impact for the latest period
        latest_period_outliers = [oi for oi in outlier_impacts if oi['period'] == latest_period]
        total_latest_dollar_impact = sum(oi['dollar_impact'] for oi in latest_period_outliers)
        
        result = {
            "outliers_identified": {
                "total_outlier_points": len(outlier_points),
                "unique_items_with_outliers": len(set(p[0] for p in outlier_points)),
                "unique_periods_with_outliers": len(set(p[1] for p in outlier_points)),
                "outlier_density": round(len(outlier_points) / (pivot.shape[0] * pivot.shape[1]), 4)
            },
            "aggregate_comparison": {
                "latest_period": {
                    "with_outliers": with_val,
                    "without_outliers": without_val,
                    "outlier_impact": with_val - without_val,
                    "outlier_impact_pct": round((with_val - without_val) / with_val * 100, 2) if with_val != 0 else 0,
                    "outlier_dollar_impact": float(total_latest_dollar_impact)
                },
                "trend_slope": {
                    "with_outliers": round(with_slope, 2),
                    "without_outliers": round(without_slope, 2),
                    "outlier_impact_on_slope": round(with_slope - without_slope, 2),
                    "interpretation": f"Outliers {'inflate' if with_slope > without_slope else 'deflate'} the apparent trend by {abs(with_slope - without_slope):,.2f}/period"
                },
                "average": {
                    "with_outliers": round(float(with_outlier_series.mean()), 2),
                    "without_outliers": round(float(without_outlier_series.mean()), 2),
                    "outlier_impact": round(float(with_outlier_series.mean() - without_outlier_series.mean()), 2)
                }
            },
            "leave_k_out": leave_k_results,
            "cleaned_time_series": {
                "periods": [str(c) for c in pivot.columns],
                "with_outliers": with_outlier_series.tolist(),
                "without_outliers": without_outlier_series.tolist()
            },
            "summary": {
                "outlier_impact_magnitude": "high" if abs(with_val - without_val) / abs(with_val) > 0.1 else "moderate" if abs(with_val - without_val) / abs(with_val) > 0.03 else "low",
                "outlier_impact_on_trend": "inflating" if with_slope > without_slope else "deflating" if with_slope < without_slope else "neutral",
                "recommendation": f"Underlying run rate is {without_val:,.2f} vs headline {with_val:,.2f}. Focus on organic trend excluding outliers."
            }
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        import traceback
        return json.dumps({
            "error": f"Failed to compute outlier impact: {str(e)}",
            "traceback": traceback.format_exc()
        }, indent=2)
