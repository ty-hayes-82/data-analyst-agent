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
Identify top level drivers for drill-down.
"""

import json


async def identify_top_level_drivers(ranked_data: str, top_n: int = 5, cumulative_threshold: float = 80.0) -> str:
    """
    Identify top N level items OR those explaining cumulative_threshold% of variance.
    
    Args:
        ranked_data: JSON from rank_level_items_by_variance
        top_n: Maximum number of items to select (default: 5)
        cumulative_threshold: Cumulative variance % threshold (default: 80)
    
    Returns:
        JSON with top driver level items selected for drill-down.
    """
    try:
        parsed = json.loads(ranked_data)
        
        if "ranked_items" not in parsed:
            return json.dumps({
                "error": "DataUnavailable",
                "source": "identify_top_level_drivers",
                "detail": "Input must contain 'ranked_items' from rank_level_items_by_variance",
                "action": "stop"
            })
        
        ranked_items = parsed["ranked_items"]
        total_variance = parsed.get("total_abs_variance_dollar", 0)
        
        # Select items: top N OR those reaching cumulative threshold
        selected_items = []
        
        for i, item in enumerate(ranked_items):
            if i < top_n or item["cumulative_pct"] <= cumulative_threshold:
                selected_items.append(item)
            else:
                break
        
        # If we hit cumulative threshold before top_n, that's fine
        final_cumulative_pct = selected_items[-1]["cumulative_pct"] if selected_items else 0
        
        return json.dumps({
            "analysis_type": "top_level_driver_identification",
            "level_number": parsed.get("level_number"),
            "selection_criteria": {
                "top_n": top_n,
                "cumulative_threshold_pct": cumulative_threshold
            },
            "top_items": selected_items,
            "items_selected_count": len(selected_items),
            "variance_explained_pct": round(final_cumulative_pct, 1),
            "total_variance_dollar": round(total_variance, 2),
            "recommendation": f"Deep-dive into {', '.join([item['level_item'] for item in selected_items[:3]])} (explaining {final_cumulative_pct:.0f}% of total variance)"
        }, indent=2)
        
    except json.JSONDecodeError as e:
        return json.dumps({
            "error": "InvalidJSON",
            "source": "identify_top_level_drivers",
            "detail": str(e),
            "action": "stop"
        })
    except Exception as e:
        return json.dumps({
            "error": "ProcessingFailed",
            "source": "identify_top_level_drivers",
            "detail": str(e),
            "action": "stop"
        })

