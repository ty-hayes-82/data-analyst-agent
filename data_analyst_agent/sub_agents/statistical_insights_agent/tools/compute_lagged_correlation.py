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
Lagged Cross-Correlation Tool

Identifies leading indicators by computing time-lagged cross-correlations
across different metrics.
"""

import pandas as pd
import numpy as np
from scipy.stats import pearsonr
from typing import Dict, Any, List, Optional
import json
from ....utils.temporal_grain import normalize_temporal_grain, temporal_grain_to_period_unit

async def compute_lagged_correlation(
    max_lag: int = 6,
    min_r: float = 0.5,
    granger_test: bool = False,
    granger_max_lag: int = 3,
    pre_resolved: Optional[dict] = None
) -> str:
    """Compute time-lagged cross-correlations to identify leading indicators.
    
    This tool tests whether one metric predicts another at a time lag. It computes
    cross-correlation functions (CCF) for all metric pairs at different lags to
    find relationships like "Orders at time t predict Revenue at time t+2".
    
    Leading indicators are valuable for:
        - Forecasting (use today's Orders to predict next month's Revenue)
        - Early warning systems (detect problems before they manifest)
        - Causal inference (though correlation ≠ causation, leading indicators
          suggest possible causal pathways)
    
    Optionally includes Granger Causality tests for stronger causal evidence.
    
    Use Cases:
        - Supply chain: Shipments lead delivered revenue by 2 weeks
        - Marketing: Ad spend leads conversions by 1 week
        - Retail: Foot traffic leads sales by same day
        - Finance: Expenses lead cash flow by 30 days
    
    Args:
        max_lag: Maximum lag to test (in periods). Default 6.
            Tests lags from -max_lag to +max_lag.
            Positive lag: metric_a at t predicts metric_b at t+lag (a leads b).
            Negative lag: metric_b leads metric_a.
        min_r: Minimum correlation coefficient to report a leading indicator.
            Default 0.5. Only reports relationships where lagged correlation
            exceeds this threshold AND is at least 0.1 better than lag-0 correlation.
        granger_test: If True, includes Granger Causality tests for each
            leading indicator. Default False.
            Requires statsmodels. Adds computational cost but provides stronger
            evidence of predictive relationships.
        granger_max_lag: Maximum lag for Granger Causality tests. Default 3.
            Only used if granger_test=True.
        pre_resolved: Pre-resolved data bundle from compute_statistical_summary.
            If provided, skips data resolution. Must contain:
            - ctx: ADK context with contract and temporal metadata
    
    Returns:
        JSON string with:
            leading_indicators: List of {
                leader: Metric name that leads
                follower: Metric name that follows
                optimal_lag: Best lag (in periods)
                lag_r: Correlation at optimal lag
                contemporaneous_r: Correlation at lag 0
                improvement: lag_r - |contemporaneous_r|
                direction: Human-readable description
                lag_unit: Temporal unit (e.g., "month", "week")
                granger_causality (optional): {p_value, significant}
            }
            cross_correlation_functions: Dict mapping metric pairs to {
                lags: List of lag values
                correlations: List of correlation values at each lag
            }
            summary: {
                metrics_analyzed, leading_pairs_found, strongest_leader,
                temporal_grain, lag_unit
            }
        
        Or {"skipped": True, "reason": "..."} or {"error": "..."}
    
    Raises:
        ValueError: Via resolve_data_and_columns if pre_resolved not provided
            and context/data resolution fails.
    
    Example:
        >>> result = await compute_lagged_correlation(max_lag=4, granger_test=True)
        >>> # Returns: {
        >>> #   "leading_indicators": [{
        >>> #     "leader": "orders",
        >>> #     "follower": "revenue",
        >>> #     "optimal_lag": 2,
        >>> #     "lag_r": 0.87,
        >>> #     "contemporaneous_r": 0.65,
        >>> #     "improvement": 0.22,
        >>> #     "direction": "orders leads revenue by 2 months",
        >>> #     "lag_unit": "month",
        >>> #     "granger_causality": {"p_value": 0.003, "significant": true}
        >>> #   }],
        >>> #   "summary": {
        >>> #     "strongest_leader": {...},
        >>> #     "temporal_grain": "monthly"
        >>> #   }
        >>> # }
        
        >>> # Interpretation: Orders today predict Revenue 2 months later
        >>> # with r=0.87 (improvement of 0.22 over same-period correlation).
        >>> # Granger test confirms predictive relationship (p<0.01).
    
    Note:
        - Requires scipy (pip install scipy)
        - Requires statsmodels for Granger tests (pip install statsmodels)
        - Requires 12+ periods for reliable results (less than 12 periods triggers skip)
        - Loads ALL metrics via validation_data_loader (not filtered to current target)
        - Temporal grain (monthly/weekly) detected from contract or context
        - Lag unit derived from temporal grain for human-readable output
        - Granger Causality interpretation:
          * p < 0.05: Significant evidence that leader predicts follower
          * p ≥ 0.05: No significant predictive relationship
        - "Improvement" threshold of 0.1 ensures lagged correlation is meaningfully
          better than contemporaneous correlation
    """
    from ....tools.validation_data_loader import load_validation_data

    try:
        include_granger = bool(granger_test)
        try:
            from config.statistical_analysis_config import get_tool_options
            lagged_options = get_tool_options("lagged_correlation")
            if isinstance(lagged_options, dict) and "include_granger" in lagged_options:
                include_granger = bool(lagged_options.get("include_granger"))
        except Exception:
            pass

        if pre_resolved:
            ctx = pre_resolved["ctx"]
        else:
            from ...data_cache import resolve_data_and_columns
            try:
                df_target, time_col, metric_col, grain_col, name_col, ctx = resolve_data_and_columns("LaggedCorrelation")
            except ValueError as e:
                return json.dumps({"error": str(e)}, indent=2)

        if not ctx or not ctx.contract:
            return json.dumps({"error": "No dataset contract available"}, indent=2)

        contract = ctx.contract
        temporal_grain = normalize_temporal_grain(getattr(ctx, "temporal_grain", None))
        if temporal_grain == "unknown":
            time_cfg = getattr(contract, "time", None)
            temporal_grain = normalize_temporal_grain(getattr(time_cfg, "frequency", None))
            if temporal_grain == "unknown":
                temporal_grain = "monthly"
        lag_unit = temporal_grain_to_period_unit(temporal_grain)
        if lag_unit == "period":
            lag_unit = "month"
        available_metrics = [m for m in contract.metrics]

        if len(available_metrics) <= 1:
            return json.dumps({"skipped": True, "reason": "Single-metric dataset"}, indent=2)

        # 2. Load all metrics data
        metric_names = [m.name for m in available_metrics]
        df_all = load_validation_data(metric_filter=metric_names)
        
        if df_all.empty:
            return json.dumps({"error": "No data found for metrics"}, indent=2)

        # 3. Pivot to (period) x (metric) matrix, aggregated across all entities
        df_all["value"] = pd.to_numeric(df_all["value"], errors="coerce").fillna(0)
        # Use contract-defined time column
        time_col_to_use = contract.time.column if contract.time else "period"
        # Validate the column exists in the dataframe
        if time_col_to_use not in df_all.columns:
            time_col_to_use = "period" if "period" in df_all.columns else df_all.columns[0]
        metric_pivot = df_all.pivot_table(
            index=time_col_to_use,
            columns="metric",
            values="value",
            aggfunc="sum"
        ).sort_index()

        # Check for sufficient periods
        if len(metric_pivot) < 12:
            return json.dumps({"skipped": True, "reason": f"Insufficient periods ({len(metric_pivot)} < 12) for lagged analysis"}, indent=2)

        cols = list(metric_pivot.columns)
        n = len(cols)
        
        leading_indicators = []
        lagging_indicators = []
        contemporaneous = []
        ccf_functions = {}

        # 4. Compute lagged correlations for each pair
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                
                m_a, m_b = cols[i], cols[j]
                
                lags = list(range(-max_lag, max_lag + 1))
                corrs = []
                
                best_lag = 0
                max_abs_r = 0.0
                
                for lag in lags:
                    if lag == 0:
                        series_a = metric_pivot[m_a]
                        series_b = metric_pivot[m_b]
                    elif lag > 0:
                        # A leads B (A at time t predicts B at time t+lag)
                        # Shift B backward or A forward
                        series_a = metric_pivot[m_a].iloc[:-lag]
                        series_b = metric_pivot[m_b].iloc[lag:]
                    else:
                        # B leads A (lag is negative)
                        # Shift A backward or B forward
                        abs_lag = abs(lag)
                        series_a = metric_pivot[m_a].iloc[abs_lag:]
                        series_b = metric_pivot[m_b].iloc[:-abs_lag]
                    
                    # Compute pearsonr
                    valid_mask = ~(series_a.isna() | series_b.isna())
                    if len(series_a[valid_mask]) >= 6:
                        r_val, _ = pearsonr(series_a[valid_mask], series_b[valid_mask])
                        if np.isnan(r_val): r_val = 0.0
                    else:
                        r_val = 0.0
                    
                    corrs.append(round(float(r_val), 4))
                    if abs(r_val) > max_abs_r:
                        max_abs_r = abs(r_val)
                        best_lag = lag
                
                # Filter to significant leading indicators
                lag0_r = corrs[lags.index(0)]
                
                # Significant improvement check (at least 0.1 improvement over lag 0)
                if max_abs_r >= min_r and (max_abs_r - abs(lag0_r)) >= 0.1:
                    # If i < j, store the CCF
                    if i < j:
                        ccf_functions[f"{m_a}_vs_{m_b}"] = {
                            "lags": lags,
                            "correlations": corrs
                        }
                    
                    # Only add once (A leads B or B leads A)
                    # If best_lag > 0, m_a leads m_b
                    # If best_lag < 0, m_b leads m_a
                    
                    # We'll just add it as a leading indicator from the perspective of the leader
                    if best_lag > 0:
                        indicator = {
                            "leader": m_a,
                            "follower": m_b,
                            "optimal_lag": best_lag,
                            "lag_r": round(float(np.sign(lag0_r) * max_abs_r if lag0_r != 0 else max_abs_r), 4),
                            "contemporaneous_r": round(float(lag0_r), 4),
                            "improvement": round(float(max_abs_r - abs(lag0_r)), 4),
                            "direction": f"{m_a} leads {m_b} by {best_lag} {lag_unit}{'s' if best_lag > 1 else ''}",
                            "lag_unit": lag_unit,
                        }
                        
                        # Granger Causality (optional)
                        if include_granger:
                            try:
                                from statsmodels.tsa.stattools import grangercausalitytests
                                # grangercausalitytests expects [y, x] where x leads y
                                data = metric_pivot[[m_b, m_a]].dropna()
                                res = grangercausalitytests(data, maxlag=granger_max_lag, verbose=False)
                                
                                # Use the best p-value across lags
                                p_values = [res[lag][0]['ssr_ftest'][1] for lag in range(1, granger_max_lag + 1)]
                                min_p = min(p_values)
                                indicator["granger_causality"] = {
                                    "p_value": round(float(min_p), 6),
                                    "significant": bool(min_p < 0.05)
                                }
                            except Exception:
                                pass
                        
                        leading_indicators.append(indicator)

        result = {
            "leading_indicators": leading_indicators,
            "cross_correlation_functions": ccf_functions,
            "summary": {
                "metrics_analyzed": n,
                "leading_pairs_found": len(leading_indicators),
                "strongest_leader": leading_indicators[0] if leading_indicators else None,
                "temporal_grain": temporal_grain,
                "lag_unit": lag_unit,
            },
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        import traceback
        return json.dumps({
            "error": f"Failed to compute lagged correlation: {str(e)}",
            "traceback": traceback.format_exc()
        }, indent=2)
