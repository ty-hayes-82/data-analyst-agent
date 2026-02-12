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
from typing import Dict, Any, List
from io import StringIO


async def detect_mad_outliers() -> str:
    """
    Robust outlier detection using MAD (Median Absolute Deviation).
    
    MAD is more robust than Z-score because it uses median instead of mean:
    - Not affected by extreme outliers
    - Works better for skewed distributions
    - Standard Z-score: (x - mean) / std
    - MAD score: 0.6745 * (x - median) / MAD
    
    Threshold: Modified Z-score > 3.5 indicates outlier
    
    Returns:
        JSON string with:
        - mad_outliers: Periods flagged as outliers
        - modified_z_scores: Robust Z-scores for all periods
        - comparison_with_z_score: Outliers caught by MAD but not Z-score
        - summary: Overall outlier statistics
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
        
        # Get account names
        account_names = df[['gl_account', 'account_name']].drop_duplicates().set_index('gl_account')['account_name'].to_dict()
        
        all_mad_outliers = []
        mad_vs_zscore_comparison = []
        
        # Analyze each GL account
        for account in df['gl_account'].unique():
            account_df = df[df['gl_account'] == account].copy()
            account_df = account_df.sort_values('period')
            
            # Need at least 6 observations for meaningful analysis
            if len(account_df) < 6:
                continue
            
            try:
                amounts = account_df['amount'].values
                periods = account_df['period'].values
                
                # Calculate MAD
                median = np.median(amounts)
                mad = np.median(np.abs(amounts - median))
                
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
                            'account': account,
                            'account_name': account_names.get(account, account),
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
        accounts_with_outliers = len(set(o['account'] for o in all_mad_outliers))
        accounts_analyzed = len(df['gl_account'].unique())
        mad_only_count = len(mad_vs_zscore_comparison)
        
        result = {
            "mad_outliers": all_mad_outliers,
            "top_outliers": top_outliers,
            "mad_vs_zscore_comparison": mad_vs_zscore_comparison,
            "summary": {
                "accounts_analyzed": accounts_analyzed,
                "total_outliers_detected": total_outliers,
                "accounts_with_outliers": accounts_with_outliers,
                "mad_only_outliers": mad_only_count,
                "outlier_rate_pct": round((total_outliers / (accounts_analyzed * len(df['period'].unique())) * 100), 2) if accounts_analyzed > 0 else 0
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

