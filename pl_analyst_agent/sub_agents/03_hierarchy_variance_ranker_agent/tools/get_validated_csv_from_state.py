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
Tool to retrieve validated CSV data from shared cache.
"""


async def get_validated_csv_from_state() -> str:
    """
    Retrieve validated P&L CSV data from shared cache.
    
    This tool reads the validated_pl_data_csv from the shared data cache, which contains
    P&L data with hierarchy levels (level_1, level_2, level_3, level_4) already joined.
    
    Returns:
        CSV string with columns: period, gl_account, account_name, amount, 
        level_1, level_2, level_3, level_4
        
    Note: This is set by testing_data_agent in TEST MODE or by the validation workflow
    in production mode.
    """
    # Import here to avoid circular dependencies
    from ....data_cache import get_validated_csv
    
    try:
        csv_data = get_validated_csv()
        if csv_data:
            # Return first 500 chars as preview + full data
            preview = csv_data[:500]
            return csv_data
        else:
            return "ERROR: No validated CSV data found in cache. Data may not have been loaded yet."
    except Exception as e:
        return f"ERROR: Failed to read from cache: {str(e)}"

