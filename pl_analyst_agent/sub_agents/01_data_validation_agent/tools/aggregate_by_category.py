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
Aggregate GL accounts by category using canonical_category from chart_of_accounts.yaml.
"""

import json
from collections import defaultdict
from typing import Any, Dict, List


async def aggregate_by_category(pl_data: str, chart_of_accounts_yaml: str) -> str:
    """
    Aggregate GL-level P&L data by canonical_category.
    
    Args:
        pl_data: JSON string with GL-level time series data
            Format: {"gl_account": "6000-00", "time_series": [{"period": "2024-01", "amount": 1000}, ...]}
            OR list of such objects for multiple GLs
        chart_of_accounts_yaml: YAML string with chart of accounts configuration
    
    Returns:
        JSON string with category-level aggregated time series:
        {
            "analysis_type": "category_aggregation",
            "categories": {
                "Wages": {
                    "time_series": [{"period": "2024-01", "amount": 5000}, ...],
                    "gl_accounts": ["6000-00", "6001-00", ...]
                },
                "Benefits": {...},
                ...
            },
            "total_categories": N
        }
    """
    try:
        import yaml
        
        # Parse inputs
        pl_data_parsed = json.loads(pl_data)
        coa = yaml.safe_load(chart_of_accounts_yaml)
        
        if not coa or "accounts" not in coa:
            return json.dumps({
                "error": "DataUnavailable",
                "source": "aggregate_by_category",
                "detail": "chart_of_accounts must contain 'accounts' key",
                "action": "stop"
            })
        
        # Normalize pl_data to list format
        if isinstance(pl_data_parsed, dict) and "gl_account" in pl_data_parsed:
            gl_data_list = [pl_data_parsed]
        elif isinstance(pl_data_parsed, list):
            gl_data_list = pl_data_parsed
        else:
            return json.dumps({
                "error": "DataUnavailable",
                "source": "aggregate_by_category",
                "detail": "pl_data must be a single GL object or list of GL objects",
                "action": "stop"
            })
        
        # Build category -> periods -> amount mapping
        category_data: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        category_gls: Dict[str, List[str]] = defaultdict(list)
        
        for gl_obj in gl_data_list:
            gl_account = gl_obj.get("gl_account")
            time_series = gl_obj.get("time_series", [])
            
            if not gl_account or not time_series:
                continue
            
            # Lookup canonical_category for this GL
            gl_config = coa["accounts"].get(gl_account, {})
            category = gl_config.get("canonical_category")
            
            if not category:
                # Skip GLs without category mapping
                continue
            
            # Track which GLs contribute to this category
            if gl_account not in category_gls[category]:
                category_gls[category].append(gl_account)
            
            # Aggregate amounts by period
            for record in time_series:
                period = record.get("period")
                amount = float(record.get("amount", 0))
                
                if period:
                    category_data[category][period] += amount
        
        # Convert to output format
        categories_output = {}
        for category, periods_dict in category_data.items():
            # Sort periods chronologically
            sorted_periods = sorted(periods_dict.keys())
            time_series = [
                {"period": period, "amount": round(periods_dict[period], 2)}
                for period in sorted_periods
            ]
            
            categories_output[category] = {
                "time_series": time_series,
                "gl_accounts": sorted(category_gls[category]),
                "total_periods": len(time_series)
            }
        
        return json.dumps({
            "analysis_type": "category_aggregation",
            "categories": categories_output,
            "total_categories": len(categories_output),
            "category_names": sorted(categories_output.keys())
        }, indent=2)
        
    except json.JSONDecodeError as e:
        return json.dumps({
            "error": "DataUnavailable",
            "source": "aggregate_by_category",
            "detail": f"Invalid JSON input: {str(e)}",
            "action": "stop"
        })
    except Exception as e:
        return json.dumps({
            "error": "ProcessingError",
            "source": "aggregate_by_category",
            "detail": str(e),
            "action": "stop"
        })

