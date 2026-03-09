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
Variance Decomposition Tool (ANOVA / Shapley Attribution).

Quantifies what percentage of total variance is explained by each dimension
(LOB, Terminal, Time, Interaction effects).
"""

import pandas as pd
import numpy as np
import json
from typing import Dict, Any, List, Optional
from statsmodels.formula.api import ols
from statsmodels.stats.anova import anova_lm


async def compute_variance_decomposition(
    dimensions: Optional[List[str]] = None,
    include_interactions: bool = True,
    method: str = "anova",
    pre_resolved: Optional[dict] = None,
    hierarchy_dim: Optional[str] = None,
    auxiliary_dim: Optional[str] = None,
) -> str:
    """
    Compute variance decomposition for available dimensions.

    Args:
        dimensions: Specific dimensions to include. If None, auto-detected.
        include_interactions: Whether to include pairwise interactions.
        method: Attribution method ("anova" or "shapley" -- shapley is simplified).
        pre_resolved: Optional pre-resolved data bundle from compute_statistical_summary.
        hierarchy_dim: Explicit hierarchy dimension column for pair mode.
        auxiliary_dim: Explicit auxiliary dimension column for pair mode.
            When both hierarchy_dim and auxiliary_dim are set, only these two
            dimensions are used (with interaction).
    """
    try:
        if pre_resolved:
            df_target = pre_resolved["df"].copy()
            time_col = pre_resolved["time_col"]
            metric_col = pre_resolved["metric_col"]
            grain_col = pre_resolved["grain_col"]
            name_col = pre_resolved["name_col"]
            ctx = pre_resolved["ctx"]
        else:
            from ...data_cache import resolve_data_and_columns
            try:
                df_target, time_col, metric_col, grain_col, name_col, ctx = resolve_data_and_columns("VarianceDecomposition")
            except ValueError as e:
                return json.dumps({"error": str(e)}, indent=2)

        if not ctx or not ctx.contract:
            return json.dumps({"error": "No dataset contract available"}, indent=2)

        contract = ctx.contract

        # Explicit pair mode: only use hierarchy_dim + auxiliary_dim
        if hierarchy_dim and auxiliary_dim:
            pair_dims = [d for d in [hierarchy_dim, auxiliary_dim] if d in df_target.columns]
            if len(pair_dims) == 2:
                analysis_dims = pair_dims
                include_interactions = True
            else:
                missing = [d for d in [hierarchy_dim, auxiliary_dim] if d not in df_target.columns]
                return json.dumps({
                    "skipped": True,
                    "reason": f"Pair mode columns not in data: {missing}",
                }, indent=2)
        elif dimensions:
            analysis_dims = [d for d in dimensions if d in df_target.columns]
        else:
            analysis_dims = [time_col, grain_col]
            potential_dims = [c for c in df_target.columns if c not in [metric_col, time_col, grain_col, name_col, "period_index", "value"]]
            analysis_dims += [d for d in potential_dims if df_target[d].nunique() > 1]

        # Ensure unique and exist
        analysis_dims = list(set(analysis_dims))
        
        if len(analysis_dims) < 1:
            return json.dumps({"skipped": True, "reason": "Insufficient dimensions for decomposition"}, indent=2)

        # 2. Prepare data for ANOVA
        # Ensure metric is numeric
        df_target[metric_col] = pd.to_numeric(df_target[metric_col], errors="coerce").fillna(0)
        
        # Filter to only needed columns and drop NaNs (normalize to "value" for formula)
        df_anova = df_target[analysis_dims + [metric_col]].dropna()
        if metric_col != "value":
            df_anova = df_anova.rename(columns={metric_col: "value"})
        
        # If we have too many observations, we might want to sample, but usually it's fine
        if len(df_anova) < 10:
             return json.dumps({"skipped": True, "reason": f"Insufficient data ({len(df_anova)} rows)"}, indent=2)

        # 3. Build Formula for OLS
        # We'll sanitize column names for statsmodels formula
        def sanitize(c):
            return f"Q('{c}')"

        # Main effects
        main_effects = " + ".join([sanitize(d) for d in analysis_dims])
        formula = f"value ~ {main_effects}"
        
        # Interactions (only if we have at least 2 dimensions)
        interactions_list = []
        if include_interactions and len(analysis_dims) >= 2:
            # Pairwise interactions only to avoid combinatorial explosion
            for i in range(len(analysis_dims)):
                for j in range(i + 1, len(analysis_dims)):
                    interactions_list.append(f"{sanitize(analysis_dims[i])}:{sanitize(analysis_dims[j])}")
            
            if interactions_list:
                formula += " + " + " + ".join(interactions_list)

        # 4. Run ANOVA
        try:
            model = ols(formula, data=df_anova).fit()
            table = anova_lm(model, typ=2) # Type II Sum of Squares
        except Exception as inner_e:
            # Fallback: simple one-way ANOVA per dimension if complex formula fails
            # (e.g., due to sparse interaction cells)
            return await _compute_simple_one_way_fallback(df_anova, analysis_dims, inner_e)

        # 5. Extract Contributions (Eta-Squared)
        total_ss = table['sum_sq'].sum()
        
        dimension_contributions = []
        interaction_effects = []
        
        for idx, row in table.iterrows():
            if idx == 'Residual':
                continue
            
            ss = row['sum_sq']
            df_val = row['df']
            f_stat = row['F']
            p_val = row['PR(>F)']
            eta_sq = ss / total_ss
            
            if ":" in str(idx):
                # Interaction
                parts = str(idx).replace("Q('", "").replace("')", "").split(":")
                interaction_effects.append({
                    "dimensions": parts,
                    "eta_squared": round(float(eta_sq), 4),
                    "label": f"{' x '.join(parts)} interaction explains {eta_sq:.1%} of variance",
                    "f_statistic": round(float(f_stat), 2) if not np.isnan(f_stat) else None,
                    "p_value": round(float(p_val), 6) if not np.isnan(p_val) else None
                })
            else:
                # Main effect
                dim_name = str(idx).replace("Q('", "").replace("')", "")
                dimension_contributions.append({
                    "dimension": dim_name,
                    "eta_squared": round(float(eta_sq), 4),
                    "label": f"{dim_name} explains {eta_sq:.1%} of total variance",
                    "f_statistic": round(float(f_stat), 2) if not np.isnan(f_stat) else None,
                    "p_value": round(float(p_val), 6) if not np.isnan(p_val) else None
                })

        residual_ss = table.loc['Residual', 'sum_sq']
        residual_pct = residual_ss / total_ss

        # Summary
        dominant = "residual"
        max_eta = residual_pct
        if dimension_contributions:
            top_dim = max(dimension_contributions, key=lambda x: x['eta_squared'])
            if top_dim['eta_squared'] > max_eta:
                dominant = top_dim['dimension']
                max_eta = top_dim['eta_squared']

        result = {
            "method": "anova_type_2",
            "total_variance_ss": float(total_ss),
            "dimension_contributions": sorted(dimension_contributions, key=lambda x: x['eta_squared'], reverse=True),
            "interaction_effects": sorted(interaction_effects, key=lambda x: x['eta_squared'], reverse=True),
            "residual_variance_pct": round(float(residual_pct), 4),
            "summary": {
                "dominant_dimension": dominant,
                "dominant_pct": round(float(max_eta * 100), 1),
                "recommendation": f"Focus analysis on {dominant if dominant != 'residual' else 'missing factors'}; it explains the largest portion of variance."
            }
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        import traceback
        return json.dumps({
            "error": f"Failed to compute variance decomposition: {str(e)}",
            "traceback": traceback.format_exc()
        }, indent=2)


async def _compute_simple_one_way_fallback(df, dimensions, error_msg) -> str:
    """One-way ANOVA per dimension fallback if multi-way fails."""
    results = []
    total_ss = ((df['value'] - df['value'].mean())**2).sum()
    
    if total_ss == 0:
        return json.dumps({"skipped": True, "reason": "Zero variance in dataset"}, indent=2)

    for dim in dimensions:
        # SSB = sum( n_g * (mean_g - mean_all)^2 )
        group_means = df.groupby(dim)['value'].mean()
        group_counts = df.groupby(dim)['value'].count()
        overall_mean = df['value'].mean()
        
        ssb = sum(group_counts * (group_means - overall_mean)**2)
        eta_sq = ssb / total_ss
        
        results.append({
            "dimension": dim,
            "eta_squared": round(float(eta_sq), 4),
            "label": f"{dim} explains {eta_sq:.1%} (one-way)"
        })

    return json.dumps({
        "method": "one_way_fallback",
        "warning": f"Multi-way ANOVA failed: {str(error_msg)}",
        "dimension_contributions": sorted(results, key=lambda x: x['eta_squared'], reverse=True),
        "residual_variance_pct": round(1.0 - sum(r['eta_squared'] for r in results), 4),
        "summary": {
            "dominant_dimension": results[0]['dimension'] if results else "none",
            "dominant_pct": round(results[0]['eta_squared'] * 100, 1) if results else 0
        }
    }, indent=2)
