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
Tool to load validated CSV data from the global cache and store in structured format (for TEST MODE).

EFFICIENCY UPDATE: This tool now stores data in the cache and returns ONLY a summary message
to avoid sending 900+ records to the LLM (which caused 268s processing delays).
"""

import json
import pandas as pd
from io import StringIO
from ...data_cache import get_validated_csv, set_validated_csv
from .flip_revenue_signs import _is_revenue_account


async def load_from_global_cache() -> str:
    """
    Load validated CSV data from the global cache, process it, and store in structured format.
    
    This tool is used in TEST MODE when testing_data_agent has stored data in the global cache.
    It retrieves the pre-validated CSV data, flips revenue signs, and stores it in structured
    format for efficient access by downstream tools.
    
    IMPORTANT: This function stores the full dataset in the cache and returns ONLY a summary
    message to the LLM. This prevents sending 900+ records to the LLM (which caused 268s delays).
    
    Returns:
        JSON string with SUMMARY ONLY:
        {
            "status": "success",
            "message": "Validated X records across Y GL accounts...",
            "summary": {
                "total_records": X,
                "gl_accounts": Y,
                "periods": Z,
                "period_range": "YYYY-MM to YYYY-MM",
                "revenue_accounts_flipped": N
            }
        }
        
        Or JSON error if no data is available:
        {
            "error": "DataUnavailable",
            "source": "load_from_global_cache",
            "detail": "No data found in global cache",
            "action": "stop"
        }
    """
    import time
    try:
        t0 = time.time()
        csv_data = get_validated_csv()
        print(f"[DEBUG] get_validated_csv() took {time.time()-t0:.3f}s")
        print(f"[DEBUG] csv_data is None: {csv_data is None}, length: {len(csv_data) if csv_data else 0}")

        if csv_data is None or csv_data.strip() == "":
            return json.dumps({
                "error": "DataUnavailable",
                "source": "load_from_global_cache",
                "detail": "No data found in global cache. Ensure testing_data_agent ran successfully.",
                "action": "stop"
            })
        
        # Parse CSV
        t1 = time.time()
        df = pd.read_csv(StringIO(csv_data))
        print(f"[DEBUG] pd.read_csv() took {time.time()-t1:.3f}s")
        
        # Verify required columns
        t2 = time.time()
        required_cols = ["period", "gl_account", "amount"]
        missing = [col for col in required_cols if col not in df.columns]
        if missing:
            return json.dumps({
                "error": "DataUnavailable",
                "source": "load_from_global_cache",
                "detail": f"Missing required columns: {missing}",
                "action": "stop"
            })
        
        # Flip revenue signs for proper P&L presentation
        t3 = time.time()
        df["is_revenue"] = df["gl_account"].apply(_is_revenue_account)
        print(f"[DEBUG] _is_revenue_account apply() took {time.time()-t3:.3f}s")
        
        t4 = time.time()
        revenue_mask = df["is_revenue"] == True
        
        # Track which records were flipped
        df["sign_flipped"] = False
        df.loc[revenue_mask, "amount"] = df.loc[revenue_mask, "amount"] * -1
        df.loc[revenue_mask, "sign_flipped"] = True
        
        flipped_count = int(df["sign_flipped"].sum())
        
        # Drop temporary column
        df = df.drop(columns=["is_revenue"])
        print(f"[DEBUG] Revenue sign flipping took {time.time()-t4:.3f}s")
        
        # Get summary statistics (before overwriting cache)
        t5 = time.time()
        periods = sorted(df["period"].unique().tolist())
        gl_accounts = df["gl_account"].unique().tolist()
        total_records = len(df)
        print(f"[DEBUG] Summary statistics took {time.time()-t5:.3f}s")

        # Store BACK into CSV cache (fast) with flipped signs; avoid building large JSON dict
        t6 = time.time()
        updated_csv = df.to_csv(index=False)
        set_validated_csv(updated_csv)
        print(f"[DEBUG] CSV cache update took {time.time()-t6:.3f}s")
        
        print(f"[load_from_global_cache]: Updated CSV cache with {total_records} records (flipped {flipped_count} revenue records)")
        print(f"[DEBUG] TOTAL function time: {time.time()-t0:.3f}s")
        
        # Return ONLY summary to LLM (NOT the full dataset)
        summary_response = {
            "status": "success",
            "message": f"Validated {total_records} records across {len(gl_accounts)} GL accounts, {len(periods)} periods ({periods[0]} to {periods[-1]}). Data stored in cache for analysis.",
            "summary": {
                "total_records": total_records,
                "gl_accounts": len(gl_accounts),
                "periods": len(periods),
                "period_range": f"{periods[0]} to {periods[-1]}",
                "revenue_accounts_flipped": flipped_count
            }
        }
        
        return json.dumps(summary_response, indent=2)
        
    except Exception as e:
        return json.dumps({
            "error": "CacheAccessFailed",
            "source": "load_from_global_cache",
            "detail": str(e),
            "action": "stop"
        })

