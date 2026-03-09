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
Distribution Shape Analysis Tool.

Analyzes skewness, kurtosis, and normality of metric distributions
to validate statistical assumptions and detect hidden patterns.
"""

import pandas as pd
import numpy as np
import json
from typing import Dict, Any, List, Optional
from scipy import stats as scipy_stats


async def compute_distribution_analysis(
    top_n: int = 15,
    test_bimodality: bool = True,
    pre_resolved: Optional[dict] = None
) -> str:
    """
    Analyze the distributional properties of metric data.
    """
    try:
        if pre_resolved:
            df = pre_resolved["df"].copy()
            time_col = pre_resolved["time_col"]
            metric_col = pre_resolved["metric_col"]
            grain_col = pre_resolved["grain_col"]
            name_col = pre_resolved["name_col"]
            pivot = pre_resolved["pivot"].copy()
            names_map = pre_resolved["names_map"]
        else:
            from ...data_cache import resolve_data_and_columns
            try:
                df, time_col, metric_col, grain_col, name_col, ctx = resolve_data_and_columns("DistributionAnalysis")
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
            names_map = dict(zip(df[grain_col], df[name_col]))
        
        # 3. Analyze per-item distributions (Time-series)
        # Select top N items by average magnitude
        top_items = pivot.abs().mean(axis=1).sort_values(ascending=False).head(top_n).index
        
        item_distributions = []
        for item in top_items:
            vals = pivot.loc[item].values
            if len(vals) < 8: continue # Need enough points for meaningful distribution
            
            skew = float(scipy_stats.skew(vals))
            kurt = float(scipy_stats.kurtosis(vals))
            
            # Normality test
            if len(vals) <= 50:
                stat, p_val = scipy_stats.shapiro(vals)
            else:
                stat, p_val = scipy_stats.normaltest(vals)
            
            is_normal = p_val > 0.05 and abs(skew) < 0.5 and abs(kurt) < 1.0
            
            classifications = []
            if skew > 0.5: classifications.append("skewed_right")
            elif skew < -0.5: classifications.append("skewed_left")
            
            if kurt > 1.0: classifications.append("heavy_tailed")
            elif kurt < -1.0: classifications.append("light_tailed")
            
            if not classifications and is_normal:
                classifications.append("normal")
            elif not classifications:
                classifications.append("near_normal")

            quantiles = {
                f"p{int(q*100)}": float(np.quantile(vals, q))
                for q in [0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95]
            }
            
            mean_val = float(np.mean(vals))
            median_val = float(np.median(vals))
            
            item_distributions.append({
                "item": str(item),
                "item_name": names_map.get(item, str(item)),
                "n_observations": len(vals),
                "skewness": round(skew, 3),
                "excess_kurtosis": round(kurt, 3),
                "normality_p_value": round(float(p_val), 4),
                "is_normal": bool(is_normal),
                "classification": ", ".join(classifications),
                "quantiles": quantiles,
                "median_vs_mean": {
                    "mean": round(mean_val, 2),
                    "median": round(median_val, 2),
                    "ratio": round(mean_val / median_val, 3) if median_val != 0 else 0
                },
                "z_score_reliability": "high" if is_normal else "low" if abs(skew) > 1.0 or abs(kurt) > 2.0 else "medium"
            })

        # 4. Cross-sectional Analysis (Latest Period)
        latest_period = pivot.columns[-1]
        cs_vals = pivot[latest_period].values
        
        cs_skew = float(scipy_stats.skew(cs_vals))
        cs_kurt = float(scipy_stats.kurtosis(cs_vals))
        
        if len(cs_vals) <= 50:
            cs_stat, cs_p_val = scipy_stats.shapiro(cs_vals)
        else:
            cs_stat, cs_p_val = scipy_stats.normaltest(cs_vals)
            
        # Bimodality detection
        bimodal_info = {"detected": False}
        if test_bimodality and len(cs_vals) >= 10:
            # Bimodality Coefficient: (skew^2 + 1) / (kurt + 3 * (n-1)^2 / ((n-2)*(n-3)))
            # Simplified BC = (skew^2 + 1) / (kurt + 3)
            # BC > 0.555 suggests bimodality
            bc = (cs_skew**2 + 1) / (cs_kurt + 3)
            if bc > 0.555:
                bimodal_info = {
                    "detected": True,
                    "bimodality_coefficient": round(bc, 3),
                    "interpretation": "Distribution suggests multiple distinct operating modes or clusters."
                }

        # 5. Validity Warnings
        validity_warnings = []
        for dist in item_distributions:
            if dist["z_score_reliability"] == "low":
                validity_warnings.append({
                    "item": dist["item"],
                    "item_name": dist["item_name"],
                    "warning": f"Strongly non-normal distribution (skew={dist['skewness']}, kurt={dist['excess_kurtosis']}).",
                    "recommendation": "Z-score-based anomalies may be unreliable; prioritize MAD-based detection."
                })

        result = {
            "item_distributions": item_distributions,
            "cross_sectional": {
                "latest_period": str(latest_period),
                "skewness": round(cs_skew, 3),
                "excess_kurtosis": round(cs_kurt, 3),
                "is_normal": bool(cs_p_val > 0.05 and abs(cs_skew) < 0.5 and abs(cs_kurt) < 1.0),
                "bimodal": bimodal_info
            },
            "validity_warnings": validity_warnings,
            "summary": {
                "items_analyzed": len(item_distributions),
                "normal_count": len([d for d in item_distributions if d["is_normal"]]),
                "non_normal_count": len([d for d in item_distributions if not d["is_normal"]]),
                "dominant_classification": pd.Series([d["classification"] for d in item_distributions]).mode()[0] if item_distributions else "N/A"
            }
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        import traceback
        return json.dumps({
            "error": f"Failed to compute distribution analysis: {str(e)}",
            "traceback": traceback.format_exc()
        }, indent=2)
