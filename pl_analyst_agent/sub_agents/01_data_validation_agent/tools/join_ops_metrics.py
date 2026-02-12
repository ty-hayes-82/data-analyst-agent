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
Join P&L data with operational metrics for volume normalization.
"""

import json
from typing import Any, Dict, List


async def join_ops_metrics(pl_data: str, ops_data: str) -> str:
    """
    Join P&L amounts with operational metrics (miles, loads, stops) by period.
    
    Args:
        pl_data: JSON string with P&L time series
            Format: {"time_series": [{"period": "2024-01", "amount": 1000}, ...]}
            OR {"gl_account": "6000-00", "time_series": [...]}
        ops_data: JSON string with ops metrics time series
            Format: {"time_series": [{"period": "2024-01", "total_miles": 10000, "orders": 500, "stops": 1200}, ...]}
    
    Returns:
        JSON string with enriched time series:
        {
            "analysis_type": "ops_metrics_join",
            "time_series": [
                {
                    "period": "2024-01",
                    "amount": 50000,
                    "total_miles": 10000,
                    "loaded_miles": 8000,
                    "orders": 500,
                    "stops": 1200,
                    "amount_per_mile": 5.00,
                    "amount_per_load": 100.00,
                    "amount_per_stop": 41.67
                },
                ...
            ]
        }
    """
    try:
        # Parse inputs
        pl_parsed = json.loads(pl_data)
        ops_parsed = json.loads(ops_data)
        
        # Extract time series from different formats
        if isinstance(pl_parsed, dict):
            if "time_series" in pl_parsed:
                pl_time_series = pl_parsed["time_series"]
                gl_account = pl_parsed.get("gl_account")
            else:
                return json.dumps({
                    "error": "DataUnavailable",
                    "source": "join_ops_metrics",
                    "detail": "pl_data must contain 'time_series' key",
                    "action": "stop"
                })
        elif isinstance(pl_parsed, list):
            pl_time_series = pl_parsed
            gl_account = None
        else:
            return json.dumps({
                "error": "DataUnavailable",
                "source": "join_ops_metrics",
                "detail": "pl_data must be dict or list",
                "action": "stop"
            })
        
        if isinstance(ops_parsed, dict) and "time_series" in ops_parsed:
            ops_time_series = ops_parsed["time_series"]
        elif isinstance(ops_parsed, list):
            ops_time_series = ops_parsed
        else:
            return json.dumps({
                "error": "DataUnavailable",
                "source": "join_ops_metrics",
                "detail": "ops_data must contain 'time_series' key or be a list",
                "action": "stop"
            })
        
        # Build ops metrics lookup by period
        ops_lookup: Dict[str, Dict[str, Any]] = {}
        for record in ops_time_series:
            period = record.get("period")
            if period:
                ops_lookup[period] = {
                    "total_miles": float(record.get("total_miles", 0)),
                    "loaded_miles": float(record.get("loaded_miles", 0)),
                    "empty_miles": float(record.get("empty_miles", 0)),
                    "orders": float(record.get("orders", 0)),
                    "stops": float(record.get("stops", 0)),
                    "revenue": float(record.get("total_revenue", 0)),
                    "truck_count": float(record.get("truck_count", 0)),
                    "fuel_surcharge": float(record.get("fuel_surcharge", 0)),
                }
        
        # Join P&L with ops metrics
        enriched_series = []
        for pl_record in pl_time_series:
            period = pl_record.get("period")
            amount = float(pl_record.get("amount", 0))
            
            if not period:
                continue
            
            # Initialize enriched record with P&L data
            enriched = {
                "period": period,
                "amount": round(amount, 2)
            }
            
            # Add ops metrics if available for this period
            if period in ops_lookup:
                ops = ops_lookup[period]
                
                # Add raw operational metrics
                enriched["total_miles"] = round(ops["total_miles"], 2)
                enriched["loaded_miles"] = round(ops["loaded_miles"], 2)
                enriched["empty_miles"] = round(ops["empty_miles"], 2)
                enriched["orders"] = round(ops["orders"], 0)
                enriched["stops"] = round(ops["stops"], 0)
                enriched["revenue"] = round(ops["revenue"], 2)
                
                # Calculate per-unit metrics
                if ops["total_miles"] > 0:
                    enriched["amount_per_mile"] = round(amount / ops["total_miles"], 4)
                
                if ops["loaded_miles"] > 0:
                    enriched["amount_per_loaded_mile"] = round(amount / ops["loaded_miles"], 4)
                
                if ops["orders"] > 0:
                    enriched["amount_per_load"] = round(amount / ops["orders"], 2)
                
                if ops["stops"] > 0:
                    enriched["amount_per_stop"] = round(amount / ops["stops"], 2)
                
                if ops["revenue"] > 0:
                    enriched["amount_pct_of_revenue"] = round((amount / ops["revenue"]) * 100, 2)

                # Utilization metrics (from config: ops_metrics_ratios_config.yaml)
                enriched["truck_count"] = round(ops["truck_count"], 2)
                enriched["fuel_surcharge"] = round(ops["fuel_surcharge"], 2)

                if ops["truck_count"] > 0:
                    enriched["miles_per_truck"] = round(ops["loaded_miles"] / ops["truck_count"], 2)
                    enriched["orders_per_truck"] = round(ops["orders"] / ops["truck_count"], 2)

                total_miles = ops["loaded_miles"] + ops["empty_miles"]
                if total_miles > 0:
                    enriched["deadhead_pct"] = round((ops["empty_miles"] / total_miles) * 100, 2)

                if ops["loaded_miles"] > 0:
                    net_revenue = ops["revenue"] - ops["fuel_surcharge"]
                    enriched["lrpm"] = round(net_revenue / ops["loaded_miles"], 4)

            enriched_series.append(enriched)
        
        result = {
            "analysis_type": "ops_metrics_join",
            "time_series": enriched_series,
            "total_periods": len(enriched_series),
            "has_ops_metrics": len(ops_lookup) > 0
        }
        
        if gl_account:
            result["gl_account"] = gl_account
        
        return json.dumps(result, indent=2)
        
    except json.JSONDecodeError as e:
        return json.dumps({
            "error": "DataUnavailable",
            "source": "join_ops_metrics",
            "detail": f"Invalid JSON input: {str(e)}",
            "action": "stop"
        })
    except Exception as e:
        return json.dumps({
            "error": "ProcessingError",
            "source": "join_ops_metrics",
            "detail": str(e),
            "action": "stop"
        })

