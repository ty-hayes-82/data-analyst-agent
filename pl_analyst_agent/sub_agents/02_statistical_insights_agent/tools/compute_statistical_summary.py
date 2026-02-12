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
from typing import Dict, Any, List
import json
from io import StringIO


async def compute_statistical_summary() -> str:
    """
    Compute comprehensive statistical summary from validated P&L data.
    
    ENHANCED: Now includes advanced analysis:
    - Seasonal decomposition (true anomalies after seasonal adjustment)
    - Change point detection (structural breaks)
    - MAD outlier detection (robust to skewed data)
    - ARIMA forecast baseline (actual vs expected)
    - Operational ratio analysis (KPIs and efficiency)
    
    Returns:
        JSON string with complete statistical analysis including:
        - top_drivers: Top accounts by average magnitude
        - most_volatile: Accounts with highest CV
        - anomalies: Periods with |z-score| >= 2
        - correlations: Key account correlations
        - monthly_totals: Aggregate by period
        - summary_stats: Overall statistics
        - seasonal_analysis: NEW - Seasonal decomposition results
        - change_points: NEW - Structural break detection
        - mad_outliers: NEW - Robust outlier detection
        - forecasts: NEW - ARIMA forecast baseline
        - operational_ratios: NEW - KPI analysis
    """
    # Import here to avoid circular dependencies
    from ...data_cache import get_validated_csv
    from .compute_seasonal_decomposition import compute_seasonal_decomposition
    from .detect_change_points import detect_change_points
    from .detect_mad_outliers import detect_mad_outliers
    from .compute_forecast_baseline import compute_forecast_baseline
    from .compute_operational_ratios import compute_operational_ratios
    
    try:
        csv_data = get_validated_csv()
        if not csv_data:
            return json.dumps({"error": "No validated CSV data found in cache"}, indent=2)
        
        # Parse CSV
        df = pd.read_csv(StringIO(csv_data))
        
        # Ensure numeric amount column
        df['amount'] = pd.to_numeric(df['amount'], errors='coerce').fillna(0)
        
        # Pivot to account x period matrix for analysis
        pivot = df.pivot_table(
            index='gl_account',
            columns='period',
            values='amount',
            aggfunc='sum',
            fill_value=0
        )
        
        # Sort periods chronologically
        pivot = pivot.reindex(sorted(pivot.columns), axis=1)
        
        # Precompute helpers for upgrades
        latest_period = str(pivot.columns[-1]) if len(pivot.columns) else "N/A"
        prev_period = str(pivot.columns[-2]) if len(pivot.columns) >= 2 else None

        # Contribution to change (latest vs prev)
        contribution_share = {}
        if prev_period is not None:
            change_series = (pivot[latest_period] - pivot[prev_period])
            denom = float(change_series.sum()) if float(change_series.sum()) != 0 else 1e-9
            for account in pivot.index:
                contribution_share[account] = float(change_series.loc[account] / denom)

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

        # === 1. Per-Account Metrics ===
        account_stats = []
        for account in pivot.index:
            values = pivot.loc[account].values
            
            # Basic stats
            avg = float(np.mean(values))
            std = float(np.std(values))
            cv = abs(std / avg) if avg != 0 else 0
            
            # Last 3-month slope (simple linear regression)
            if len(values) >= 3:
                last_3 = values[-3:]
                x = np.arange(len(last_3))
                slope = float(np.polyfit(x, last_3, 1)[0])
            else:
                slope = 0

            # Previous 3-month slope for acceleration
            if len(values) >= 6:
                prev_3 = values[-6:-3]
                x2 = np.arange(len(prev_3))
                slope_prev = float(np.polyfit(x2, prev_3, 1)[0])
                acceleration = float(slope - slope_prev)
            else:
                acceleration = 0
            
            # Get account name from original df
            account_name = df[df['gl_account'] == account]['account_name'].iloc[0] if len(df[df['gl_account'] == account]) > 0 else account
            
            account_stats.append({
                'account': account,
                'account_name': account_name,
                'avg': round(avg, 2),
                'std': round(std, 2),
                'cv': round(cv, 4),
                'slope_3mo': round(slope, 2),
                'acceleration_3mo': round(acceleration, 2),
                'min': round(float(np.min(values)), 2),
                'max': round(float(np.max(values)), 2)
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
            mean = np.mean(values)
            std = np.std(values)
            
            if std > 0:
                z_scores = (values - mean) / std
                
                # Flag anomalies with |z| >= 2
                for i, (period, z) in enumerate(zip(pivot.columns, z_scores)):
                    if abs(z) >= 2.0:
                        account_name = df[df['gl_account'] == account]['account_name'].iloc[0] if len(df[df['gl_account'] == account]) > 0 else account
                        anomalies.append({
                            'period': str(period),
                            'account': account,
                            'account_name': account_name,
                            'value': round(float(values[i]), 2),
                            'z_score': round(float(z), 2),
                            'avg': round(float(mean), 2),
                            'std': round(float(std), 2)
                        })
        
        # Sort anomalies by absolute z-score
        anomalies_sorted = sorted(anomalies, key=lambda x: abs(x['z_score']), reverse=True)[:20]
        
        # Build quick lookup for latest-period anomaly per account
        anomaly_latest_flag = {}
        for a in anomalies:
            if a['period'] == latest_period:
                anomaly_latest_flag[a['account']] = True

        # === 3. Correlations ===
        correlations = {}
        
        # Find key revenue accounts (3xxx series)
        revenue_accounts = [acc for acc in pivot.index if str(acc).startswith('3')]
        
        if len(revenue_accounts) >= 2:
            # Calculate correlation between top 2 revenue accounts
            for i in range(min(3, len(revenue_accounts))):
                for j in range(i + 1, min(4, len(revenue_accounts))):
                    acc1 = revenue_accounts[i]
                    acc2 = revenue_accounts[j]
                    
                    corr = float(np.corrcoef(pivot.loc[acc1], pivot.loc[acc2])[0, 1])
                    
                    if abs(corr) > 0.7:  # Only report strong correlations
                        key = f"{acc1}_vs_{acc2}"
                        correlations[key] = round(corr, 3)
        
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

        # === 4. Monthly Totals ===
        monthly_totals = {}
        for period in pivot.columns:
            total = float(pivot[period].sum())
            monthly_totals[str(period)] = round(total, 2)
        
        # === 5. Summary Statistics ===
        total_accounts = len(pivot.index)
        total_periods = len(pivot.columns)
        
        # Find highest/lowest total months
        sorted_months = sorted(monthly_totals.items(), key=lambda x: x[1])
        highest_month = sorted_months[-1] if sorted_months else ("N/A", 0)
        lowest_month = sorted_months[0] if sorted_months else ("N/A", 0)
        
        summary_stats = {
            'total_accounts': total_accounts,
            'total_periods': total_periods,
            'period_range': f"{pivot.columns[0]} to {pivot.columns[-1]}",
            'highest_total_month': {'period': highest_month[0], 'total': highest_month[1]},
            'lowest_total_month': {'period': lowest_month[0], 'total': lowest_month[1]},
            'total_anomalies_detected': len(anomalies_sorted),
            'accounts_with_high_volatility': len([a for a in account_stats if a['cv'] > 0.5])
        }
        
        # === Compile enhanced drivers with contribution, pattern, flags ===
        enhanced_top_drivers = []
        for d in top_drivers:
            acc = d['account']
            enhanced_top_drivers.append({
                'account': acc,
                'account_name': d['account_name'],
                'avg': d['avg'],
                'std': d['std'],
                'cv': d['cv'],
                'slope_3mo': d['slope_3mo'],
                'acceleration_3mo': d.get('acceleration_3mo', 0),
                'min': d['min'],
                'max': d['max'],
                'share_of_total': round(abs(d['avg']) / total_avg_mag, 4),
                'contribution_share': round(float(contribution_share.get(acc, 0.0)), 4),
                'pattern_label': pattern_label_by_account.get(acc, 'run_rate_change'),
                'per_unit_change': None,  # No ops metrics available in this tool
                'anomaly_latest': bool(anomaly_latest_flag.get(acc, False)),
            })

        # Delta attribution list
        delta_attribution = []
        if prev_period is not None:
            deltas_sorted = change_series.sort_values(key=lambda s: s.abs(), ascending=False)
            denom = float(deltas_sorted.sum()) if float(deltas_sorted.sum()) != 0 else 1e-9
            for acc, delta in deltas_sorted.items():
                delta_attribution.append({
                    'gl_account': acc,
                    'account_name': df[df['gl_account'] == acc]['account_name'].iloc[0] if len(df[df['gl_account'] == acc]) > 0 else acc,
                    'delta': round(float(delta), 2),
                    'share': round(float(delta) / denom, 4),
                    'pattern_label': pattern_label_by_account.get(acc, 'run_rate_change')
                })

        # === ENHANCED: Call Advanced Analysis Tools ===
        print("[StatisticalSummary] Running advanced analysis...")
        
        # 1. Seasonal decomposition
        seasonal_json = await compute_seasonal_decomposition()
        seasonal_data = json.loads(seasonal_json)
        
        # 2. Change point detection
        changepoint_json = await detect_change_points()
        changepoint_data = json.loads(changepoint_json)
        
        # 3. MAD outlier detection
        mad_json = await detect_mad_outliers()
        mad_data = json.loads(mad_json)
        
        # 4. ARIMA forecast baseline
        forecast_json = await compute_forecast_baseline()
        forecast_data = json.loads(forecast_json)
        
        # 5. Operational ratio analysis
        ratio_json = await compute_operational_ratios()
        ratio_data = json.loads(ratio_json)
        
        print("[StatisticalSummary] Advanced analysis complete")
        
        # === Compile Results (Original + Enhanced) ===
        result = {
            # Original analysis
            'top_drivers': top_drivers,
            'most_volatile': most_volatile,
            'anomalies': anomalies_sorted,
            'correlations': correlations,
            'monthly_totals': monthly_totals,
            'summary_stats': summary_stats,
            'enhanced_top_drivers': enhanced_top_drivers,
            'normalization_unavailable': True,
            'normalization_readiness': {'ready': False, 'missing_metrics': ['miles', 'loads', 'stops']},
            'delta_attribution': delta_attribution,
            'dq_flags': {'suspected_uniform_growth': suspected_uniform_growth},
            
            # NEW: Advanced analysis results
            'seasonal_analysis': seasonal_data,
            'change_points': changepoint_data,
            'mad_outliers': mad_data,
            'forecasts': forecast_data,
            'operational_ratios': ratio_data,
            
            'metadata': {
                'computation_method': 'pandas/numpy statistical analysis + advanced methods',
                'anomaly_threshold': 'z-score >= 2.0',
                'slope_method': 'last 3 months linear regression',
                'advanced_methods': [
                    'STL seasonal decomposition',
                    'PELT change point detection',
                    'MAD robust outlier detection',
                    'ARIMA forecasting',
                    'Operational ratio analysis'
                ]
            }
        }
        
        return json.dumps(result, indent=2)
        
    except Exception as e:
        return json.dumps({
            "error": f"Failed to compute statistical summary: {str(e)}",
            "traceback": str(e)
        }, indent=2)


