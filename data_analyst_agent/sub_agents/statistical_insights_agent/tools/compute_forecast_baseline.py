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
from typing import Dict, Any, List, Optional
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


async def compute_forecast_baseline(pre_resolved: Optional[dict] = None) -> str:
    """
    Generate ARIMA forecast baseline for each item.
    """
    if not PMDARIMA_AVAILABLE:
        return json.dumps({
            "warning": "PmdarimaNotAvailable",
            "message": "ARIMA forecasting requires pmdarima package which is not available due to binary incompatibility. Install compatible version or skip forecasting.",
            "forecasts": [],
            "forecast_misses": [],
            "summary": {"items_analyzed": 0, "total_forecast_misses": 0, "note": "pmdarima unavailable"}
        }, indent=2)
    
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
                df, time_col, metric_col, grain_col, name_col, ctx = resolve_data_and_columns("ForecastBaseline")
            except ValueError as e:
                return json.dumps({"error": str(e)}, indent=2)
            df[metric_col] = pd.to_numeric(df[metric_col], errors='coerce').fillna(0)
            names_map = dict(zip(df[grain_col], df[name_col]))
        
        periods_available = len(df[time_col].unique())
        if periods_available < 18:
            return json.dumps({
                "warning": "InsufficientDataForForecasting",
                "message": f"ARIMA forecasting requires at least 18 periods. Only {periods_available} available.",
                "forecasts": [],
                "forecast_misses": [],
                "summary": {"items_analyzed": 0, "total_forecast_misses": 0}
            }, indent=2)
        
        all_forecasts = []
        all_forecast_misses = []
        
        # Analyze each item
        for item in df[grain_col].unique():
            item_df = df[df[grain_col] == item].copy()
            item_df = item_df.sort_values(time_col)
            
            # Need at least 18 observations for ARIMA
            if len(item_df) < 18:
                continue
            
            try:
                amounts = item_df[metric_col].values
                periods = item_df[time_col].values
                
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
                        'item': item,
                        'item_name': names_map.get(item, item),
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
        items_with_misses = len(set(fm['item'] for fm in all_forecast_misses))
        items_analyzed = len(set(f['item'] for f in all_forecasts))
        
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
                "items_analyzed": items_analyzed,
                "total_forecasts": total_forecasts,
                "total_forecast_misses": total_misses,
                "items_with_misses": items_with_misses,
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

