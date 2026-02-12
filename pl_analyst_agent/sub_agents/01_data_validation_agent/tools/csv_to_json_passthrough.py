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
Pass-through tool for TEST MODE: Converts validated CSV directly to JSON format.
Used when testing_data_agent has already loaded and validated data with hierarchy.
"""

import json
import pandas as pd
from io import StringIO


async def csv_to_json_passthrough(csv_data: str) -> str:
    """
    Convert pre-validated CSV data (with hierarchy levels) to JSON format.
    
    Args:
        csv_data: CSV string with columns: period, gl_account, account_name, amount, 
                  level_1, level_2, level_3, level_4
    
    Returns:
        JSON string with format:
        {
            "analysis_type": "ingest_validation",
            "status": "success",
            "time_series": [
                {"period": "2024-07", "gl_account": "3100-00", "amount": 1000, ...},
                ...
            ],
            "quality_flags": {
                "source": "testing_data_agent",
                "pre_validated": true
            }
        }
    """
    try:
        # Parse CSV
        df = pd.read_csv(StringIO(csv_data))
        
        # Verify required columns
        required_cols = ["period", "gl_account", "amount"]
        missing = [col for col in required_cols if col not in df.columns]
        if missing:
            return json.dumps({
                "error": "DataUnavailable",
                "source": "csv_to_json_passthrough",
                "detail": f"Missing required columns: {missing}",
                "action": "stop"
            })
        
        # Convert to time series format
        time_series = df.to_dict(orient="records")
        
        # Build response
        result = {
            "analysis_type": "ingest_validation",
            "status": "success",
            "time_series": time_series,
            "quality_flags": {
                "source": "testing_data_agent",
                "pre_validated": True,
                "hierarchy_joined": True,
                "total_records": len(time_series),
                "periods": sorted(df["period"].unique().tolist()),
                "gl_accounts": len(df["gl_account"].unique())
            }
        }
        
        return json.dumps(result, indent=2)
        
    except Exception as e:
        return json.dumps({
            "error": "ProcessingFailed",
            "source": "csv_to_json_passthrough",
            "detail": str(e),
            "action": "stop"
        })





