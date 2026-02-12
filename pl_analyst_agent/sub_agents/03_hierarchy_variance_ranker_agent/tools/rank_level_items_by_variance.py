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
Rank level items by variance.
"""

import json


async def rank_level_items_by_variance(level_data: str, variance_type: str = "yoy") -> str:
    """
    Rank level items by absolute dollar variance.
    
    Args:
        level_data: JSON from aggregate_by_level
        variance_type: "yoy" (year-over-year), "mom" (month-over-month), or "3mma"
    
    Returns:
        JSON with level items ranked by absolute variance, showing cumulative %.
    """
    try:
        parsed = json.loads(level_data)
        
        if "level_items" not in parsed:
            return json.dumps({
                "error": "DataUnavailable",
                "source": "rank_level_items_by_variance",
                "detail": "Input must contain 'level_items' from aggregate_by_level",
                "action": "stop"
            })
        
        level_items = parsed["level_items"]
        periods = parsed.get("periods", [])
        
        if len(periods) < 2:
            return json.dumps({
                "error": "InsufficientData",
                "source": "rank_level_items_by_variance",
                "detail": "Need at least 2 periods for variance calculation",
                "action": "stop"
            })
        
        # Sort periods to ensure chronological order
        periods = sorted(periods)
        
        # Calculate variances based on type
        item_variances = []
        
        for item in level_items:
            level_item_name = item["level_item"]
            time_series = item["time_series"]
            
            if variance_type == "yoy":
                # Year-over-year: compare same month last year
                recent_period = periods[-1]
                # Try to find period 12 months ago
                prior_period = periods[-13] if len(periods) >= 13 else periods[0]
            elif variance_type == "mom":
                # Month-over-month: compare to previous month
                recent_period = periods[-1]
                prior_period = periods[-2]
            else:  # 3mma
                # 3-month moving average
                if len(periods) < 6:
                    recent_period = periods[-1]
                    prior_period = periods[0]
                else:
                    recent_period = periods[-1]
                    prior_period = periods[-4]
            
            recent_amount = time_series.get(recent_period, 0)
            prior_amount = time_series.get(prior_period, 0)
            variance_dollar = recent_amount - prior_amount
            variance_pct = (variance_dollar / prior_amount * 100) if prior_amount != 0 else 0
            
            item_variances.append({
                "level_item": level_item_name,
                "recent_amount": round(recent_amount, 2),
                "prior_amount": round(prior_amount, 2),
                "variance_dollar": round(variance_dollar, 2),
                "variance_pct": round(variance_pct, 2),
                "abs_variance_dollar": abs(variance_dollar)
            })
        
        # Sort by absolute variance (largest first)
        item_variances.sort(key=lambda x: x["abs_variance_dollar"], reverse=True)
        
        # Calculate cumulative percentage
        total_abs_variance = sum(item["abs_variance_dollar"] for item in item_variances)
        cumulative = 0.0
        
        ranked_items = []
        for rank, item in enumerate(item_variances, start=1):
            cumulative += item["abs_variance_dollar"]
            cumulative_pct = (cumulative / total_abs_variance * 100) if total_abs_variance > 0 else 0
            
            ranked_items.append({
                "rank": rank,
                "level_item": item["level_item"],
                "variance_dollar": item["variance_dollar"],
                "variance_pct": item["variance_pct"],
                "abs_variance_dollar": round(item["abs_variance_dollar"], 2),
                "cumulative_pct": round(cumulative_pct, 1),
                "recent_amount": item["recent_amount"],
                "prior_amount": item["prior_amount"]
            })
        
        return json.dumps({
            "analysis_type": "level_item_variance_ranking",
            "level_number": parsed.get("level_number"),
            "variance_type": variance_type,
            "total_abs_variance_dollar": round(total_abs_variance, 2),
            "items_count": len(ranked_items),
            "ranked_items": ranked_items
        }, indent=2)
        
    except json.JSONDecodeError as e:
        return json.dumps({
            "error": "InvalidJSON",
            "source": "rank_level_items_by_variance",
            "detail": str(e),
            "action": "stop"
        })
    except Exception as e:
        return json.dumps({
            "error": "ProcessingFailed",
            "source": "rank_level_items_by_variance",
            "detail": str(e),
            "action": "stop"
        })

