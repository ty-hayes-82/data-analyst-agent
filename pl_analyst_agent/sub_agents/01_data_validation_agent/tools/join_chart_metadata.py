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
Join chart of accounts metadata to financial data.
"""

import pandas as pd
from io import StringIO

from config.chart_loader import get_all_accounts_with_levels


async def join_chart_metadata(data_csv: str) -> str:
    """
    Join chart_of_accounts level hierarchy metadata to financial data.
    
    Args:
        data_csv: CSV data with gl_account column
    
    Returns:
        CSV data with added columns: level_1, level_2, level_3, level_4
    """
    try:
        # Load financial data
        df = pd.read_csv(StringIO(data_csv))
        
        if "gl_account" not in df.columns:
            return "ERROR: Data must have 'gl_account' column"
        
        # Load chart of accounts metadata
        chart_data = get_all_accounts_with_levels()
        
        # Create metadata DataFrame
        metadata_records = []
        for account_code, account_info in chart_data.items():
            metadata_records.append({
                "gl_account": account_code,
                "level_1": account_info.get("level_1"),
                "level_2": account_info.get("level_2"),
                "level_3": account_info.get("level_3"),
                "level_4": account_info.get("level_4"),
            })
        
        metadata_df = pd.DataFrame(metadata_records)
        
        # Join metadata to financial data
        result_df = df.merge(metadata_df, on="gl_account", how="left")
        
        # Return as CSV
        csv_output = result_df.to_csv(index=False)
        return csv_output
        
    except Exception as e:
        return f"ERROR: Failed to join chart metadata: {str(e)}"

