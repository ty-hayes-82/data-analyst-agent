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
ARIMA forecast baseline using pmdarima (auto_arima).

Generates forecast baselines to compare actual vs expected values.
"Revenue is $80K" is less useful than "Revenue is $80K below forecast".
"""

import json
import pandas as pd
import numpy as np
from typing import Dict, Any, List
import warnings
from io import StringIO

# Suppress ARIMA warnings
warnings.filterwarnings('ignore')

# Try to import pmdarima, but make it optional
try:
    from pmdarima import auto_arima
    PMDARIMA_AVAILABLE = True
except (ImportError, ValueError) as e:
    # ValueError can occur due to numpy binary incompatibility
    PMDARIMA_AVAILABLE = False
    print(f"[ForecastBaseline] WARNING: pmdarima not available: {e}")
    print("[ForecastBaseline] ARIMA forecasting will be skipped")


async def compute_forecast_baseline() -> str:
    """
    Generate ARIMA forecast baseline for each GL account.
    
    Uses auto_arima to:
    - Automatically detect seasonality
    - Select best ARIMA parameters
    - Generate forecasts for recent periods
    
    Compares actual vs forecast to identify:
    - Below expectations (forecast miss)
    - Above expectations (positive surprise)
    
    Returns:
        JSON string with:
        - forecasts: Predicted values for each account/period
        - forecast_variance: Actual - Forecast
        - forecast_misses: Periods significantly below forecast
        - summary: Overall forecast accuracy metrics
    """
    # Import here to avoid circular dependencies
    from ...data_cache import get_validated_csv
    
    # Check if pmdarima is available
    if not PMDARIMA_AVAILABLE:
        return json.dumps({
            "warning": "PmdarimaNotAvailable",
            "message": "ARIMA forecasting requires pmdarima package which is not available due to binary incompatibility. Install compatible version or skip forecasting.",
            "forecasts": [],
            "forecast_misses": [],
            "summary": {"accounts_analyzed": 0, "total_forecast_misses": 0, "note": "pmdarima unavailable"}
        }, indent=2)
    
    try:
        csv_data = get_validated_csv()
        if not csv_data:
            return json.dumps({"error": "No validated CSV data found in cache"}, indent=2)
        
        # Parse CSV
        df = pd.read_csv(StringIO(csv_data))
        
        # Ensure numeric amount column
        df['amount'] = pd.to_numeric(df['amount'], errors='coerce').fillna(0)
        
        # Need at least 18 periods for meaningful ARIMA forecasting
        periods_available = len(df['period'].unique())
        if periods_available < 18:
            return json.dumps({
                "warning": "InsufficientDataForForecasting",
                "message": f"ARIMA forecasting requires at least 18 periods. Only {periods_available} available.",
                "forecasts": [],
                "forecast_misses": [],
                "summary": {"accounts_analyzed": 0, "total_forecast_misses": 0}
            }, indent=2)
        
        # Get account names
        account_names = df[['gl_account', 'account_name']].drop_duplicates().set_index('gl_account')['account_name'].to_dict()
        
        all_forecasts = []
        all_forecast_misses = []
        
        # Analyze each GL account
        for account in df['gl_account'].unique():
            account_df = df[df['gl_account'] == account].copy()
            account_df = account_df.sort_values('period')
            
            # Need at least 18 observations for ARIMA
            if len(account_df) < 18:
                continue
            
            try:
                amounts = account_df['amount'].values
                periods = account_df['period'].values
                
                # Use 80% of data for training, 20% for validation (forecast comparison)
                train_size = int(len(amounts) * 0.8)
                if train_size < 12:  # Need minimum training data
                    continue
                
                train_data = amounts[:train_size]
                test_data = amounts[train_size:]
                test_periods = periods[train_size:]
                
                # Auto ARIMA with seasonal detection
                # seasonal=True, m=12 for monthly seasonality
                # stepwise=True for faster computation
                # suppress_warnings=True to avoid verbose output
                model = auto_arima(
                    train_data,
                    seasonal=True,
                    m=12,
                    stepwise=True,
                    suppress_warnings=True,
                    error_action='ignore',
                    max_p=3,  # Limit AR order for speed
                    max_q=3,  # Limit MA order for speed
                    max_order=6,  # Total limit
                    n_fits=10  # Limit model search for speed
                )
                
                # Generate forecasts for test period
                n_periods = len(test_data)
                forecasts = model.predict(n_periods=n_periods)
                
                # Calculate forecast variance
                for i, (period, actual, forecast) in enumerate(zip(test_periods, test_data, forecasts)):
                    variance = actual - forecast
                    variance_pct = (variance / forecast * 100) if forecast != 0 else 0
                    
                    forecast_data = {
                        'period': period,
                        'account': account,
                        'account_name': account_names.get(account, account),
                        'actual': float(actual),
                        'forecast': float(forecast),
                        'variance_dollar': float(variance),
                        'variance_pct': float(variance_pct),
                        'abs_variance_pct': abs(float(variance_pct))
                    }
                    
                    all_forecasts.append(forecast_data)
                    
                    # Flag significant forecast misses (>10% variance)
                    if abs(variance_pct) > 10:
                        all_forecast_misses.append(forecast_data)
                
            except Exception as e:
                # Skip accounts where ARIMA fails
                continue
        
        # Sort forecast misses by absolute variance percentage
        all_forecast_misses.sort(key=lambda x: x['abs_variance_pct'], reverse=True)
        
        # Get top 15 forecast misses
        top_forecast_misses = all_forecast_misses[:15]
        
        # Calculate summary statistics
        total_forecasts = len(all_forecasts)
        total_misses = len(all_forecast_misses)
        accounts_with_misses = len(set(fm['account'] for fm in all_forecast_misses))
        accounts_analyzed = len(set(f['account'] for f in all_forecasts))
        
        # Calculate average forecast accuracy
        if total_forecasts > 0:
            avg_abs_error_pct = np.mean([f['abs_variance_pct'] for f in all_forecasts])
            mape = float(avg_abs_error_pct)  # Mean Absolute Percentage Error
        else:
            mape = 0
        
        result = {
            "forecasts": all_forecasts,
            "forecast_misses": all_forecast_misses,
            "top_forecast_misses": top_forecast_misses,
            "summary": {
                "accounts_analyzed": accounts_analyzed,
                "total_forecasts": total_forecasts,
                "total_forecast_misses": total_misses,
                "accounts_with_misses": accounts_with_misses,
                "miss_rate_pct": round((total_misses / total_forecasts * 100), 2) if total_forecasts > 0 else 0,
                "mape": round(mape, 2)  # Mean Absolute Percentage Error
            }
        }
        
        return json.dumps(result, indent=2)
        
    except Exception as e:
        return json.dumps({
            "error": "ForecastingFailed",
            "message": f"Failed to generate forecasts: {str(e)}",
            "forecasts": [],
            "forecast_misses": [],
            "summary": {"accounts_analyzed": 0, "total_forecast_misses": 0}
        }, indent=2)

