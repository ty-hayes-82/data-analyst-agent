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
