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
from typing import Dict, Any, List
from statsmodels.tsa.seasonal import seasonal_decompose
from io import StringIO


async def compute_seasonal_decomposition() -> str:
    """
    Decompose time series into trend, seasonal, and residual components.
    
    This function identifies TRUE anomalies by removing seasonal effects.
    A spike in December might be normal (seasonal), but a spike in July
    that exceeds the residual threshold is a true anomaly.
    
    Returns:
        JSON string with:
        - seasonal_analysis: Per-account seasonal decomposition
        - residual_anomalies: True anomalies (residual > 2sigma)
        - seasonal_adjusted_variance: YoY variance after seasonal adjustment
        - top_anomalies: Most significant non-seasonal anomalies
        - summary: Overall analysis summary
    """
    # Import here to avoid circular dependencies
    from ...data_cache import get_validated_csv
    
    try:
        csv_data = get_validated_csv()
        if not csv_data:
            return json.dumps({"error": "No validated CSV data found in cache"}, indent=2)
        
        # Parse CSV
        df = pd.read_csv(StringIO(csv_data))
        
        # Ensure numeric amount column
        df['amount'] = pd.to_numeric(df['amount'], errors='coerce').fillna(0)
        
        # Need at least 24 periods (2 years) for meaningful seasonal decomposition
        periods_available = len(df['period'].unique())
        if periods_available < 24:
            return json.dumps({
                "warning": "InsufficientDataForSeasonal",
                "message": f"Seasonal decomposition requires at least 24 periods. Only {periods_available} available.",
                "seasonal_analysis": [],
                "residual_anomalies": [],
                "top_anomalies": [],
                "summary": {"accounts_analyzed": 0, "total_anomalies_detected": 0}
            }, indent=2)
        
        # Get account names for reporting
        account_names = df[['gl_account', 'account_name']].drop_duplicates().set_index('gl_account')['account_name'].to_dict()
        
        seasonal_results = []
        all_residual_anomalies = []
        
        # Analyze each GL account
        for account in df['gl_account'].unique():
            account_df = df[df['gl_account'] == account].copy()
            account_df = account_df.sort_values('period')
            
            # Create time series
            account_df['period_date'] = pd.to_datetime(account_df['period'])
            account_df = account_df.set_index('period_date')
            
            # Need at least 24 observations for seasonal decomposition
            if len(account_df) < 24:
                continue
            
            try:
                # Seasonal decomposition (additive model)
                # period=12 for monthly seasonality
                result = seasonal_decompose(
                    account_df['amount'],
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
                    anomalies_df = account_df[anomaly_mask].copy()
                    anomalies_df['residual'] = result.resid[anomaly_mask]
                    anomalies_df['residual_z_score'] = (result.resid[anomaly_mask] - residual_mean) / residual_std
                    
                    for idx, row in anomalies_df.iterrows():
                        all_residual_anomalies.append({
                            'period': idx.strftime('%Y-%m'),
                            'account': account,
                            'account_name': account_names.get(account, account),
                            'actual_amount': float(row['amount']),
                            'residual_magnitude': float(row['residual']),
                            'residual_z_score': float(row['residual_z_score']),
                            'seasonal_component': float(result.seasonal.loc[idx]) if idx in result.seasonal.index else 0,
                            'trend_component': float(result.trend.loc[idx]) if idx in result.trend.index else 0
                        })
                
                # Calculate seasonally-adjusted YoY variance
                seasonal_adjusted = account_df['amount'] - result.seasonal
                latest_period = seasonal_adjusted.index[-1]
                
                # Find same month last year
                year_ago = latest_period - pd.DateOffset(years=1)
                if year_ago in seasonal_adjusted.index:
                    yoy_variance_seasonal_adjusted = float(
                        seasonal_adjusted.loc[latest_period] - seasonal_adjusted.loc[year_ago]
                    )
                    yoy_variance_raw = float(
                        account_df.loc[latest_period, 'amount'] - account_df.loc[year_ago, 'amount']
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
                    'account': account,
                    'account_name': account_names.get(account, account),
                    'periods_analyzed': len(account_df),
                    'residual_std': float(residual_std),
                    'residual_mean': float(residual_mean),
                    'anomaly_count': int(anomaly_mask.sum()),
                    'seasonal_pattern': seasonal_pattern,
                    'yoy_variance_raw': yoy_variance_raw,
                    'yoy_variance_seasonal_adjusted': yoy_variance_seasonal_adjusted,
                    'seasonal_strength': float(result.seasonal.std() / account_df['amount'].std()) if account_df['amount'].std() > 0 else 0
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
        accounts_with_anomalies = len(set(a['account'] for a in all_residual_anomalies))
        accounts_analyzed = len(seasonal_results)
        
        # Identify accounts with strongest seasonal patterns
        seasonal_results_sorted = sorted(
            seasonal_results,
            key=lambda x: x['seasonal_strength'],
            reverse=True
        )
        strongest_seasonal = seasonal_results_sorted[:5]
        
        result = {
            "seasonal_analysis": seasonal_results,
            "residual_anomalies": all_residual_anomalies,
            "top_anomalies": top_anomalies,
            "strongest_seasonal_accounts": strongest_seasonal,
            "summary": {
                "accounts_analyzed": accounts_analyzed,
                "total_periods": periods_available,
                "total_anomalies_detected": total_anomalies,
                "accounts_with_anomalies": accounts_with_anomalies,
                "anomaly_rate_pct": round((total_anomalies / (accounts_analyzed * periods_available) * 100), 2) if accounts_analyzed > 0 else 0
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

