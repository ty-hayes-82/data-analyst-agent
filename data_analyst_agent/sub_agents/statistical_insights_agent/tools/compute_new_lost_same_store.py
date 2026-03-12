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
New / Lost / Same-Store Decomposition Tool

Decomposes period-over-period variance into three components:
- New entities: present in current period but absent in prior period
- Lost entities: present in prior period but absent in current period
- Same-store: entities present in both periods (organic change)

This analysis reveals whether aggregate changes are driven by portfolio
churn (new/lost entities) or organic growth/decline in the existing base.
"""

import json
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional


async def compute_new_lost_same_store(comparison: str = "MoM", top_n: int = 10, pre_resolved: Optional[dict] = None) -> str:
    """Decompose period-over-period variance into new, lost, and same-store components.
    
    This analysis answers the critical question:
    "Is the aggregate change driven by portfolio churn (new/lost entities)
    or organic growth/decline in the existing base (same-store)?"
    
    Buckets:
        - New: Entities present in current period but absent in prior period
        - Lost: Entities present in prior period but absent in current period
        - Same-Store: Entities present in both periods (organic change)
    
    Use Cases:
        - Retail: New stores opening vs store closures vs same-store sales
        - Supply chain: New terminals vs closed terminals vs same-terminal volume
        - Revenue: New accounts vs churned accounts vs same-account growth
        - Workforce: New hires vs terminations vs existing employee productivity
    
    Args:
        comparison: Comparison type.
            - "MoM": Month-over-month (latest vs prior period)
            - "YoY": Year-over-year (latest vs same period last year)
              Requires 13+ periods. Falls back to MoM if insufficient.
        top_n: Number of top entities to return in each bucket (new/lost/same-store).
            Default 10. Top is sorted by absolute value magnitude.
        pre_resolved: Pre-resolved data bundle from compute_statistical_summary.
            If provided, skips data resolution. Must contain:
            - df: DataFrame with time, grain, metric columns
            - time_col, metric_col, grain_col, name_col: Column names
            - names_map: Dict mapping grain values to display names
    
    Returns:
        JSON string with:
            comparison: "MoM" or "YoY"
            current_period: Current period identifier (e.g., "2025-03")
            prior_period: Prior period identifier (e.g., "2025-02" or "2024-03")
            summary: {
                total_current, total_prior, total_delta: Aggregate totals
                new_total, lost_total, same_store_delta: Component totals
                new_count, lost_count, same_store_count: Entity counts
                new_pct_of_delta: % of total delta from new entities
                lost_pct_of_delta: % of total delta from lost entities (negative)
                same_store_pct_of_delta: % of total delta from same-store changes
            }
            top_new: List of {item, item_name, current_value} for top new entities
            top_lost: List of {item, item_name, prior_value} for top lost entities
            top_same_store_movers: List of {item, item_name, current, prior, delta, delta_pct}
                for same-store entities with largest absolute delta, sorted descending.
        
        Or {"warning": "InsufficientPeriods", ...} if <2 periods available
        Or {"error": "NewLostSameStoreFailed", ...} on exception
    
    Raises:
        ValueError: Via resolve_data_and_columns if pre_resolved not provided
            and context/data resolution fails.
    
    Example:
        >>> result = await compute_new_lost_same_store(comparison="MoM", top_n=5)
        >>> # Returns: {
        >>> #   "summary": {
        >>> #     "total_delta": 1500,
        >>> #     "new_total": 800,
        >>> #     "lost_total": 200,
        >>> #     "same_store_delta": 900,
        >>> #     "new_pct_of_delta": 53.3,
        >>> #     "lost_pct_of_delta": -13.3,
        >>> #     "same_store_pct_of_delta": 60.0
        >>> #   },
        >>> #   "top_new": [{"item": "Store_123", "item_name": "Downtown", "current_value": 500}, ...]
        >>> # }
        
        >>> # Interpretation: 53% of the growth came from new stores,
        >>> # 13% offset by store closures, 60% from existing stores.
    
    Note:
        - Percentages may not sum to 100% due to rounding
        - new_pct + lost_pct + same_store_pct should ≈ 100%
        - Requires grain_col values to be entity identifiers (e.g., store_id)
        - YoY comparison requires 13+ periods (12 months + 1 for latest)
    """
    try:
        if pre_resolved:
            df = pre_resolved["df"].copy()
            time_col = pre_resolved["time_col"]
            metric_col = pre_resolved["metric_col"]
            grain_col = pre_resolved["grain_col"]
            name_col = pre_resolved["name_col"]
            names_map = pre_resolved["names_map"]
        else:
            from ...data_cache import resolve_data_and_columns
            try:
                df, time_col, metric_col, grain_col, name_col, ctx = resolve_data_and_columns("NewLostSameStore")
            except ValueError as e:
                return json.dumps({"error": str(e)}, indent=2)
            df[metric_col] = pd.to_numeric(df[metric_col], errors='coerce').fillna(0)
            names_map = dict(zip(df[grain_col], df[name_col]))
        
        periods = sorted(df[time_col].unique())
        periods_available = len(periods)
        
        if periods_available < 2:
            return json.dumps({
                "warning": "InsufficientPeriods",
                "message": f"New/Lost/Same-Store analysis requires at least 2 periods. Only {periods_available} available.",
                "comparison": comparison,
                "summary": {},
                "top_new": [],
                "top_lost": [],
                "top_same_store_movers": []
            }, indent=2)
        
        current_period = periods[-1]
        
        if comparison == "YoY":
            if periods_available < 13:
                print(f"[NewLostSameStore] YoY requires 13+ periods, only {periods_available} available. Falling back to MoM.")
                comparison = "MoM"
                prior_period = periods[-2]
            else:
                prior_period = periods[-13]
        else:
            prior_period = periods[-2]
        
        current_df = df[df[time_col] == current_period]
        prior_df = df[df[time_col] == prior_period]
        
        current_entities = set(current_df[grain_col].unique())
        prior_entities = set(prior_df[grain_col].unique())
        
        new_entities = current_entities - prior_entities
        lost_entities = prior_entities - current_entities
        same_store_entities = current_entities & prior_entities
        
        new_count = len(new_entities)
        lost_count = len(lost_entities)
        same_store_count = len(same_store_entities)
        
        print(f"[NewLostSameStore] {new_count} new, {lost_count} lost, {same_store_count} same-store entities")
        
        if new_entities:
            new_df = current_df[current_df[grain_col].isin(new_entities)]
            new_total = float(new_df[metric_col].sum())
        else:
            new_total = 0.0
        
        if lost_entities:
            lost_df = prior_df[prior_df[grain_col].isin(lost_entities)]
            lost_total = float(lost_df[metric_col].sum())
        else:
            lost_total = 0.0
        
        if same_store_entities:
            same_store_current_df = current_df[current_df[grain_col].isin(same_store_entities)]
            same_store_prior_df = prior_df[prior_df[grain_col].isin(same_store_entities)]
            same_store_current = float(same_store_current_df[metric_col].sum())
            same_store_prior = float(same_store_prior_df[metric_col].sum())
            same_store_delta = same_store_current - same_store_prior
        else:
            same_store_current = 0.0
            same_store_prior = 0.0
            same_store_delta = 0.0
        
        total_current = float(current_df[metric_col].sum())
        total_prior = float(prior_df[metric_col].sum())
        total_delta = total_current - total_prior
        
        if total_delta != 0:
            new_pct_of_delta = (new_total / total_delta) * 100
            lost_pct_of_delta = (-lost_total / total_delta) * 100
            same_store_pct_of_delta = (same_store_delta / total_delta) * 100
        else:
            new_pct_of_delta = 0.0
            lost_pct_of_delta = 0.0
            same_store_pct_of_delta = 0.0
        
        top_new = []
        if new_entities:
            new_agg = new_df.groupby(grain_col)[metric_col].sum().reset_index()
            new_agg = new_agg.sort_values(metric_col, key=abs, ascending=False).head(top_n)
            # Vectorized conversion instead of iterrows()
            new_agg['item_name'] = new_agg[grain_col].map(lambda x: names_map.get(x, x))
            top_new = new_agg.rename(columns={
                grain_col: "item",
                metric_col: "current_value"
            })[["item", "item_name", "current_value"]].to_dict("records")
            # Round values
            for record in top_new:
                record["current_value"] = round(float(record["current_value"]), 2)
        
        top_lost = []
        if lost_entities:
            lost_agg = lost_df.groupby(grain_col)[metric_col].sum().reset_index()
            lost_agg = lost_agg.sort_values(metric_col, key=abs, ascending=False).head(top_n)
            # Vectorized conversion instead of iterrows()
            lost_agg['item_name'] = lost_agg[grain_col].map(lambda x: names_map.get(x, x))
            top_lost = lost_agg.rename(columns={
                grain_col: "item",
                metric_col: "prior_value"
            })[["item", "item_name", "prior_value"]].to_dict("records")
            # Round values
            for record in top_lost:
                record["prior_value"] = round(float(record["prior_value"]), 2)
        
        top_same_store_movers = []
        if same_store_entities:
            current_by_entity = same_store_current_df.groupby(grain_col)[metric_col].sum()
            prior_by_entity = same_store_prior_df.groupby(grain_col)[metric_col].sum()
            
            same_store_changes = []
            for entity in same_store_entities:
                curr_val = float(current_by_entity.get(entity, 0))
                prior_val = float(prior_by_entity.get(entity, 0))
                delta = curr_val - prior_val
                delta_pct = ((delta / prior_val) * 100) if prior_val != 0 else 0.0
                same_store_changes.append({
                    "item": entity,
                    "item_name": names_map.get(entity, entity),
                    "current": round(curr_val, 2),
                    "prior": round(prior_val, 2),
                    "delta": round(delta, 2),
                    "delta_pct": round(delta_pct, 1)
                })
            
            same_store_changes.sort(key=lambda x: abs(x["delta"]), reverse=True)
            top_same_store_movers = same_store_changes[:top_n]
        
        result = {
            "comparison": comparison,
            "current_period": str(current_period),
            "prior_period": str(prior_period),
            "summary": {
                "total_current": round(total_current, 2),
                "total_prior": round(total_prior, 2),
                "total_delta": round(total_delta, 2),
                "new_total": round(new_total, 2),
                "lost_total": round(lost_total, 2),
                "same_store_current": round(same_store_current, 2),
                "same_store_prior": round(same_store_prior, 2),
                "same_store_delta": round(same_store_delta, 2),
                "new_count": new_count,
                "lost_count": lost_count,
                "same_store_count": same_store_count,
                "new_pct_of_delta": round(new_pct_of_delta, 1),
                "lost_pct_of_delta": round(lost_pct_of_delta, 1),
                "same_store_pct_of_delta": round(same_store_pct_of_delta, 1)
            },
            "top_new": top_new,
            "top_lost": top_lost,
            "top_same_store_movers": top_same_store_movers
        }
        
        return json.dumps(result, indent=2)
        
    except Exception as e:
        return json.dumps({
            "error": "NewLostSameStoreFailed",
            "message": f"Failed to compute new/lost/same-store decomposition: {str(e)}",
            "summary": {},
            "top_new": [],
            "top_lost": [],
            "top_same_store_movers": []
        }, indent=2)
