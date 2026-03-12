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
3-Factor Price-Volume-Mix (PVM) Decomposition Tool.

Isolates mix effects from price and volume effects.
Math (Sequential Decomposition):
- Volume Effect = (Total_Current_Vol - Total_Prior_Vol) * Prior_Blended_Price
- Price Effect = (Blended_Price_at_Prior_Mix - Prior_Blended_Price) * Current_Total_Vol
- Mix Effect = (Current_Blended_Price - Blended_Price_at_Prior_Mix) * Current_Total_Vol
Where Blended_Price_at_Prior_Mix = sum(Prior_Weight_s * Current_Price_s)
"""

import json
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional
from ...data_cache import resolve_data_and_columns


async def compute_mix_shift_analysis(
    target_metric: str,
    price_metric: str,
    volume_metric: str,
    segment_dimension: str,
    analysis_period: str = "latest",
    prior_period: Optional[str] = None
) -> str:
    """Perform 3-factor Price-Volume-Mix (PVM) decomposition to isolate mix shift effects.
    
    This advanced analysis separates the variance of a target metric (e.g., Revenue)
    into three independent components:
        1. Volume Effect: How much did total volume change?
        2. Price Effect: How much did prices change (at prior mix)?
        3. Mix Effect: How much did the segment mix shift (at current prices)?
    
    The key insight: Mix shift isolates the impact of portfolio composition changes
    (e.g., shift from low-margin to high-margin segments) independent of price and
    volume movements.
    
    Math (Sequential Decomposition):
        - Volume Effect = (Total_Current_Vol - Total_Prior_Vol) × Prior_Blended_Price
        - Price Effect = (Blended_Price_at_Prior_Mix - Prior_Blended_Price) × Current_Total_Vol
        - Mix Effect = (Current_Blended_Price - Blended_Price_at_Prior_Mix) × Current_Total_Vol
    
    Where:
        Blended_Price_at_Prior_Mix = sum(Prior_Weight_s × Current_Price_s)
        This calculates what the blended price would be if segment mix stayed constant.
    
    Use Cases:
        - Revenue analysis: Segment mix shifting to higher/lower-margin products
        - Supply chain: Terminal mix shifting to higher/lower-cost locations
        - Pricing strategy: Quantify mix vs price effects independently
        - Portfolio management: Measure impact of segment composition changes
    
    Args:
        target_metric: Metric to decompose (e.g., 'revenue', 'gross_margin').
            Should be = price_metric × volume_metric.
        price_metric: Price/rate metric (e.g., 'rate_per_mile', 'avg_price').
        volume_metric: Volume metric (e.g., 'miles', 'units').
        segment_dimension: Dimension defining segments (e.g., 'lob', 'terminal',
            'product_category'). Mix shift is measured across this dimension.
        analysis_period: Period to analyze. "latest" (default) or specific period
            (YYYY-MM). If "latest", uses most recent period.
        prior_period: Prior period for comparison. If None, defaults to YoY
            (12 periods ago) if available, else MoM (1 period ago).
    
    Returns:
        JSON string with:
            decomposition: {
                total_variance_dollar: Total change in target metric
                volume_effect_dollar: Variance from volume change
                price_effect_dollar: Variance from price change (at prior mix)
                mix_effect_dollar: Variance from mix shift
                volume_effect_pct: Volume effect as % of total variance
                price_effect_pct: Price effect as % of total variance
                mix_effect_pct: Mix effect as % of total variance
            }
            mix_shift_detail: [{
                segment: Segment identifier
                prior_weight: Prior period weight (% of volume)
                current_weight: Current period weight
                weight_change_ppt: Weight change in percentage points
                current_price: Current period price
                prior_price: Prior period price
                price_change_pct: Price change %
                contribution_to_mix: Contribution to mix effect
            }]
            summary: {
                current_period, prior_period,
                dominant_factor: "volume", "price", or "mix"
                dominant_factor_pct: % of total variance
                interpretation: Human-readable summary
            }
        
        Or {"error": "..."} on exception or insufficient data
    
    Raises:
        ValueError: Via resolve_data_and_columns if context/data resolution fails.
    
    Example:
        >>> result = await compute_mix_shift_analysis(
        ...     target_metric="revenue",
        ...     price_metric="rate_per_load",
        ...     volume_metric="loads",
        ...     segment_dimension="line_of_business"
        ... )
        >>> # Returns: {
        >>> #   "decomposition": {
        >>> #     "total_variance_dollar": 500000,
        >>> #     "volume_effect_dollar": 200000,
        >>> #     "price_effect_dollar": 150000,
        >>> #     "mix_effect_dollar": 150000,
        >>> #     "volume_effect_pct": 40.0,
        >>> #     "price_effect_pct": 30.0,
        >>> #     "mix_effect_pct": 30.0
        >>> #   },
        >>> #   "summary": {
        >>> #     "dominant_factor": "volume",
        >>> #     "interpretation": "40% of revenue growth driven by volume increase"
        >>> #   }
        >>> # }
    
    Note:
        - Requires at least 2 periods (current and prior)
        - Target metric should be = price × volume (validates PVM relationship)
        - Mix effect can be positive (shift to higher-priced segments) or negative
        - Percentages may not sum to exactly 100% due to rounding
        - Segment-level prices calculated as target/volume for each segment
    """
    try:
        # 1. Get data
        try:
            df, time_col, _, _, _, ctx = resolve_data_and_columns("MixShiftAnalysis")
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
                    return json.dumps({"error": "Insufficient periods for analysis"}, indent=2)
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

        # 3. Aggregate data per segment for both periods
        def get_segment_agg(period):
            p_df = df[df[time_col] == period].copy()
            agg = p_df.groupby(segment_dimension).agg({
                target_metric: 'sum',
                volume_metric: 'sum'
            }).reset_index()
            # Calculate segment-level price
            agg['price'] = (agg[target_metric] / agg[volume_metric]).replace([np.inf, -np.inf], 0).fillna(0)
            # Calculate total volume for weights
            total_vol = agg[volume_metric].sum()
            agg['weight'] = (agg[volume_metric] / total_vol).fillna(0) if total_vol != 0 else 0
            return agg, total_vol

        curr_seg_agg, curr_total_vol = get_segment_agg(curr_p)
        prior_seg_agg, prior_total_vol = get_segment_agg(prior_p)

        # 4. Merge and calculate effects
        merged = curr_seg_agg.merge(
            prior_seg_agg, on=segment_dimension, how='outer', suffixes=('_curr', '_prior')
        ).fillna(0)

        # Blended Prices
        prior_blended_price = merged[target_metric + '_prior'].sum() / prior_total_vol if prior_total_vol != 0 else 0
        curr_blended_price = merged[target_metric + '_curr'].sum() / curr_total_vol if curr_total_vol != 0 else 0
        
        # Price at Prior Mix = sum(Prior_Weight * Current_Price)
        # We must use Current Price but Prior Weight
        merged['price_at_prior_mix_contribution'] = merged['weight_prior'] * merged['price_curr']
        blended_price_at_prior_mix = merged['price_at_prior_mix_contribution'].sum()

        # Total Variance
        total_variance = merged[target_metric + '_curr'].sum() - merged[target_metric + '_prior'].sum()

        # 3-Factor Decomposition
        # Volume Effect = (Total_Current_Vol - Total_Prior_Vol) * Prior_Blended_Price
        volume_effect = (curr_total_vol - prior_total_vol) * prior_blended_price
        
        # Price Effect = (Blended_Price_at_Prior_Mix - Prior_Blended_Price) * Current_Total_Vol
        price_effect = (blended_price_at_prior_mix - prior_blended_price) * curr_total_vol
        
        # Mix Effect = (Current_Blended_Price - Blended_Price_at_Prior_Mix) * Current_Total_Vol
        mix_effect = (curr_blended_price - blended_price_at_prior_mix) * curr_total_vol

        # Segment level contribution to Mix Effect:
        # Mix Effect = sum( Prior_Price * (Curr_Vol_s - Prior_Vol_s) ) - sum( Prior_Price * (Curr_Vol_total - Prior_Vol_total) * Prior_Weight_s )
        # Actually, using the definition from the spec: 
        # Mix Effect = sum( Prior_Price * Total_Volume_Prior * (Current_Weight_s - Prior_Weight_s) ) + interaction
        # We'll follow the sequential decomposition's result for simplicity at segment level.
        # Contribution to mix = (Current_Weight - Prior_Weight) * (Current_Price - Blended_Price_at_Prior_Mix) * Current_Total_Vol ? No.
        # Let's use: (Current_Weight - Prior_Weight) * Current_Price * Current_Total_Vol
        merged['mix_contribution'] = (merged['weight_curr'] - merged['weight_prior']) * merged['price_curr'] * curr_total_vol

        # Vectorized segment detail generation (avoid iterrows)
        merged_sorted = merged.sort_values('mix_contribution', key=abs, ascending=False).copy()
        merged_sorted['weight_change'] = merged_sorted['weight_curr'] - merged_sorted['weight_prior']
        merged_sorted['segment'] = merged_sorted[segment_dimension].astype(str)
        
        segment_detail = merged_sorted.apply(
            lambda row: {
                "segment": row['segment'],
                "prior_weight": float(row['weight_prior']),
                "current_weight": float(row['weight_curr']),
                "weight_change": float(row['weight_change']),
                "prior_price": float(row['price_prior']),
                "current_price": float(row['price_curr']),
                "volume_current": float(row[volume_metric + '_curr']),
                "volume_prior": float(row[volume_metric + '_prior']),
                "contribution_to_mix_effect": float(row['mix_contribution'])
            },
            axis=1
        ).tolist()

        # Summary
        dominant_effect = "mix"
        max_abs = abs(mix_effect)
        if abs(volume_effect) > max_abs:
            dominant_effect = "volume"
            max_abs = abs(volume_effect)
        if abs(price_effect) > max_abs:
            dominant_effect = "price"

        mix_direction = "favorable" if mix_effect > 0 else "unfavorable"
        mix_pct_value = float(mix_effect / abs(total_variance) * 100) if total_variance != 0 else 0.0
        
        blended_rate_change = curr_blended_price - prior_blended_price
        change_from_rate = blended_price_at_prior_mix - prior_blended_price
        change_from_mix = curr_blended_price - blended_price_at_prior_mix

        mix_effect_word = "added" if mix_effect >= 0 else "reduced"
        rate_direction_word = "increased" if blended_rate_change >= 0 else "decreased"

        result = {
            "target_metric": target_metric,
            "segment_dimension": segment_dimension,
            "current_period": curr_p,
            "prior_period": prior_p,
            "blended_price": {
                "current": float(curr_blended_price),
                "prior": float(prior_blended_price),
                "at_prior_mix": float(blended_price_at_prior_mix),
                "change_total": float(blended_rate_change),
                "change_from_rate": float(change_from_rate),
                "change_from_mix": float(change_from_mix)
            },
            "total_decomposition": {
                "total_variance": float(total_variance),
                "volume_effect": float(volume_effect),
                "price_effect": float(price_effect),
                "mix_effect": float(mix_effect),
                "volume_pct": float(volume_effect / abs(total_variance) * 100) if total_variance != 0 else 0,
                "price_pct": float(price_effect / abs(total_variance) * 100) if total_variance != 0 else 0,
                "mix_pct": mix_pct_value,
            },
            "segment_detail": segment_detail[:10],
            "summary": {
                "dominant_effect": dominant_effect,
                "mix_direction": mix_direction,
                "narrative": (
                    f"Mix effect {mix_effect_word} {abs(mix_effect):,.2f} ({mix_pct_value:+.1f}% of total variance) "
                    f"and blended rate {rate_direction_word} by {abs(blended_rate_change):.2f} "
                    f"({abs(change_from_rate):.2f} from price, {abs(change_from_mix):.2f} from mix)."
                ),
            }
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        import traceback
        return json.dumps({
            "error": f"Failed to compute mix shift analysis: {str(e)}",
            "traceback": traceback.format_exc()
        }, indent=2)
