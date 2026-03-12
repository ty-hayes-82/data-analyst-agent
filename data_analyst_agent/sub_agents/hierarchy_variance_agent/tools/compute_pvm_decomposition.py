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
Price-Volume-Mix (PVM) Decomposition Tool.

Calculates the contribution of price changes, volume changes, and mix effects
to the total variance of a metric (usually Revenue or Margin).

Math:
- Volume Impact = (Actual Qty - Prior Qty) * Prior Price
- Price Impact = (Actual Price - Prior Price) * Actual Qty
- Total Variance = Price Impact + Volume Impact (simple 2-factor model)
"""

import json
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional
from data_analyst_agent.sub_agents.data_cache import resolve_data_and_columns


async def compute_pvm_decomposition(
    target_metric: str,
    price_metric: str,
    volume_metric: str,
    dimension: str,
    analysis_period: str = "latest",
    prior_period: Optional[str] = None
) -> str:
    """Perform 2-factor Price-Volume-Mix (PVM) decomposition for a target metric.
    
    This is a simplified version of PVM analysis that separates variance into:
        1. Volume Impact: Change from quantity differences (at prior prices)
        2. Price Impact: Change from price differences (at current quantities)
    
    Math:
        - Volume Impact = (Actual_Qty - Prior_Qty) × Prior_Price
        - Price Impact = (Actual_Price - Prior_Price) × Actual_Qty
        - Total Variance = Price Impact + Volume Impact
    
    This 2-factor model is appropriate when mix shift is less relevant (e.g.,
    single-product analysis) or when you want a simpler attribution.
    
    For full 3-factor analysis (including mix shift), use compute_mix_shift_analysis().
    
    Use Cases:
        - Per-customer revenue analysis: Price vs volume contribution
        - Per-lane logistics analysis: Rate vs load count impact
        - Simple variance attribution without mix complexity
        - Waterfall charts showing price and volume bridges
    
    Args:
        target_metric: Metric to decompose (e.g., 'revenue', 'cost').
            Should be = price_metric × volume_metric.
        price_metric: Price/rate metric (e.g., 'rate_per_mile', 'unit_price').
        volume_metric: Volume metric (e.g., 'miles', 'units', 'loads').
        dimension: Dimension to group by (e.g., 'customer', 'lane', 'product').
            Decomposition performed per dimension value.
        analysis_period: Period to analyze. "latest" (default) or specific period
            (YYYY-MM). If "latest", uses most recent period.
        prior_period: Prior period for comparison. If None, defaults to YoY
            (12 periods ago) if available, else MoM (1 period ago).
    
    Returns:
        JSON string with:
            total_variance: Aggregate variance across all dimension values
            decomposition: {
                total_price_impact: Sum of price impacts
                total_volume_impact: Sum of volume impacts
                price_impact_pct: Price impact as % of total variance
                volume_impact_pct: Volume impact as % of total variance
            }
            entity_pvm: [{
                entity: Dimension value identifier
                entity_name: Display name
                current_total: Current period value
                prior_total: Prior period value
                variance_dollar: Total variance
                price_impact: Price impact component
                volume_impact: Volume impact component
                current_qty: Current period volume
                prior_qty: Prior period volume
                current_price: Current period price
                prior_price: Prior period price
            }]
            top_price_drivers: Top N entities by price impact
            top_volume_drivers: Top N entities by volume impact
            summary: {
                current_period, prior_period,
                dominant_factor: "price" or "volume"
                dominant_factor_pct: % of total variance
            }
        
        Or {"error": "..."} on exception or insufficient data
    
    Raises:
        ValueError: Via resolve_data_and_columns if context/data resolution fails.
    
    Example:
        >>> result = await compute_pvm_decomposition(
        ...     target_metric="revenue",
        ...     price_metric="avg_rate",
        ...     volume_metric="loads",
        ...     dimension="customer"
        ... )
        >>> # Returns: {
        >>> #   "decomposition": {
        >>> #     "total_price_impact": 300000,
        >>> #     "total_volume_impact": 200000,
        >>> #     "price_impact_pct": 60.0,
        >>> #     "volume_impact_pct": 40.0
        >>> #   },
        >>> #   "top_price_drivers": [
        >>> #     {
        >>> #       "entity": "customer_123",
        >>> #       "price_impact": 150000,
        >>> #       "current_price": 2.50,
        >>> #       "prior_price": 2.00
        >>> #     }
        >>> #   ]
        >>> # }
    
    Note:
        - Requires at least 2 periods (current and prior)
        - Target metric should be = price × volume (validates PVM relationship)
        - Prices calculated as target/volume for each dimension value
        - Handles division by zero (sets price to 0 if volume is 0)
        - For 3-factor analysis (including mix shift), use compute_mix_shift_analysis()
    """
    try:
        # 1. Get data
        try:
            df, time_col, _, _, name_col, ctx = resolve_data_and_columns("PVMDecomposition")
        except ValueError as e:
            return json.dumps({"error": str(e)}, indent=2)

        # 2. Setup periods
        periods = sorted(df[time_col].unique())
        if analysis_period == "latest":
            curr_p = periods[-1]
            if not prior_period:
                # Default to YoY if possible, else MoM
                curr_idx = periods.index(curr_p)
                if curr_idx >= 12:
                    prior_p = periods[curr_idx - 12]
                elif curr_idx >= 1:
                    prior_p = periods[curr_idx - 1]
                else:
                    return json.dumps({"error": "Insufficient periods for PVM analysis"}, indent=2)
            else:
                prior_p = prior_period
        else:
            curr_p = analysis_period
            if not prior_period:
                curr_idx = periods.index(curr_p)
                prior_p = periods[curr_idx - 1] if curr_idx > 0 else None
            else:
                prior_p = prior_period

        if not prior_p or prior_p not in periods:
            return json.dumps({"error": f"Prior period {prior_p} not found"}, indent=2)

        # 3. Aggregate data for both periods
        def get_agg(period):
            p_df = df[df[time_col] == period].copy()
            agg = p_df.groupby(dimension).agg({
                target_metric: 'sum',
                volume_metric: 'sum'
            }).reset_index()
            # Calculate implied price
            agg['price'] = (agg[target_metric] / agg[volume_metric]).replace([np.inf, -np.inf], 0).fillna(0)
            return agg

        curr_agg = get_agg(curr_p)
        prior_agg = get_agg(prior_p)

        # 4. Merge and calculate impacts
        merged = curr_agg.merge(prior_agg, on=dimension, how='outer', suffixes=('_curr', '_prior')).fillna(0)
        
        # Volume Impact = (Actual Qty - Prior Qty) * Prior Price
        merged['volume_impact'] = (merged[f'{volume_metric}_curr'] - merged[f'{volume_metric}_prior']) * merged['price_prior']
        
        # Price Impact = (Actual Price - Prior Price) * Actual Qty
        merged['price_impact'] = (merged['price_curr'] - merged['price_prior']) * merged[f'{volume_metric}_curr']
        
        # Total Variance
        merged['total_variance'] = merged[f'{target_metric}_curr'] - merged[f'{target_metric}_prior']
        
        # Mix/Unexplained (should be zero in 2-factor model if metrics are perfectly related, 
        # but often there's a residual due to non-linearity or rounding)
        merged['residual'] = merged['total_variance'] - (merged['volume_impact'] + merged['price_impact'])

        # 5. Summarize
        top_drivers = merged.sort_values('total_variance', key=abs, ascending=False).head(10).copy()
        
        # Vectorized impact records (avoid iterrows)
        top_drivers['item'] = top_drivers[dimension].astype(str)
        impacts = top_drivers.apply(
            lambda row: {
                "item": row['item'],
                "total_variance": float(row['total_variance']),
                "volume_impact": float(row['volume_impact']),
                "price_impact": float(row['price_impact']),
                "residual": float(row['residual']),
                "curr_vol": float(row[f'{volume_metric}_curr']),
                "prior_vol": float(row[f'{volume_metric}_prior']),
                "curr_price": float(row['price_curr']),
                "prior_price": float(row['price_prior'])
            },
            axis=1
        ).tolist()

        result = {
            "target_metric": target_metric,
            "dimension": dimension,
            "current_period": curr_p,
            "prior_period": prior_p,
            "total_volume_impact": float(merged['volume_impact'].sum()),
            "total_price_impact": float(merged['price_impact'].sum()),
            "total_variance": float(merged['total_variance'].sum()),
            "top_drivers": impacts
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        import traceback
        return json.dumps({"error": str(e), "traceback": traceback.format_exc()}, indent=2)
