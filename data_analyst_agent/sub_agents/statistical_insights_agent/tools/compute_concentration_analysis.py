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
Concentration / Pareto Analysis Tool

Measures portfolio concentration using:
- Pareto ratio: % of entities needed to reach 80% of total
- HHI (Herfindahl-Hirschman Index): Sum of squared market shares (0-10000 scale)
- Gini coefficient: Inequality measure (0 = equality, 1 = maximum concentration)

Also tracks concentration trends over time and identifies persistent variance drivers.
"""

import json
import pandas as pd
import numpy as np
from scipy import stats as scipy_stats
from typing import Dict, Any, List, Optional
from ....semantic.lag_utils import resolve_effective_latest_period


def _compute_hhi(shares: pd.Series) -> float:
    """Compute HHI on the 10,000-point scale."""
    if shares.sum() == 0:
        return 0.0
    return float(np.sum((shares * 100) ** 2))


def _hhi_label(hhi: float) -> str:
    """Return DOJ/FTC standard concentration label."""
    if hhi < 1500:
        return "Unconcentrated (<1500)"
    elif hhi < 2500:
        return "Moderately concentrated (1500-2500)"
    else:
        return "Highly concentrated (>2500)"


def _compute_gini(values: np.ndarray) -> float:
    """
    Compute Gini coefficient using sorted cumulative sums formula.
    
    Returns value in [0, 1] where 0 = perfect equality, 1 = maximum concentration.
    """
    if len(values) == 0 or np.sum(values) == 0:
        return 0.0
    
    sorted_vals = np.sort(np.abs(values))
    n = len(sorted_vals)
    index = np.arange(1, n + 1)
    
    total = np.sum(sorted_vals)
    if total == 0:
        return 0.0
    
    gini = (2 * np.sum(index * sorted_vals)) / (n * total) - (n + 1) / n
    return float(max(0.0, min(gini, 1.0)))


def _compute_pareto(shares: pd.Series, threshold: float = 0.8) -> tuple:
    """
    Compute Pareto ratio: smallest k such that top-k entities >= threshold of total.
    
    Returns (pareto_count, pareto_ratio).
    """
    if shares.sum() == 0 or len(shares) == 0:
        return (0, 0.0)
    
    sorted_shares = shares.sort_values(ascending=False)
    cumsum = sorted_shares.cumsum()
    
    for k, cum_val in enumerate(cumsum, 1):
        if cum_val >= threshold:
            return (k, k / len(shares))
    
    return (len(shares), 1.0)


async def compute_concentration_analysis(
    top_n_pct: float = 0.8,
    pre_resolved: Optional[dict] = None,
    segment_by: Optional[str] = None,
) -> str:
    """
    Compute portfolio concentration metrics including Pareto ratio, HHI, and Gini.
    
    Args:
        top_n_pct: Cumulative share threshold for Pareto calculation (default 80%)
        pre_resolved: Optional pre-resolved data bundle from compute_statistical_summary
        segment_by: Optional column name to segment the analysis by (e.g., compute
            concentration of auxiliary dimension values within each hierarchy entity).
            When set, returns per-segment concentration metrics alongside the overall.
        
    Returns:
        JSON string with concentration analysis results
    """
    try:
        if pre_resolved:
            df = pre_resolved["df"].copy()
            time_col = pre_resolved["time_col"]
            metric_col = pre_resolved["metric_col"]
            grain_col = pre_resolved["grain_col"]
            name_col = pre_resolved["name_col"]
            names_map = pre_resolved["names_map"]
            pivot = pre_resolved["pivot"].copy()
        else:
            from ...data_cache import resolve_data_and_columns
            try:
                df, time_col, metric_col, grain_col, name_col, ctx = resolve_data_and_columns("ConcentrationAnalysis")
            except ValueError as e:
                return json.dumps({"error": str(e)}, indent=2)
            df[metric_col] = pd.to_numeric(df[metric_col], errors='coerce').fillna(0)
            names_map = dict(zip(df[grain_col], df[name_col]))
            pivot = df.pivot_table(
                index=grain_col,
                columns=time_col,
                values=metric_col,
                aggfunc='sum',
                fill_value=0
            )
            pivot = pivot.reindex(sorted(pivot.columns), axis=1)
        
        total_entities = len(pivot.index)
        total_periods = len(pivot.columns)
        
        if total_entities < 2:
            return json.dumps({
                "warning": "TooFewEntities",
                "message": f"Concentration analysis requires at least 2 entities. Only {total_entities} available.",
                "latest_period": {},
                "concentration_trend": {},
                "variance_concentration": {},
                "summary": {"entities_analyzed": total_entities, "periods_analyzed": total_periods}
            }, indent=2)
        
        if total_periods < 2:
            return json.dumps({
                "warning": "InsufficientPeriods",
                "message": f"Concentration analysis requires at least 2 periods. Only {total_periods} available.",
                "latest_period": {},
                "concentration_trend": {},
                "variance_concentration": {},
                "summary": {"entities_analyzed": total_entities, "periods_analyzed": total_periods}
            }, indent=2)
        
        # Period resolution with lag support
        periods = sorted(pivot.columns)
        lag = 0
        if ctx and ctx.contract and ctx.target_metric:
            lag = ctx.contract.get_effective_lag(ctx.target_metric)
        
        effective_latest, _ = resolve_effective_latest_period(periods, lag)
        latest_period_name = str(effective_latest) if effective_latest else "N/A"
        
        # Get values for the effective latest period
        if effective_latest in pivot.columns:
            values = pivot[effective_latest]
        else:
            values = pivot.iloc[:, -1] # Fallback
            
        abs_values = values.abs().sort_values(ascending=False)
        total = abs_values.sum()
        
        if total == 0:
            shares = abs_values * 0
        else:
            shares = abs_values / total
        
        pareto_count, pareto_ratio = _compute_pareto(shares, top_n_pct)
        top_5_share = float(shares.iloc[:5].sum()) if len(shares) >= 5 else float(shares.sum())
        top_10_share = float(shares.iloc[:10].sum()) if len(shares) >= 10 else float(shares.sum())
        hhi = _compute_hhi(shares)
        hhi_label_str = _hhi_label(hhi)
        gini = _compute_gini(abs_values.values)
        
        top_entities = []
        cumulative = 0.0
        for idx, (entity, val) in enumerate(abs_values.items()):
            if idx >= 10:
                break
            share = float(shares.loc[entity])
            cumulative += share
            top_entities.append({
                "item": entity,
                "item_name": names_map.get(entity, entity),
                "value": round(float(val), 2),
                "share": round(share, 4),
                "cumulative_share": round(cumulative, 4)
            })
        
        latest_period_data = {
            "period": latest_period_name,
            "total_entities": total_entities,
            "pareto_count": pareto_count,
            "pareto_ratio": round(pareto_ratio, 3),
            "pareto_label": f"{pareto_count} of {total_entities} entities ({pareto_ratio*100:.0f}%) account for {top_n_pct*100:.0f}% of total",
            "top_5_share": round(top_5_share, 3),
            "top_10_share": round(top_10_share, 3),
            "hhi": round(hhi, 1),
            "hhi_label": hhi_label_str,
            "gini": round(gini, 3),
            "top_entities": top_entities
        }
        
        hhi_values = []
        gini_values = []
        
        for period in pivot.columns:
            period_values = pivot[period].abs()
            period_total = period_values.sum()
            if period_total > 0:
                period_shares = period_values / period_total
                period_hhi = _compute_hhi(period_shares)
                period_gini = _compute_gini(period_values.values)
            else:
                period_hhi = 0.0
                period_gini = 0.0
            hhi_values.append({"period": str(period), "hhi": round(period_hhi, 1)})
            gini_values.append({"period": str(period), "gini": round(period_gini, 3)})
        
        concentration_trend = {
            "hhi_values": hhi_values,
            "gini_values": gini_values
        }
        
        if total_periods >= 6:
            hhi_array = np.array([v["hhi"] for v in hhi_values])
            gini_array = np.array([v["gini"] for v in gini_values])
            x = np.arange(len(hhi_array))
            
            try:
                hhi_lr = scipy_stats.linregress(x, hhi_array)
                concentration_trend["hhi_slope"] = round(float(hhi_lr.slope), 2)
                concentration_trend["hhi_slope_p_value"] = round(float(hhi_lr.pvalue), 4) if not np.isnan(hhi_lr.pvalue) else 1.0
                concentration_trend["hhi_direction"] = "increasing" if hhi_lr.slope > 0 else "decreasing" if hhi_lr.slope < 0 else "stable"
            except Exception:
                concentration_trend["hhi_slope"] = 0.0
                concentration_trend["hhi_slope_p_value"] = 1.0
                concentration_trend["hhi_direction"] = "stable"
            
            try:
                gini_lr = scipy_stats.linregress(x, gini_array)
                concentration_trend["gini_slope"] = round(float(gini_lr.slope), 4)
                concentration_trend["gini_direction"] = "increasing" if gini_lr.slope > 0 else "decreasing" if gini_lr.slope < 0 else "stable"
            except Exception:
                concentration_trend["gini_slope"] = 0.0
                concentration_trend["gini_direction"] = "stable"
        else:
            concentration_trend["warning"] = "InsufficientPeriodsForTrend"
            concentration_trend["message"] = f"Trend analysis requires at least 6 periods. Only {total_periods} available."
        
        deltas = pivot.diff(axis=1).iloc[:, 1:]
        abs_deltas = deltas.abs()
        total_abs_delta_per_entity = abs_deltas.sum(axis=1).sort_values(ascending=False)
        
        variance_total = total_abs_delta_per_entity.sum()
        if variance_total > 0:
            variance_shares = total_abs_delta_per_entity / variance_total
            variance_pareto_count, variance_pareto_ratio = _compute_pareto(variance_shares, top_n_pct)
            variance_top_5_share = float(variance_shares.iloc[:5].sum()) if len(variance_shares) >= 5 else float(variance_shares.sum())
        else:
            variance_pareto_count = 0
            variance_pareto_ratio = 0.0
            variance_top_5_share = 0.0
        
        top5_counts = {}
        num_delta_periods = len(abs_deltas.columns)
        
        for col in abs_deltas.columns:
            period_deltas = abs_deltas[col]
            top5_entities = period_deltas.nlargest(5).index.tolist()
            for entity in top5_entities:
                top5_counts[entity] = top5_counts.get(entity, 0) + 1
        
        persistent_threshold = num_delta_periods * 0.5 if num_delta_periods > 0 else 0
        persistent_top_movers = []
        for entity, count in sorted(top5_counts.items(), key=lambda x: x[1], reverse=True):
            if count >= persistent_threshold and count > 0:
                persistent_top_movers.append({
                    "item": entity,
                    "item_name": names_map.get(entity, entity),
                    "times_in_top_5": count,
                    "out_of_periods": num_delta_periods
                })
        
        variance_concentration = {
            "pareto_count": variance_pareto_count,
            "pareto_ratio": round(variance_pareto_ratio, 3),
            "pareto_label": f"{variance_pareto_count} of {total_entities} entities ({variance_pareto_ratio*100:.0f}%) drive {top_n_pct*100:.0f}% of period-over-period variance",
            "top_5_variance_share": round(variance_top_5_share, 3),
            "persistent_top_movers": persistent_top_movers[:10]
        }
        
        if hhi < 1500:
            concentration_level = "unconcentrated"
        elif hhi < 2500:
            concentration_level = "moderate"
        else:
            concentration_level = "high"
        
        concentration_trending = concentration_trend.get("hhi_direction", "unknown")
        if "warning" in concentration_trend:
            concentration_trending = "insufficient_data"
        
        summary = {
            "entities_analyzed": total_entities,
            "periods_analyzed": total_periods,
            "concentration_level": concentration_level,
            "concentration_trending": concentration_trending
        }
        
        print(f"[ConcentrationAnalysis] {total_entities} entities, HHI={hhi:.0f}, Gini={gini:.3f}, Pareto={pareto_count}/{total_entities}")
        
        result = {
            "latest_period": latest_period_data,
            "concentration_trend": concentration_trend,
            "variance_concentration": variance_concentration,
            "summary": summary
        }

        # Segmented analysis: compute concentration within each segment
        if segment_by and segment_by in df.columns and df[segment_by].nunique() > 1:
            segmented = {}
            latest_period_col = pivot.columns[-1] if len(pivot.columns) else None
            for seg_val, seg_df in df.groupby(segment_by):
                seg_pivot = seg_df.pivot_table(
                    index=grain_col, columns=time_col, values=metric_col,
                    aggfunc="sum", fill_value=0,
                )
                if seg_pivot.empty or len(seg_pivot) < 2:
                    continue
                seg_pivot = seg_pivot.reindex(sorted(seg_pivot.columns), axis=1)
                latest_col = seg_pivot.columns[-1]
                latest_vals = seg_pivot[latest_col].abs()
                seg_total = float(latest_vals.sum()) or 1e-9
                shares = latest_vals / seg_total
                seg_hhi = _compute_hhi(shares)
                seg_gini = _compute_gini(latest_vals.values)
                seg_pareto_count, seg_pareto_ratio = _compute_pareto(shares, top_n_pct)
                segmented[str(seg_val)] = {
                    "entities": int(len(seg_pivot)),
                    "hhi": round(seg_hhi, 1),
                    "gini": round(seg_gini, 3),
                    "pareto_count": seg_pareto_count,
                    "pareto_ratio": round(seg_pareto_ratio, 3),
                    "concentration_label": _hhi_label(seg_hhi),
                }
            if segmented:
                result["segmented_concentration"] = segmented
        
        return json.dumps(result, indent=2)
        
    except Exception as e:
        return json.dumps({
            "error": "ConcentrationAnalysisFailed",
            "message": f"Failed to compute concentration analysis: {str(e)}",
            "latest_period": {},
            "concentration_trend": {},
            "variance_concentration": {},
            "summary": {}
        }, indent=2)
