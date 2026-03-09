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
Cross-Metric Correlation Tool

Computes pairwise correlations across different metrics in the dataset
to surface operational-financial linkages.
"""

import pandas as pd
import numpy as np
from scipy.stats import pearsonr
from typing import Dict, Any, List, Optional
import json

async def compute_cross_metric_correlation(
    min_r: float = 0.5,
    max_p: float = 0.10,
    include_derived: bool = True,
    per_dimension: bool = False,
    pre_resolved: Optional[dict] = None,
) -> str:
    """
    Compute pairwise correlations across different metrics.
    """
    from ...data_cache import resolve_data_and_columns
    from ....tools.validation_data_loader import load_validation_data

    try:
        # 1. Get current context to see what metrics we have
        if pre_resolved:
            ctx = pre_resolved["ctx"]
        else:
            try:
                df_target, time_col, metric_col, grain_col, name_col, ctx = resolve_data_and_columns("CrossMetricCorrelation")
            except ValueError as e:
                return json.dumps({"error": str(e)}, indent=2)

        if not ctx or not ctx.contract:
            return json.dumps({"error": "No dataset contract available"}, indent=2)

        contract = ctx.contract
        available_metrics = [m for m in contract.metrics if include_derived or (m.type or "").lower() not in ("derived", "ratio")]

        if len(available_metrics) <= 1:
            return json.dumps({"skipped": True, "reason": "Single-metric dataset"}, indent=2)

        # 2. Load all metrics data
        metric_names = [m.name for m in available_metrics]
        # We need all metrics for the terminals in the current analysis
        # load_validation_data can load multiple metrics
        df_all = load_validation_data(metric_filter=metric_names)
        
        if df_all.empty:
            return json.dumps({"error": "No data found for metrics"}, indent=2)

        # 3. Pivot to (period) x (metric) matrix, aggregated across all entities
        # Ensure 'value' is numeric
        df_all["value"] = pd.to_numeric(df_all["value"], errors="coerce").fillna(0)
        
        # Aggregate across all terminals per period and metric
        metric_pivot = df_all.pivot_table(
            index="week_ending",
            columns="metric",
            values="value",
            aggfunc="sum"
        ).sort_index()

        # Check for sufficient periods
        if len(metric_pivot) < 6:
            return json.dumps({"skipped": True, "reason": f"Insufficient periods ({len(metric_pivot)} < 6)"}, indent=2)

        # 4. Compute correlation matrix
        cols = metric_pivot.columns
        n = len(cols)
        corr_matrix = np.zeros((n, n))
        p_matrix = np.zeros((n, n))

        significant_pairs = []
        
        # Helper to classify relationship
        def classify_pair(m_a: str, m_b: str, r: float) -> tuple:
            classification = "moderate"
            if abs(r) >= 0.8:
                classification = "strong"
            
            direction = "positive" if r > 0 else "negative"
            label = f"{classification}_{direction}"
            
            # Check if expected
            metric_a = contract.get_metric(m_a)
            metric_b = contract.get_metric(m_b)
            
            expected = False
            relationship = None
            
            # 1. Dependency check
            deps_a = (metric_a.depends_on or []) + (metric_a.derived_from or [])
            deps_b = (metric_b.depends_on or []) + (metric_b.derived_from or [])
            
            if m_b in deps_a or m_a in deps_b:
                expected = True
                relationship = f"{m_a if m_b in deps_a else m_b} is derived from {m_b if m_b in deps_a else m_a}"
            
            # 2. PVM role check
            if metric_a.pvm_role and metric_b.pvm_role:
                if (metric_a.pvm_role == "total" and metric_b.pvm_role in ("price", "volume")) or \
                   (metric_b.pvm_role == "total" and metric_a.pvm_role in ("price", "volume")):
                    expected = True
                    relationship = f"PVM relationship: {metric_a.pvm_role} vs {metric_b.pvm_role}"

            return label, expected, relationship

        for i in range(n):
            for j in range(n):
                if i == j:
                    corr_matrix[i, j] = 1.0
                    p_matrix[i, j] = 0.0
                    continue
                
                # Drop NaNs
                valid_mask = ~(metric_pivot.iloc[:, i].isna() | metric_pivot.iloc[:, j].isna())
                series_i = metric_pivot.iloc[:, i][valid_mask]
                series_j = metric_pivot.iloc[:, j][valid_mask]
                
                if len(series_i) < 6:
                    corr_matrix[i, j] = 0.0
                    p_matrix[i, j] = 1.0
                    continue
                    
                r_val, p_val = pearsonr(series_i, series_j)
                corr_matrix[i, j] = r_val
                p_matrix[i, j] = p_val
                
                if i < j and abs(r_val) >= min_r and p_val <= max_p:
                    m_a, m_b = cols[i], cols[j]
                    classification, expected, relationship = classify_pair(m_a, m_b, r_val)
                    
                    significant_pairs.append({
                        "metric_a": m_a,
                        "metric_b": m_b,
                        "r": round(float(r_val), 4),
                        "p_value": round(float(p_val), 6),
                        "classification": classification,
                        "expected": expected,
                        "relationship": relationship
                    })

        # 5. Dimension outliers (optional)
        dimension_outliers = []
        if per_dimension:
            # For each terminal, compute the same correlations and see where they deviate from the population
            # Filter to just the significant pairs for performance
            terminals = df_all["terminal"].unique()
            for pair in significant_pairs:
                m_a = pair["metric_a"]
                m_b = pair["metric_b"]
                pop_r = pair["r"]
                
                for term in terminals:
                    term_df = df_all[(df_all["terminal"] == term) & (df_all["metric"].isin([m_a, m_b]))]
                    term_pivot = term_df.pivot_table(index="week_ending", columns="metric", values="value", aggfunc="sum")
                    
                    if len(term_pivot) >= 6 and m_a in term_pivot.columns and m_b in term_pivot.columns:
                        valid_mask = ~(term_pivot[m_a].isna() | term_pivot[m_b].isna())
                        s_a = term_pivot[m_a][valid_mask]
                        s_b = term_pivot[m_b][valid_mask]
                        
                        if len(s_a) >= 6:
                            term_r, _ = pearsonr(s_a, s_b)
                            # If population is strongly correlated (>0.8) but terminal is not (<0.3 or opposite sign)
                            if abs(pop_r) >= 0.8 and (abs(term_r) < 0.3 or np.sign(term_r) != np.sign(pop_r)):
                                dimension_outliers.append({
                                    "dimension_value": term,
                                    "metric_a": m_a,
                                    "metric_b": m_b,
                                    "r": round(float(term_r), 4),
                                    "population_r": round(float(pop_r), 4),
                                    "deviation": f"Correlation breakdown -- {m_a} decoupled from {m_b} at this terminal"
                                })

        result = {
            "matrix": {
                "metrics": list(cols),
                "correlations": corr_matrix.tolist(),
                "p_values": p_matrix.tolist()
            },
            "significant_pairs": significant_pairs,
            "unexpected_pairs": [p for p in significant_pairs if not p["expected"]],
            "dimension_outliers": dimension_outliers[:20],  # Limit to top 20
            "summary": {
                "metrics_analyzed": n,
                "significant_pairs": len(significant_pairs),
                "unexpected_pairs": len([p for p in significant_pairs if not p["expected"]]),
                "dimension_outliers": len(dimension_outliers)
            }
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        import traceback
        return json.dumps({
            "error": f"Failed to compute cross-metric correlation: {str(e)}",
            "traceback": traceback.format_exc()
        }, indent=2)
