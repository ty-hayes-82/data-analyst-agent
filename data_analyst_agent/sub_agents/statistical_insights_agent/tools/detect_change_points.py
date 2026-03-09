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
Change point detection using ruptures library (PELT algorithm).

Detects structural breaks in time series - significant shifts in mean/trend
that indicate business model changes, new customers, cost initiatives, etc.
"""

import json
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional
try:
    import ruptures as rpt
except ImportError:
    rpt = None
from io import StringIO


async def detect_change_points(pre_resolved: Optional[dict] = None) -> str:
    """
    Detect structural breaks in time series using PELT algorithm.
    """
    if rpt is None:
        return json.dumps({
            "warning": "LibraryMissing",
            "message": "The 'ruptures' library is not installed. Change point detection is disabled.",
            "change_points": [],
            "summary": {"items_analyzed": 0, "total_change_points": 0}
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
                df, time_col, metric_col, grain_col, name_col, ctx = resolve_data_and_columns("ChangePoints")
            except ValueError as e:
                return json.dumps({"error": str(e)}, indent=2)
            df[metric_col] = pd.to_numeric(df[metric_col], errors='coerce').fillna(0)
            names_map = dict(zip(df[grain_col], df[name_col]))
        
        periods_available = len(df[time_col].unique())
        if periods_available < 12:
            return json.dumps({
                "warning": "InsufficientDataForChangePoints",
                "message": f"Change point detection requires at least 12 periods. Only {periods_available} available.",
                "change_points": [],
                "top_change_points": [],
                "summary": {"items_analyzed": 0, "total_change_points": 0}
            }, indent=2)
        
        all_change_points = []
        periods_list = sorted(df[time_col].unique())
        
        # Analyze each item
        for item in df[grain_col].unique():
            item_df = df[df[grain_col] == item].copy()
            item_df = item_df.sort_values(time_col)
            
            # Need at least 12 observations
            if len(item_df) < 12:
                continue
            
            try:
                # Get time series as array
                amounts = item_df[metric_col].values
                periods = item_df[time_col].values
                
                # PELT algorithm for change point detection
                # pen=10 is penalty for adding change points (higher = fewer change points)
                # min_size=3 means at least 3 observations between change points
                algo = rpt.Pelt(model="rbf", min_size=3, jump=1).fit(amounts)
                change_point_indices = algo.predict(pen=10)
                
                # Last index is always end of series, remove it
                change_point_indices = [idx for idx in change_point_indices if idx < len(amounts)]
                
                if len(change_point_indices) == 0:
                    continue
                
                # Analyze each change point
                for cp_idx in change_point_indices:
                    # Calculate means before and after
                    before_amounts = amounts[:cp_idx]
                    after_amounts = amounts[cp_idx:]
                    
                    if len(before_amounts) > 0 and len(after_amounts) > 0:
                        before_mean = float(np.mean(before_amounts))
                        after_mean = float(np.mean(after_amounts))
                        magnitude = after_mean - before_mean
                        magnitude_pct = (magnitude / abs(before_mean) * 100) if before_mean != 0 else 0
                        
                        # Get period where change occurred
                        change_period = periods[cp_idx] if cp_idx < len(periods) else periods[-1]
                        
                        # Calculate confidence (based on magnitude relative to std)
                        std_before = np.std(before_amounts) if len(before_amounts) > 1 else 1
                        confidence = abs(magnitude) / std_before if std_before > 0 else 0
                        
                        all_change_points.append({
                            'period': change_period,
                            'item': item,
                            'item_name': names_map.get(item, item),
                            'change_point_index': int(cp_idx),
                            'before_mean': before_mean,
                            'after_mean': after_mean,
                            'magnitude_dollar': magnitude,
                            'magnitude_pct': float(magnitude_pct),
                            'confidence_score': float(min(confidence, 10)),  # Cap at 10
                            'periods_before': len(before_amounts),
                            'periods_after': len(after_amounts)
                        })
                
            except Exception as e:
                # Skip accounts that can't be analyzed
                continue
        
        # Sort by absolute magnitude
        all_change_points.sort(key=lambda x: abs(x['magnitude_dollar']), reverse=True)
        
        # Get top 15 change points
        top_change_points = all_change_points[:15]
        
        # Calculate summary statistics
        total_change_points = len(all_change_points)
        items_with_changes = len(set(cp['item'] for cp in all_change_points))
        items_analyzed = len(df[grain_col].unique())
        
        # Count positive vs negative changes
        positive_changes = sum(1 for cp in all_change_points if cp['magnitude_dollar'] > 0)
        negative_changes = sum(1 for cp in all_change_points if cp['magnitude_dollar'] < 0)
        
        result = {
            "change_points": all_change_points,
            "top_change_points": top_change_points,
            "summary": {
                "items_analyzed": items_analyzed,
                "total_periods": periods_available,
                "total_change_points": total_change_points,
                "items_with_changes": items_with_changes,
                "positive_changes": positive_changes,
                "negative_changes": negative_changes,
                "change_point_rate": round((total_change_points / items_analyzed), 2) if items_analyzed > 0 else 0
            }
        }
        
        return json.dumps(result, indent=2)
        
    except Exception as e:
        return json.dumps({
            "error": "ChangePointDetectionFailed",
            "message": f"Failed to detect change points: {str(e)}",
            "change_points": [],
            "top_change_points": [],
            "summary": {"accounts_analyzed": 0, "total_change_points": 0}
        }, indent=2)

