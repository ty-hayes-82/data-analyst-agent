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
MAD (Median Absolute Deviation) outlier detection.

More robust than Z-score for skewed distributions.
Uses median instead of mean, making it resistant to extreme outliers.
"""

import json
import pandas as pd
import numpy as np
from scipy import stats as scipy_stats
from typing import Dict, Any, List, Optional
from io import StringIO


async def detect_mad_outliers(pre_resolved: Optional[dict] = None) -> str:
    """
    Robust outlier detection using MAD (Median Absolute Deviation).
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
                df, time_col, metric_col, grain_col, name_col, ctx = resolve_data_and_columns("MADOutliers")
            except ValueError as e:
                return json.dumps({"error": str(e)}, indent=2)
            df[metric_col] = pd.to_numeric(df[metric_col], errors='coerce').fillna(0)
            names_map = dict(zip(df[grain_col], df[name_col]))
        
        all_mad_outliers = []
        mad_vs_zscore_comparison = []
        
        # Analyze each item
        for item in df[grain_col].unique():
            item_df = df[df[grain_col] == item].copy()
            item_df = item_df.sort_values(time_col)
            
            # Need at least 6 observations for meaningful analysis
            if len(item_df) < 6:
                continue
            
            try:
                amounts = item_df[metric_col].values
                periods = item_df[time_col].values
                
                # Calculate MAD using scipy for robustness
                median = np.median(amounts)
                mad = float(scipy_stats.median_abs_deviation(amounts))
                
                # Avoid division by zero
                if mad == 0:
                    # If MAD is 0, all values are the same, no outliers
                    continue
                
                # Calculate modified Z-scores
                # 0.6745 is the 75th percentile of the standard normal distribution
                # Makes MAD comparable to standard deviation
                modified_z_scores = 0.6745 * (amounts - median) / mad
                
                # Flag outliers (threshold = 3.5 for modified Z-score)
                outlier_mask = np.abs(modified_z_scores) > 3.5
                
                if outlier_mask.sum() > 0:
                    # Also calculate traditional Z-scores for comparison
                    mean = np.mean(amounts)
                    std = np.std(amounts)
                    z_scores = (amounts - mean) / std if std > 0 else np.zeros_like(amounts)
                    z_score_outliers = np.abs(z_scores) > 2
                    
                    for idx in np.where(outlier_mask)[0]:
                        mad_only = outlier_mask[idx] and not z_score_outliers[idx]
                        
                        outlier_data = {
                            'period': periods[idx],
                            'item': item,
                            'item_name': names_map.get(item, item),
                            'amount': float(amounts[idx]),
                            'median': float(median),
                            'modified_z_score': float(modified_z_scores[idx]),
                            'traditional_z_score': float(z_scores[idx]),
                            'mad_only': mad_only,  # Caught by MAD but not Z-score
                            'deviation_from_median': float(amounts[idx] - median)
                        }
                        
                        all_mad_outliers.append(outlier_data)
                        
                        if mad_only:
                            mad_vs_zscore_comparison.append(outlier_data)
                
            except Exception as e:
                # Skip accounts that can't be analyzed
                continue
        
        # Sort by absolute modified Z-score
        all_mad_outliers.sort(key=lambda x: abs(x['modified_z_score']), reverse=True)
        
        # Get top 15 outliers
        top_outliers = all_mad_outliers[:15]
        
        # Calculate summary statistics
        total_outliers = len(all_mad_outliers)
        items_with_outliers = len(set(o['item'] for o in all_mad_outliers))
        items_analyzed = len(df[grain_col].unique())
        mad_only_count = len(mad_vs_zscore_comparison)
        
        result = {
            "mad_outliers": all_mad_outliers,
            "top_outliers": top_outliers,
            "mad_vs_zscore_comparison": mad_vs_zscore_comparison,
            "summary": {
                "items_analyzed": items_analyzed,
                "total_outliers_detected": total_outliers,
                "items_with_outliers": items_with_outliers,
                "mad_only_outliers": mad_only_count,
                "outlier_rate_pct": round((total_outliers / (items_analyzed * len(df[time_col].unique())) * 100), 2) if items_analyzed > 0 else 0
            }
        }
        
        return json.dumps(result, indent=2)
        
    except Exception as e:
        return json.dumps({
            "error": "MADDetectionFailed",
            "message": f"Failed to detect MAD outliers: {str(e)}",
            "mad_outliers": [],
            "top_outliers": [],
            "summary": {"accounts_analyzed": 0, "total_outliers_detected": 0}
        }, indent=2)

