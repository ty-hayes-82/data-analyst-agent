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
Seasonal decomposition tool using STL (Seasonal and Trend decomposition using Loess).

Decomposes time series into:
- Trend: Long-term direction
- Seasonal: Recurring patterns (monthly/yearly)
- Residual: What's left (true anomalies)
"""

import json
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional
from statsmodels.tsa.seasonal import seasonal_decompose
from io import StringIO


async def compute_seasonal_decomposition(pre_resolved: Optional[dict] = None) -> str:
    """Decompose time series into trend, seasonal, and residual components using STL.
    
    This tool uses statsmodels' Seasonal and Trend decomposition using Loess (STL)
    to break down each time series into three additive components:
    
    Components:
        - Trend: Long-term directional movement (growth or decline)
        - Seasonal: Recurring patterns (e.g., monthly/yearly cycles)
        - Residual: What's left after removing trend and seasonality (true anomalies)
    
    The residual component is particularly valuable for anomaly detection because
    it isolates unexpected deviations that aren't explained by normal patterns.
    
    Use Cases:
        - Detect true anomalies (residuals beyond 2σ) vs normal seasonal spikes
        - Quantify seasonal patterns (e.g., "December is 15% above annual average")
        - Calculate seasonally-adjusted YoY variance (removes monthly bias)
        - Identify items with strongest/weakest seasonal effects
    
    Args:
        pre_resolved: Pre-resolved data bundle from compute_statistical_summary.
            If provided, skips data resolution. Must contain:
            - df: DataFrame with time series data
            - time_col, metric_col, grain_col, name_col: Column names
            - names_map: Dict mapping grain values to display names
    
    Returns:
        JSON string with:
            seasonal_analysis: Per-item analysis with:
                - periods_analyzed: Number of time periods
                - residual_std/residual_mean: Residual statistics
                - anomaly_count: Count of residuals beyond 2σ
                - seasonal_pattern: Dict mapping month (1-12) to average seasonal component
                - yoy_variance_raw: YoY change including seasonality
                - yoy_variance_seasonal_adjusted: YoY change with seasonality removed
                - seasonal_strength: Ratio of seasonal std to total std
            residual_anomalies: All detected anomalies (|residual| > 2σ)
            top_anomalies: Top 15 anomalies by absolute residual magnitude
            strongest_seasonal_items: Top 5 items by seasonal_strength
            seasonality_summary: Dataset-level {peak_month, trough_month, seasonal_amplitude_pct}
            summary: {
                items_analyzed, total_periods, total_anomalies_detected,
                items_with_anomalies, anomaly_rate_pct
            }
        
        Or {"warning": "InsufficientDataForSeasonal", ...} if <24 periods
        Or {"error": "SeasonalDecompositionFailed", ...} on exception
    
    Raises:
        ValueError: Via resolve_data_and_columns if pre_resolved not provided
            and context/data resolution fails.
    
    Example:
        >>> result = await compute_seasonal_decomposition()
        >>> # Returns: {
        >>> #   "seasonal_analysis": [{
        >>> #     "item": "Store_123",
        >>> #     "seasonal_pattern": {
        >>> #       12: 1500,  # December +$1500 above trend
        >>> #       1: -800,   # January -$800 below trend
        >>> #       ...
        >>> #     },
        >>> #     "seasonal_strength": 0.35,  # 35% of variance is seasonal
        >>> #     "yoy_variance_seasonal_adjusted": 1200,  # True growth after removing seasonal effect
        >>> #   }],
        >>> #   "top_anomalies": [{
        >>> #     "period": "2025-02",
        >>> #     "item": "Store_456",
        >>> #     "residual_z_score": 3.8,  # 3.8σ above expected
        >>> #     "residual_magnitude": 5000  # $5000 unexplained deviation
        >>> #   }]
        >>> # }
    
    Note:
        - Requires statsmodels (pip install statsmodels)
        - Requires 24+ periods (2 years) for reliable seasonal decomposition
        - Uses additive model (seasonal + trend + residual = observed)
        - Seasonal period = 12 (monthly cycles)
        - Residual anomaly threshold = 2 standard deviations
        - Items with <24 observations are skipped
        - Seasonal_strength interpretation:
          * <0.2 = weak seasonality
          * 0.2-0.5 = moderate seasonality
          * >0.5 = strong seasonality
    """
    try:
        if pre_resolved:
            df = pre_resolved["df"].copy()
            time_col = pre_resolved["time_col"]
            metric_col = pre_resolved["metric_col"]
            grain_col = pre_resolved["grain_col"]
            name_col = pre_resolved["name_col"]
            names_map = pre_resolved["names_map"]
        else:
            from ...data_cache import resolve_data_and_columns
            try:
                df, time_col, metric_col, grain_col, name_col, ctx = resolve_data_and_columns("SeasonalDecomposition")
            except ValueError as e:
                return json.dumps({"error": str(e)}, indent=2)
            df[metric_col] = pd.to_numeric(df[metric_col], errors='coerce').fillna(0)
            names_map = dict(zip(df[grain_col], df[name_col]))
        
        # Need at least 24 periods (2 years) for meaningful seasonal decomposition
        periods_available = len(df[time_col].unique())
        if periods_available < 24:
            return json.dumps({
                "warning": "InsufficientDataForSeasonal",
                "message": f"Seasonal decomposition requires at least 24 periods. Only {periods_available} available.",
                "seasonal_analysis": [],
                "residual_anomalies": [],
                "top_anomalies": [],
                "summary": {"items_analyzed": 0, "total_anomalies_detected": 0}
            }, indent=2)
        
        seasonal_results = []
        all_residual_anomalies = []
        
        # Analyze each item
        for item in df[grain_col].unique():
            item_df = df[df[grain_col] == item].copy()
            item_df = item_df.sort_values(time_col)
            
            # Create time series
            item_df['period_date'] = pd.to_datetime(item_df[time_col])
            item_df = item_df.set_index('period_date')
            
            # Need at least 24 observations for seasonal decomposition
            if len(item_df) < 24:
                continue
            
            try:
                # Seasonal decomposition (additive model)
                # period=12 for monthly seasonality
                result = seasonal_decompose(
                    item_df[metric_col],
                    model='additive',
                    period=12,
                    extrapolate_trend='freq'
                )
                
                # Calculate residual statistics
                residual_std = result.resid.std()
                residual_mean = result.resid.mean()
                
                # Flag anomalies: residuals beyond 2 standard deviations
                threshold = 2 * residual_std
                anomaly_mask = abs(result.resid - residual_mean) > threshold
                
                if anomaly_mask.sum() > 0:
                    anomalies_df = item_df[anomaly_mask].copy()
                    anomalies_df['residual'] = result.resid[anomaly_mask]
                    anomalies_df['residual_z_score'] = (result.resid[anomaly_mask] - residual_mean) / residual_std
                    
                    # Vectorized anomaly processing (avoid iterrows)
                    anomalies_df['period'] = anomalies_df.index.strftime('%Y-%m')
                    anomalies_df['item'] = item
                    anomalies_df['item_name'] = names_map.get(item, item)
                    
                    # Get seasonal and trend components for each index
                    anomalies_df['seasonal_component'] = anomalies_df.index.map(
                        lambda idx: float(result.seasonal.loc[idx]) if idx in result.seasonal.index else 0
                    )
                    anomalies_df['trend_component'] = anomalies_df.index.map(
                        lambda idx: float(result.trend.loc[idx]) if idx in result.trend.index else 0
                    )
                    
                    # Create records
                    anomaly_records = anomalies_df.apply(
                        lambda row: {
                            'period': row['period'],
                            'item': row['item'],
                            'item_name': row['item_name'],
                            'actual_amount': float(row[metric_col]),
                            'residual_magnitude': float(row['residual']),
                            'residual_z_score': float(row['residual_z_score']),
                            'seasonal_component': row['seasonal_component'],
                            'trend_component': row['trend_component']
                        },
                        axis=1
                    ).tolist()
                    
                    all_residual_anomalies.extend(anomaly_records)
                
                # Calculate seasonally-adjusted YoY variance
                seasonal_adjusted = item_df[metric_col] - result.seasonal
                latest_period = seasonal_adjusted.index[-1]
                
                # Find same month last year
                year_ago = latest_period - pd.DateOffset(years=1)
                if year_ago in seasonal_adjusted.index:
                    yoy_variance_seasonal_adjusted = float(
                        seasonal_adjusted.loc[latest_period] - seasonal_adjusted.loc[year_ago]
                    )
                    yoy_variance_raw = float(
                        item_df.loc[latest_period, metric_col] - item_df.loc[year_ago, metric_col]
                    )
                else:
                    yoy_variance_seasonal_adjusted = None
                    yoy_variance_raw = None
                
                # Store seasonal pattern (average by month)
                seasonal_pattern = {}
                for month in range(1, 13):
                    month_data = result.seasonal[result.seasonal.index.month == month]
                    if len(month_data) > 0:
                        seasonal_pattern[month] = float(month_data.mean())
                
                seasonal_results.append({
                    'item': item,
                    'item_name': names_map.get(item, item),
                    'periods_analyzed': len(item_df),
                    'residual_std': float(residual_std),
                    'residual_mean': float(residual_mean),
                    'anomaly_count': int(anomaly_mask.sum()),
                    'seasonal_pattern': seasonal_pattern,
                    'yoy_variance_raw': yoy_variance_raw,
                    'yoy_variance_seasonal_adjusted': yoy_variance_seasonal_adjusted,
                    'seasonal_strength': float(result.seasonal.std() / item_df[metric_col].std()) if item_df[metric_col].std() > 0 else 0
                })
                
            except Exception as e:
                # Skip accounts that can't be decomposed
                continue
        
        # Sort anomalies by absolute residual magnitude
        all_residual_anomalies.sort(key=lambda x: abs(x['residual_magnitude']), reverse=True)
        
        # Get top 15 anomalies
        top_anomalies = all_residual_anomalies[:15]
        
        # Calculate summary statistics
        total_anomalies = len(all_residual_anomalies)
        items_with_anomalies = len(set(a['item'] for a in all_residual_anomalies))
        items_analyzed = len(seasonal_results)
        
        # Identify items with strongest seasonal patterns
        seasonal_results_sorted = sorted(
            seasonal_results,
            key=lambda x: x['seasonal_strength'],
            reverse=True
        )
        strongest_seasonal = seasonal_results_sorted[:5]
        
        # Dataset-level month seasonality summary (used by incremental E2E)
        seasonality_summary = {}
        try:
            monthly_df = df.copy()
            if "grain" in monthly_df.columns:
                monthly_df = monthly_df[monthly_df["grain"] == "monthly"].copy()

            if not monthly_df.empty:
                if "month" not in monthly_df.columns:
                    monthly_df["month"] = pd.to_datetime(monthly_df[time_col], errors="coerce").dt.month

                monthly_avgs = monthly_df.groupby("month")[metric_col].mean()
                if not monthly_avgs.empty:
                    peak_month = int(monthly_avgs.idxmax())
                    trough_month = int(monthly_avgs.idxmin())
                    amplitude_pct = float((monthly_avgs.max() - monthly_avgs.min()) / monthly_avgs.mean() * 100) if monthly_avgs.mean() else 0.0
                    seasonality_summary = {
                        "peak_month": peak_month,
                        "trough_month": trough_month,
                        "seasonal_amplitude_pct": amplitude_pct,
                    }
        except Exception:
            seasonality_summary = {}

        result = {
            "seasonal_analysis": seasonal_results,
            "residual_anomalies": all_residual_anomalies,
            "top_anomalies": top_anomalies,
            "strongest_seasonal_items": strongest_seasonal,
            "seasonality_summary": seasonality_summary,
            "summary": {
                "items_analyzed": items_analyzed,
                "total_periods": periods_available,
                "total_anomalies_detected": total_anomalies,
                "items_with_anomalies": items_with_anomalies,
                "anomaly_rate_pct": round((total_anomalies / (items_analyzed * periods_available) * 100), 2) if items_analyzed > 0 else 0
            }
        }
        
        return json.dumps(result, indent=2)
        
    except Exception as e:
        return json.dumps({
            "error": "SeasonalDecompositionFailed",
            "message": f"Failed to compute seasonal decomposition: {str(e)}",
            "seasonal_analysis": [],
            "residual_anomalies": [],
            "top_anomalies": [],
            "summary": {"accounts_analyzed": 0, "total_anomalies_detected": 0}
        }, indent=2)

