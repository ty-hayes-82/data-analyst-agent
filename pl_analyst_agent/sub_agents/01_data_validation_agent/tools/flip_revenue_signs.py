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
Tool to flip revenue account signs for proper P&L presentation.
"""

import pandas as pd
from io import StringIO
from config.chart_loader import get_all_accounts_with_levels


# Cache chart data at module load time (once) instead of loading it 900 times
_CHART_DATA_CACHE = None


def _get_chart_data():
    """Get cached chart data or load it once."""
    global _CHART_DATA_CACHE
    if _CHART_DATA_CACHE is None:
        try:
            _CHART_DATA_CACHE = get_all_accounts_with_levels()
        except Exception:
            _CHART_DATA_CACHE = {}
    return _CHART_DATA_CACHE


def _is_revenue_account(gl_account: str) -> bool:
    """
    Determine if a GL account is a revenue account.
    
    Revenue accounts are identified by:
    1. Account numbers starting with "3" (3100-00, 3115-00, etc.)
    2. level_1 = "Total Operating Revenue"
    3. canonical_category = "Revenue"
    
    Args:
        gl_account: GL account code (e.g., "3100-00")
    
    Returns:
        True if account is a revenue account, False otherwise
    """
    try:
        # Check if account starts with "3"
        if gl_account and str(gl_account).startswith("3"):
            return True
        
        # Also check chart of accounts metadata (using cached data)
        chart_data = _get_chart_data()
        account_info = chart_data.get(gl_account, {})
        
        # Check level_1 or canonical_category
        if account_info.get("level_1") == "Total Operating Revenue":
            return True
        if account_info.get("canonical_category") == "Revenue":
            return True
            
    except Exception:
        # If metadata lookup fails, fall back to account number check
        if gl_account and str(gl_account).startswith("3"):
            return True
    
    return False


async def flip_revenue_signs(data_csv: str) -> str:
    """
    Flip the sign of revenue accounts for proper P&L presentation.
    
    In accounting, revenue is typically recorded as positive in the GL,
    but for P&L presentation, revenue should be displayed as positive.
    Some systems may store revenue as negative, requiring sign flipping.
    
    This tool identifies revenue accounts and multiplies their amounts by -1.
    
    Args:
        data_csv: CSV data with gl_account and amount columns
    
    Returns:
        CSV data with flipped revenue signs, including a new column
        'sign_flipped' indicating which records were modified
    """
    try:
        # Load financial data
        df = pd.read_csv(StringIO(data_csv))
        
        if "gl_account" not in df.columns:
            return "ERROR: Data must have 'gl_account' column"
        
        if "amount" not in df.columns:
            return "ERROR: Data must have 'amount' column"
        
        # Identify revenue accounts
        df["is_revenue"] = df["gl_account"].apply(_is_revenue_account)
        
        # Flip signs for revenue accounts
        df["sign_flipped"] = False
        revenue_mask = df["is_revenue"] == True
        df.loc[revenue_mask, "amount"] = df.loc[revenue_mask, "amount"] * -1
        df.loc[revenue_mask, "sign_flipped"] = True
        
        # Count how many records were flipped
        flipped_count = df["sign_flipped"].sum()
        total_count = len(df)
        
        # Drop the temporary is_revenue column
        df = df.drop(columns=["is_revenue"])
        
        # Add summary message in console
        print(f"[flip_revenue_signs]: Flipped {flipped_count} out of {total_count} records for revenue accounts")
        
        # Return as CSV
        csv_output = df.to_csv(index=False)
        return csv_output
        
    except Exception as e:
        return f"ERROR: Failed to flip revenue signs: {str(e)}"

