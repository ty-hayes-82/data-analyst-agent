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
Convert JSON time series to CSV format for downstream tools.
"""

import json
import pandas as pd


async def json_to_csv(json_data: str) -> str:
    """
    Convert JSON time series data to CSV format.
    
    Args:
        json_data: JSON string with format:
            {
                "time_series": [
                    {"period": "2024-01", "gl_account": "3100-00", "amount": 1000, ...},
                    ...
                ]
            }
    
    Returns:
        CSV string with all fields from time_series records
    """
    try:
        data = json.loads(json_data)
        
        if "time_series" not in data:
            return "ERROR: Input must have 'time_series' key"
        
        time_series = data["time_series"]
        
        if not time_series or not isinstance(time_series, list):
            return "ERROR: time_series must be a non-empty list"
        
        # Convert to DataFrame
        df = pd.DataFrame(time_series)
        
        # Return as CSV
        return df.to_csv(index=False)
        
    except json.JSONDecodeError as e:
        return f"ERROR: Invalid JSON - {str(e)}"
    except Exception as e:
        return f"ERROR: Failed to convert JSON to CSV - {str(e)}"

