"""Cross-cutting pattern detection."""
from __future__ import annotations

from typing import Any, List

import numpy as np
import pandas as pd

from .....semantic.lag_utils import (
    get_effective_lag_or_default,
    resolve_effective_latest_period,
)


def detect_cross_cutting_patterns(
    df: pd.DataFrame,
    hier_col: str,
    aux_col: str,
    metric_col: str,
    time_col: str,
    variance_type: str,
    ctx: Any,
) -> List[dict]:
    """Detect auxiliary dimension values that consistently boost or drag performance.
    
    This function identifies cross-cutting patterns where an auxiliary dimension
    (e.g., Terminal, Payment Type) has a consistent effect across multiple hierarchy
    entities (e.g., LOBs, Stores). It answers questions like:
    
    - "Is Terminal X dragging performance across all LOBs?"
    - "Is Payment Type Y boosting revenue for most stores?"
    
    The analysis computes period-over-period changes for each (hierarchy, auxiliary)
    pair, then aggregates by auxiliary dimension to find consistent effects.
    
    Args:
        df: DataFrame with columns [hier_col, aux_col, metric_col, time_col].
        hier_col: Hierarchy dimension column (e.g., "line_of_business").
        aux_col: Auxiliary dimension column (e.g., "terminal_name").
        metric_col: Target metric column (e.g., "revenue").
        time_col: Time period column (e.g., "week_ending").
        variance_type: "MoM" or "YoY" for period comparison.
        ctx: ADK context with contract and target_metric for lag calculation.
    
    Returns:
        List of pattern dicts sorted by absolute mean_impact_pct, each with:
            auxiliary_value: Auxiliary dimension value (e.g., "Terminal_123")
            effect_direction: "positive" or "negative"
            mean_impact_pct: Average % change across affected entities
            affected_entities: List of hierarchy values (up to 5)
            affected_entity_count: Count of entities with consistent effect
            consistency: Proportion of entities affected (0.0-1.0)
            label: Human-readable description
        
        Empty list if <2 periods or no patterns detected.
    
    Example:
        >>> df = pd.DataFrame({
        ...     'lob': ['Retail', 'Retail', 'Wholesale', 'Wholesale'],
        ...     'terminal': ['T1', 'T2', 'T1', 'T2'],
        ...     'revenue': [1000, 900, 2000, 1800],
        ...     'week_ending': ['2025-01', '2025-01', '2025-01', '2025-01']
        ... })
        >>> patterns = detect_cross_cutting_patterns(
        ...     df, 'lob', 'terminal', 'revenue', 'week_ending', 'MoM', ctx
        ... )
        >>> # Returns: [
        >>> #   {
        >>> #     'auxiliary_value': 'T2',
        >>> #     'effect_direction': 'negative',
        >>> #     'mean_impact_pct': -10.5,
        >>> #     'affected_entity_count': 2,
        >>> #     'consistency': 1.0,
        >>> #     'label': 'T2 is dragging performance at 2 of 2 entities (-10.5% avg impact)'
        >>> #   }
        >>> # ]
    
    Note:
        - Requires 2+ periods for comparison
        - Negative pattern threshold: ≥60% of entities with change < -1%
        - Positive pattern threshold: ≥60% of entities with change > +1%
        - Minimum entities per auxiliary value: 2
        - Uses lag-aware period selection (respects contract lag_periods)
        - Returns top patterns sorted by absolute mean impact
    """
    """Find aux values that consistently over/under-perform across hierarchy entities."""
    periods = sorted(df[time_col].unique())
    if len(periods) < 2:
        return []

    lag = (
        get_effective_lag_or_default(ctx.contract, ctx.target_metric)
        if ctx and ctx.contract and ctx.target_metric
        else 0
    )
    effective_latest, _ = resolve_effective_latest_period(periods, lag)
    current_period = effective_latest
    current_date = pd.to_datetime(current_period)
    if variance_type.lower() == "yoy":
        prior_date = current_date - pd.DateOffset(years=1)
    elif variance_type.lower() == "mom":
        prior_date = current_date - pd.DateOffset(months=1)
    else:
        prior_date = current_date - pd.DateOffset(years=1)

    all_dates = sorted(pd.to_datetime(periods))
    best_prior = min(all_dates, key=lambda d: abs(d - prior_date)) if all_dates else None
    if best_prior is None:
        return []
    prior_period = (
        str(best_prior.strftime(ctx.contract.time.format))
        if ctx and ctx.contract
        else str(best_prior)
    )

    cur_agg = (
        df[df[time_col].astype(str) == str(current_period)]
        .groupby([hier_col, aux_col])[metric_col]
        .sum()
        .reset_index()
    )
    cur_agg.columns = [hier_col, aux_col, "current"]

    pri_agg = (
        df[df[time_col].astype(str) == prior_period]
        .groupby([hier_col, aux_col])[metric_col]
        .sum()
        .reset_index()
    )
    pri_agg.columns = [hier_col, aux_col, "prior"]

    merged = cur_agg.merge(pri_agg, on=[hier_col, aux_col], how="outer").fillna(0)
    merged["pct_change"] = np.where(
        merged["prior"].abs() > 0,
        (merged["current"] - merged["prior"]) / merged["prior"].abs() * 100,
        0,
    )

    aux_stats = (
        merged.groupby(aux_col)
        .agg(
            n=("pct_change", "size"),
            mean_impact=("pct_change", "mean"),
            neg_count=("pct_change", lambda x: (x < -1).sum()),
            pos_count=("pct_change", lambda x: (x > 1).sum()),
        )
        .reset_index()
    )

    aux_stats["consistency_neg"] = aux_stats["neg_count"] / aux_stats["n"]
    aux_stats["consistency_pos"] = aux_stats["pos_count"] / aux_stats["n"]

    patterns: List[dict] = []
    drags = aux_stats[(aux_stats["consistency_neg"] >= 0.6) & (aux_stats["n"] >= 2)].copy()
    
    # Vectorized processing of drags (avoid iterrows)
    if not drags.empty:
        # Get affected entities for each aux_val
        def get_affected_entities(aux_val):
            return merged[(merged[aux_col] == aux_val) & (merged["pct_change"] < -1)][
                hier_col
            ].tolist()[:5]
        
        drags['affected_entities'] = drags[aux_col].apply(get_affected_entities)
        drags['auxiliary_value'] = drags[aux_col].astype(str)
        drags['effect_direction'] = 'negative'
        drags['mean_impact_pct'] = drags['mean_impact'].round(1)
        drags['affected_entity_count'] = drags['neg_count'].astype(int)
        drags['consistency'] = drags['consistency_neg'].round(2)
        drags['label'] = drags.apply(
            lambda r: f"{r[aux_col]} is dragging performance at {int(r['neg_count'])} of {int(r['n'])} "
                     f"entities ({float(r['mean_impact']):+.1f}% avg impact)",
            axis=1
        )
        
        patterns.extend(drags[[
            'auxiliary_value', 'effect_direction', 'mean_impact_pct', 
            'affected_entities', 'affected_entity_count', 'consistency', 'label'
        ]].to_dict('records'))

    boosts = aux_stats[(aux_stats["consistency_pos"] >= 0.6) & (aux_stats["n"] >= 2)].copy()
    
    # Vectorized processing of boosts (avoid iterrows)
    if not boosts.empty:
        # Get affected entities for each aux_val
        def get_affected_entities(aux_val):
            return merged[(merged[aux_col] == aux_val) & (merged["pct_change"] > 1)][
                hier_col
            ].tolist()[:5]
        
        boosts['affected_entities'] = boosts[aux_col].apply(get_affected_entities)
        boosts['auxiliary_value'] = boosts[aux_col].astype(str)
        boosts['effect_direction'] = 'positive'
        boosts['mean_impact_pct'] = boosts['mean_impact'].round(1)
        boosts['affected_entity_count'] = boosts['pos_count'].astype(int)
        boosts['consistency'] = boosts['consistency_pos'].round(2)
        boosts['label'] = boosts.apply(
            lambda r: f"{r[aux_col]} is boosting performance at {int(r['pos_count'])} of {int(r['n'])} "
                     f"entities ({float(r['mean_impact']):+.1f}% avg impact)",
            axis=1
        )
        
        patterns.extend(boosts[[
            'auxiliary_value', 'effect_direction', 'mean_impact_pct', 
            'affected_entities', 'affected_entity_count', 'consistency', 'label'
        ]].to_dict('records'))

    patterns.sort(key=lambda p: abs(p["mean_impact_pct"]), reverse=True)
    return patterns
