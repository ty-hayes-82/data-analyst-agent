"""Orchestrator for cross-dimension analysis."""
from __future__ import annotations

import json
import time
from typing import Optional

import pandas as pd

from .anova import compute_two_way_anova
from .hierarchy import resolve_hierarchy_col
from .patterns import detect_cross_cutting_patterns
from .recommendations import build_recommendation
from .residuals import compute_residual_analysis
from .trends import compute_trend_overlay

_TOP_N_AUX_VALUES = 50
_ANOVA_PARAM_CAP = 5000


async def compute_cross_dimension_analysis(
    hierarchy_level: int,
    auxiliary_dimension: str,
    variance_type: str = "yoy",
    min_sample_size: int = 10,
    max_cardinality: int = 50,
    top_n_cells: int = 10,
    trend_periods: int = 6,
    pre_resolved: Optional[dict] = None,
) -> str:
    """Cross-analyze a hierarchy dimension against an auxiliary dimension."""

    t0 = time.perf_counter()
    try:
        df, time_col, metric_col, grain_col, ctx = _resolve_frame(pre_resolved)
    except ValueError as exc:  # pragma: no cover - caught conditions bubble to JSON
        return json.dumps({"error": str(exc)}, indent=2)

    if not ctx or not ctx.contract:
        return json.dumps({"error": "No dataset contract available"}, indent=2)

    contract = ctx.contract
    hierarchy_col = resolve_hierarchy_col(contract, hierarchy_level, grain_col, df)
    if hierarchy_col is None:
        return json.dumps(
            {
                "skipped": True,
                "reason": f"Cannot resolve hierarchy column for level {hierarchy_level}",
            },
            indent=2,
        )

    try:
        aux_dim_def = contract.get_dimension(auxiliary_dimension)
        aux_col = aux_dim_def.column
    except KeyError:
        return json.dumps(
            {
                "skipped": True,
                "reason": f"Auxiliary dimension '{auxiliary_dimension}' not found in contract",
            },
            indent=2,
        )

    if aux_col not in df.columns:
        return json.dumps(
            {
                "skipped": True,
                "reason": f"Column '{aux_col}' for auxiliary dimension '{auxiliary_dimension}' not in data",
            },
            indent=2,
        )

    if hierarchy_col == aux_col:
        return json.dumps(
            {
                "skipped": True,
                "reason": (
                    f"Auxiliary dimension '{auxiliary_dimension}' is the same as "
                    f"hierarchy dimension at level {hierarchy_level}"
                ),
            },
            indent=2,
        )

    work = df[[hierarchy_col, aux_col, metric_col, time_col]].copy()
    work[metric_col] = pd.to_numeric(work[metric_col], errors="coerce").fillna(0)

    n_unique_raw = work[aux_col].nunique()
    effective_cap = min(max_cardinality, _TOP_N_AUX_VALUES)

    if n_unique_raw > effective_cap:
        top_values = (
            work.groupby(aux_col)[metric_col]
            .sum()
            .abs()
            .nlargest(effective_cap)
            .index
        )
        work = work[work[aux_col].isin(top_values)]
        print(
            f"[CrossDimensionAnalysis] Narrowed {auxiliary_dimension} from "
            f"{n_unique_raw} to top {effective_cap} values by metric magnitude"
        )

    n_unique_aux = work[aux_col].nunique()
    if n_unique_aux < 2:
        return json.dumps(
            {
                "skipped": True,
                "reason": f"After filtering, only {n_unique_aux} aux values remain",
            },
            indent=2,
        )

    anova_result = compute_two_way_anova(
        work, hierarchy_col, aux_col, metric_col, _ANOVA_PARAM_CAP
    )

    cell_agg = (
        work.groupby([hierarchy_col, aux_col])[metric_col]
        .agg(["sum", "count"])
        .reset_index()
    )
    cell_agg.columns = [hierarchy_col, aux_col, "total", "obs"]
    cell_agg_filtered = cell_agg[cell_agg["obs"] >= min_sample_size].copy()

    anomalous_cells = compute_residual_analysis(
        cell_agg_filtered, hierarchy_col, aux_col, top_n_cells
    )

    cross_cutting = detect_cross_cutting_patterns(
        work,
        hierarchy_col,
        aux_col,
        metric_col,
        time_col,
        variance_type,
        ctx,
    )

    trends = compute_trend_overlay(
        work,
        aux_col,
        metric_col,
        time_col,
        trend_periods,
    )

    aux_interaction = anova_result.get("interaction_p_value", 1.0) < 0.05
    n_drags = len([p for p in cross_cutting if p["effect_direction"] == "negative"])
    n_boosts = len([p for p in cross_cutting if p["effect_direction"] == "positive"])
    aux_explains = anova_result.get("auxiliary_eta_squared", 0) > 0.05

    elapsed = time.perf_counter() - t0
    result = {
        "hierarchy_dimension": hierarchy_col,
        "hierarchy_level": hierarchy_level,
        "auxiliary_dimension": auxiliary_dimension,
        "auxiliary_column": aux_col,
        "metric": metric_col,
        "independence_test": anova_result,
        "auxiliary_dimension_summary": {
            "unique_values_raw": int(n_unique_raw),
            "unique_values_analyzed": int(n_unique_aux),
            "pre_filter_applied": n_unique_raw > effective_cap,
            "values_dropped_sample_size": int(
                n_unique_aux - cell_agg_filtered[aux_col].nunique()
            ),
        },
        "cross_cutting_patterns": cross_cutting[:10],
        "anomalous_cells": anomalous_cells[:top_n_cells],
        "trends": trends[:5],
        "summary": {
            "auxiliary_explains_variance": aux_explains,
            "interaction_significant": aux_interaction,
            "cross_cutting_drags": n_drags,
            "cross_cutting_boosts": n_boosts,
            "anomalous_cells": len(anomalous_cells),
            "recommendation": build_recommendation(
                auxiliary_dimension,
                aux_explains,
                aux_interaction,
                n_drags,
                n_boosts,
                cross_cutting,
                trends,
            ),
        },
        "elapsed_seconds": round(elapsed, 2),
    }
    print(
        f"[CrossDimensionAnalysis] Completed {auxiliary_dimension} "
        f"at level {hierarchy_level} in {elapsed:.2f}s"
    )
    return json.dumps(result, indent=2)



def _resolve_frame(pre_resolved: Optional[dict]):
    if pre_resolved:
        return (
            pre_resolved["df"],
            pre_resolved["time_col"],
            pre_resolved["metric_col"],
            pre_resolved["grain_col"],
            pre_resolved.get("ctx"),
        )

    from ....data_cache import resolve_data_and_columns  # local import to avoid cycles

    df, time_col, metric_col, grain_col, _, ctx = resolve_data_and_columns(
        "CrossDimensionAnalysis"
    )
    return df, time_col, metric_col, grain_col, ctx
