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
Load And Validate From Cache tool for ingest_validator_agent.
"""

import json
from typing import Any, Dict, List
from datetime import datetime
from pathlib import Path

# Import pandas if available
try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

# Cache directory and default file
DATA_CACHE_DIR = Path(__file__).parent.parent.parent.parent.parent / "data_cache"
DEFAULT_CACHE_FILE = DATA_CACHE_DIR / "toll_expenses_cache.csv"


def _validate_series(series: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Validate time series data for gaps and back-dated postings.
    
    Args:
        series: List of time-series records sorted by period
    
    Returns:
        Dictionary with quality flags
    """
    flags = {"missing_months": [], "back_dated_postings": False, "non_numeric_amounts": False}
    if not series:
        return flags

    def parse(period: str) -> datetime:
        return datetime.strptime(period, "%Y-%m")

    for idx in range(1, len(series)):
        prev = parse(series[idx - 1]["period"])
        cur = parse(series[idx]["period"])
        gap = (cur.year - prev.year) * 12 + (cur.month - prev.month)
        if gap > 1:
            flags["missing_months"].append(f"gap_before_{series[idx]['period']}")
        if gap < 0:
            flags["back_dated_postings"] = True

    return flags


async def load_and_validate_from_cache(
    cache_file: str = "",
    aggregate_by: str = "period"
) -> str:
    """Load data from cache and validate it.
    
    Args:
        cache_file: Optional custom cache file name (empty string = default: toll_expenses_cache.csv)
        aggregate_by: How to aggregate data - "period" (default), "cost_center", or "division"
        
    Returns:
        JSON string with validated time series data.
    """
    if not HAS_PANDAS:
        return json.dumps({
            "error": "DependencyError",
            "source": "ingest_validator",
            "detail": "pandas not available",
            "action": "stop",
        })
    
    try:
        # Determine cache file path
        if not cache_file or cache_file == "":
            cache_path = DEFAULT_CACHE_FILE
        else:
            cache_path = DATA_CACHE_DIR / cache_file
        
        # Check if cache exists
        if not cache_path.exists():
            return json.dumps({
                "error": "CacheNotFound",
                "source": "ingest_validator",
                "detail": f"No cached data found at {cache_path}. Please refresh data first.",
                "action": "stop",
            })
        
        # Load CSV from cache
        df = pd.read_csv(cache_path)
        
        # Verify required columns
        required_cols = ['THYEAR', 'THMNTH', 'TXFAMT']
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            return json.dumps({
                "error": "InvalidCacheFormat",
                "source": "ingest_validator",
                "detail": f"Missing required columns: {missing_cols}",
                "action": "stop",
            })
        
        # Create period column
        df['period'] = (
            df['THYEAR'].astype(str) + '-' + 
            df['THMNTH'].astype(str).str.zfill(2)
        )
        
        # Filter invalid periods (month > 12 or < 1)
        df = df[df['THMNTH'].astype(int).between(1, 12)]
        
        # Aggregate based on parameter
        if aggregate_by == "cost_center":
            # Aggregate by cost center and period
            agg_df = df.groupby(['GL_CC', 'gl_cst_ctr_nm', 'period'], as_index=False).agg({
                'TXFAMT': 'sum',
                'CTACCT': 'first'  # Keep one GL string for reference
            })
            time_series = agg_df.rename(columns={
                'TXFAMT': 'amount',
                'CTACCT': 'GL String'
            }).to_dict('records')
            
        elif aggregate_by == "division":
            # Aggregate by division and period
            agg_df = df.groupby(['DIV', 'gl_div_nm', 'period'], as_index=False).agg({
                'TXFAMT': 'sum',
                'CTACCT': 'first'
            })
            time_series = agg_df.rename(columns={
                'TXFAMT': 'amount',
                'CTACCT': 'GL String'
            }).to_dict('records')
            
        else:  # aggregate_by == "period" (default)
            # Aggregate by period only (sum across all cost centers/divisions)
            agg_df = df.groupby('period', as_index=False).agg({
                'TXFAMT': 'sum'
            })
            time_series = agg_df.rename(columns={'TXFAMT': 'amount'}).to_dict('records')
        
        # Sort by period
        time_series.sort(key=lambda x: x['period'])
        
        # Validate the series
        flags = _validate_series(time_series)
        
        return json.dumps({
            "analysis_type": "ingest_validation",
            "source": "cache",
            "cache_file": str(cache_path),
            "aggregation": aggregate_by,
            "time_series": time_series,
            "quality_flags": flags,
            "raw_row_count": len(df),
            "aggregated_row_count": len(time_series)
        }, indent=2)
        
    except Exception as e:
        return json.dumps({
            "error": "CacheLoadError",
            "source": "ingest_validator",
            "detail": f"Failed to load from cache: {str(e)}",
            "action": "stop",
        })
