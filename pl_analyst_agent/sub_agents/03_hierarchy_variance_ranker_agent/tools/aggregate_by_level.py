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
Aggregate data by level from chart_of_accounts hierarchy.
"""

import json
import pandas as pd


async def aggregate_by_level(data_csv: str, level_number: int) -> str:
    """
    Aggregate financial data by specified hierarchy level.
    
    Args:
        data_csv: CSV data with columns: gl_account, period, amount, level_1, level_2, level_3, level_4
        level_number: Level to aggregate by (2, 3, or 4)
    
    Returns:
        JSON with aggregated time series by level
    """
    try:
        from io import StringIO
        df = pd.read_csv(StringIO(data_csv))
        
        level_col = f"level_{level_number}"
        
        if level_col not in df.columns:
            return json.dumps({
                "error": "DataUnavailable",
                "source": "aggregate_by_level",
                "detail": f"Column {level_col} not found in data. Ensure ingest_validator joined chart_of_accounts metadata.",
                "action": "stop"
            })
        
        # Aggregate by level and period
        agg_df = df.groupby([level_col, "period"])["amount"].sum().reset_index()
        agg_df.rename(columns={level_col: "level_item"}, inplace=True)
        
        # Pivot to time series format
        pivot_df = agg_df.pivot(index="level_item", columns="period", values="amount")
        pivot_df = pivot_df.fillna(0)
        
        # Convert to JSON format
        result = {
            "analysis_type": "level_aggregation",
            "level_number": level_number,
            "level_items_count": len(pivot_df),
            "periods": list(pivot_df.columns),
            "level_items": []
        }
        
        for level_item in pivot_df.index:
            item_data = {
                "level_item": level_item,
                "time_series": {
                    period: round(float(pivot_df.loc[level_item, period]), 2)
                    for period in pivot_df.columns
                }
            }
            result["level_items"].append(item_data)
        
        return json.dumps(result, indent=2)
        
    except Exception as e:
        return json.dumps({
            "error": "ProcessingFailed",
            "source": "aggregate_by_level",
            "detail": str(e),
            "action": "stop"
        })

