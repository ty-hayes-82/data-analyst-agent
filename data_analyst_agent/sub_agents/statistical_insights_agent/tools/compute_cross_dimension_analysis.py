"""
Cross-Dimension Analysis Tool

Cross-analyzes a hierarchy dimension against an auxiliary dimension to surface
interaction effects, cross-cutting patterns, and trend divergences that the
standard hierarchy walk alone cannot reveal.

Statistical methods:
  - Two-way ANOVA for interaction detection (hierarchy x auxiliary)
  - Per-cell residual analysis (z-scores for anomalous combinations)
  - Cross-cutting pattern detection (aux values consistently +/- across entities)
  - Trend overlay (aux values diverging from overall trend)

Performance notes:
  High-cardinality auxiliary dimensions are automatically narrowed to the top-N
  values by metric magnitude before any expensive computation runs. This keeps
  ANOVA, residual pivots, and per-group regressions bounded regardless of how
  many raw values exist in the data.
"""

import json
import time
import numpy as np
import pandas as pd
from scipy import stats as scipy_stats
from typing import Any, Dict, List, Optional
from ....semantic.lag_utils import resolve_effective_latest_period, get_effective_lag_or_default

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
    """
    Cross-analyze a hierarchy level dimension against an auxiliary dimension.
    """
    t0 = time.perf_counter()
    try:
        if pre_resolved:
            df = pre_resolved["df"]
            time_col = pre_resolved["time_col"]
            metric_col = pre_resolved["metric_col"]
            grain_col = pre_resolved["grain_col"]
            ctx = pre_resolved["ctx"]
        else:
            from ...data_cache import resolve_data_and_columns
            try:
                df, time_col, metric_col, grain_col, _, ctx = resolve_data_and_columns(
                    "CrossDimensionAnalysis"
                )
            except ValueError as e:
                return json.dumps({"error": str(e)}, indent=2)

        if not ctx or not ctx.contract:
            return json.dumps({"error": "No dataset contract available"}, indent=2)

        contract = ctx.contract

        hierarchy_col = _resolve_hierarchy_col(contract, hierarchy_level, grain_col, df)
        if hierarchy_col is None:
            return json.dumps({
                "skipped": True,
                "reason": f"Cannot resolve hierarchy column for level {hierarchy_level}",
            }, indent=2)

        try:
            aux_dim_def = contract.get_dimension(auxiliary_dimension)
            aux_col = aux_dim_def.column
        except KeyError:
            return json.dumps({
                "skipped": True,
                "reason": f"Auxiliary dimension '{auxiliary_dimension}' not found in contract",
            }, indent=2)

        if aux_col not in df.columns:
            return json.dumps({
                "skipped": True,
                "reason": f"Column '{aux_col}' for auxiliary dimension '{auxiliary_dimension}' not in data",
            }, indent=2)

        if hierarchy_col == aux_col:
            return json.dumps({
                "skipped": True,
                "reason": f"Auxiliary dimension '{auxiliary_dimension}' is the same as hierarchy dimension at level {hierarchy_level}",
            }, indent=2)

        # --- Materiality pre-filter: keep only top-N aux values by total metric ---
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
            return json.dumps({
                "skipped": True,
                "reason": f"After filtering, only {n_unique_aux} aux values remain",
            }, indent=2)

        # --- 1. Two-way ANOVA ---
        anova_result = _compute_two_way_anova(work, hierarchy_col, aux_col, metric_col)

        # --- 2. Cell aggregation ---
        cell_agg = (
            work.groupby([hierarchy_col, aux_col])[metric_col]
            .agg(["sum", "count"])
            .reset_index()
        )
        cell_agg.columns = [hierarchy_col, aux_col, "total", "obs"]
        cell_agg_filtered = cell_agg[cell_agg["obs"] >= min_sample_size].copy()

        # --- 3. Residual analysis (vectorized) ---
        anomalous_cells = _compute_residual_analysis(
            cell_agg_filtered, hierarchy_col, aux_col, top_n_cells
        )

        # --- 4. Cross-cutting pattern detection ---
        cross_cutting = _detect_cross_cutting_patterns(
            work, hierarchy_col, aux_col, metric_col, time_col, variance_type, ctx
        )

        # --- 5. Trend overlay ---
        trends = _compute_trend_overlay(
            work, aux_col, metric_col, time_col, trend_periods
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
                "values_dropped_sample_size": int(n_unique_aux - cell_agg_filtered[aux_col].nunique()),
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
                "recommendation": _build_recommendation(
                    auxiliary_dimension, aux_explains, aux_interaction,
                    n_drags, n_boosts, cross_cutting, trends
                ),
            },
            "elapsed_seconds": round(elapsed, 2),
        }
        print(f"[CrossDimensionAnalysis] Completed {auxiliary_dimension} at level {hierarchy_level} in {elapsed:.2f}s")
        return json.dumps(result, indent=2)

    except Exception as e:
        import traceback
        return json.dumps({
            "error": f"Failed to compute cross-dimension analysis: {str(e)}",
            "traceback": traceback.format_exc(),
        }, indent=2)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_hierarchy_col(
    contract, level: int, grain_col: str, df: pd.DataFrame
) -> Optional[str]:
    """Map hierarchy level -> physical column name."""
    hierarchies = contract.hierarchies
    if not hierarchies:
        return grain_col if level == 0 else None

    hier = hierarchies[0]
    if level == 0:
        if "_total_agg" not in df.columns:
            df["_total_agg"] = "Total"
        return "_total_agg"
    if level <= len(hier.children):
        semantic = hier.children[level - 1]
        try:
            return contract.get_dimension(semantic).column
        except KeyError:
            return semantic if semantic in df.columns else None
    return None


def _compute_two_way_anova(
    df: pd.DataFrame, hier_col: str, aux_col: str, metric_col: str
) -> dict:
    """Run two-way ANOVA and return eta-squared + interaction stats."""
    try:
        from statsmodels.formula.api import ols
        from statsmodels.stats.anova import anova_lm

        work = df[[hier_col, aux_col, metric_col]].dropna()
        if len(work) < 10:
            return {"skipped": True, "reason": "Insufficient data for ANOVA"}

        n_hier = work[hier_col].nunique()
        n_aux = work[aux_col].nunique()
        if n_hier * n_aux > _ANOVA_PARAM_CAP:
            return _fallback_one_way(work.rename(columns={metric_col: "value"}), hier_col, aux_col)

        work = work.rename(columns={metric_col: "value"})
        formula = f"value ~ Q('{hier_col}') + Q('{aux_col}') + Q('{hier_col}'):Q('{aux_col}')"
        try:
            model = ols(formula, data=work).fit()
            table = anova_lm(model, typ=2)
        except Exception:
            return _fallback_one_way(work, hier_col, aux_col)

        total_ss = table["sum_sq"].sum()
        if total_ss == 0:
            return {"skipped": True, "reason": "Zero total sum of squares"}

        def _extract(idx):
            if idx in table.index:
                row = table.loc[idx]
                return {
                    "eta_squared": round(float(row["sum_sq"] / total_ss), 4),
                    "f_statistic": round(float(row["F"]), 2) if not np.isnan(row["F"]) else None,
                    "p_value": round(float(row["PR(>F)"]), 6) if not np.isnan(row["PR(>F)"]) else None,
                }
            return {"eta_squared": 0.0, "f_statistic": None, "p_value": None}

        hier_key = f"Q('{hier_col}')"
        aux_key = f"Q('{aux_col}')"
        interaction_key = f"Q('{hier_col}'):Q('{aux_col}')"

        hier_stats = _extract(hier_key)
        aux_stats = _extract(aux_key)
        inter_stats = _extract(interaction_key)

        residual_pct = float(table.loc["Residual", "sum_sq"] / total_ss) if "Residual" in table.index else 0.0

        interaction_sig = (inter_stats["p_value"] or 1.0) < 0.05
        interp_parts = []
        if aux_stats["eta_squared"] > 0.05:
            interp_parts.append(
                f"{aux_col} explains {aux_stats['eta_squared']:.0%} of variance independently"
            )
        if interaction_sig:
            interp_parts.append(
                f"the {hier_col} x {aux_col} interaction explains an additional "
                f"{inter_stats['eta_squared']:.0%} -- specific combinations matter"
            )
        interpretation = "; ".join(interp_parts) if interp_parts else "No significant interaction detected."

        return {
            "method": "two_way_anova",
            "hierarchy_eta_squared": hier_stats["eta_squared"],
            "auxiliary_eta_squared": aux_stats["eta_squared"],
            "interaction_eta_squared": inter_stats["eta_squared"],
            "interaction_f_statistic": inter_stats["f_statistic"],
            "interaction_p_value": inter_stats["p_value"],
            "residual_pct": round(residual_pct, 4),
            "interpretation": interpretation,
        }
    except ImportError:
        return _fallback_one_way(
            df[[hier_col, aux_col, metric_col]].dropna().rename(columns={metric_col: "value"}),
            hier_col, aux_col,
        )


def _fallback_one_way(work: pd.DataFrame, hier_col: str, aux_col: str) -> dict:
    """Simple one-way eta-squared per dimension when statsmodels ANOVA fails."""
    total_ss = ((work["value"] - work["value"].mean()) ** 2).sum()
    if total_ss == 0:
        return {"skipped": True, "reason": "Zero variance"}

    def _eta(col):
        gm = work.groupby(col)["value"].mean()
        gc = work.groupby(col)["value"].count()
        ssb = float((gc * (gm - work["value"].mean()) ** 2).sum())
        return round(ssb / total_ss, 4)

    return {
        "method": "one_way_fallback",
        "hierarchy_eta_squared": _eta(hier_col),
        "auxiliary_eta_squared": _eta(aux_col),
        "interaction_eta_squared": 0.0,
        "interaction_f_statistic": None,
        "interaction_p_value": None,
        "residual_pct": None,
        "interpretation": "Interaction effects not computed (fallback mode).",
    }


def _compute_residual_analysis(
    cell_agg: pd.DataFrame, hier_col: str, aux_col: str, top_n: int
) -> List[dict]:
    """Flag (entity, aux_value) cells that deviate from expected (row + col means).

    Fully vectorized -- no Python loops over the pivot.
    """
    if cell_agg.empty or cell_agg["total"].std() == 0:
        return []

    pivot = cell_agg.pivot_table(index=hier_col, columns=aux_col, values="total", aggfunc="sum")
    if pivot.empty:
        return []

    vals = pivot.values
    mask = ~np.isnan(vals)
    if mask.sum() == 0:
        return []

    grand_mean = vals[mask].mean()
    row_means = np.nanmean(vals, axis=1, keepdims=True)
    col_means = np.nanmean(vals, axis=0, keepdims=True)

    expected = row_means + col_means - grand_mean
    residuals = vals - expected
    residual_std = float(np.nanstd(residuals)) or 1e-9
    z_scores = residuals / residual_std

    # Find cells with |z| >= 2.0 using vectorized ops
    significant = np.abs(z_scores) >= 2.0
    significant &= mask
    rows_idx, cols_idx = np.where(significant)

    if len(rows_idx) == 0:
        return []

    # Sort by |z| descending and take top_n
    z_vals = np.abs(z_scores[rows_idx, cols_idx])
    order = np.argsort(-z_vals)[:top_n]

    entities = pivot.index
    aux_vals = pivot.columns

    results = []
    for i in order:
        r, c = rows_idx[i], cols_idx[i]
        actual = float(vals[r, c])
        exp = float(expected[r, c])
        z = float(z_scores[r, c])
        entity = str(entities[r])
        aux_val = str(aux_vals[c])
        results.append({
            "hierarchy_entity": entity,
            "auxiliary_value": aux_val,
            "actual": round(actual, 2),
            "expected": round(exp, 2),
            "residual": round(actual - exp, 2),
            "residual_z": round(z, 2),
            "label": (
                f"{entity} + {aux_val} is {abs(actual - exp):,.0f} "
                f"{'above' if actual > exp else 'below'} expected ({z:+.1f} sigma)"
            ),
        })

    return results


def _detect_cross_cutting_patterns(
    df: pd.DataFrame,
    hier_col: str,
    aux_col: str,
    metric_col: str,
    time_col: str,
    variance_type: str,
    ctx,
) -> List[dict]:
    """Find aux values that consistently over/under-perform across hierarchy entities.

    Uses vectorized aggregation instead of per-group Python iteration.
    """
    periods = sorted(df[time_col].unique())
    if len(periods) < 2:
        return []

    lag = get_effective_lag_or_default(ctx.contract, ctx.target_metric) if ctx and ctx.contract and ctx.target_metric else 0
        
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
    prior_period = str(best_prior.strftime(ctx.contract.time.format)) if ctx and ctx.contract else str(best_prior)

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

    # Vectorized aggregation per aux value
    aux_stats = merged.groupby(aux_col).agg(
        n=("pct_change", "size"),
        mean_impact=("pct_change", "mean"),
        neg_count=("pct_change", lambda x: (x < -1).sum()),
        pos_count=("pct_change", lambda x: (x > 1).sum()),
    ).reset_index()

    aux_stats["consistency_neg"] = aux_stats["neg_count"] / aux_stats["n"]
    aux_stats["consistency_pos"] = aux_stats["pos_count"] / aux_stats["n"]

    patterns = []
    # Only iterate the rows that pass the threshold (typically very few)
    drags = aux_stats[(aux_stats["consistency_neg"] >= 0.6) & (aux_stats["n"] >= 2)]
    for _, row in drags.iterrows():
        aux_val = row[aux_col]
        affected = merged[(merged[aux_col] == aux_val) & (merged["pct_change"] < -1)][hier_col].tolist()
        patterns.append({
            "auxiliary_value": str(aux_val),
            "effect_direction": "negative",
            "mean_impact_pct": round(float(row["mean_impact"]), 1),
            "affected_entities": affected[:5],
            "affected_entity_count": int(row["neg_count"]),
            "consistency": round(float(row["consistency_neg"]), 2),
            "label": (
                f"{aux_val} is dragging performance at {int(row['neg_count'])} of {int(row['n'])} "
                f"entities ({float(row['mean_impact']):+.1f}% avg impact)"
            ),
        })

    boosts = aux_stats[(aux_stats["consistency_pos"] >= 0.6) & (aux_stats["n"] >= 2)]
    for _, row in boosts.iterrows():
        aux_val = row[aux_col]
        affected = merged[(merged[aux_col] == aux_val) & (merged["pct_change"] > 1)][hier_col].tolist()
        patterns.append({
            "auxiliary_value": str(aux_val),
            "effect_direction": "positive",
            "mean_impact_pct": round(float(row["mean_impact"]), 1),
            "affected_entities": affected[:5],
            "affected_entity_count": int(row["pos_count"]),
            "consistency": round(float(row["consistency_pos"]), 2),
            "label": (
                f"{aux_val} is boosting performance at {int(row['pos_count'])} of {int(row['n'])} "
                f"entities ({float(row['mean_impact']):+.1f}% avg impact)"
            ),
        })

    patterns.sort(key=lambda p: abs(p["mean_impact_pct"]), reverse=True)
    return patterns


def _compute_trend_overlay(
    df: pd.DataFrame,
    aux_col: str,
    metric_col: str,
    time_col: str,
    trend_periods: int,
) -> List[dict]:
    """Compute per-aux-value trends and compare to overall trend.

    Pre-aggregates to avoid per-group linregress where possible.
    """
    periods = sorted(df[time_col].unique())
    if len(periods) < max(3, trend_periods):
        return []

    recent_periods = periods[-trend_periods:]
    recent = df[df[time_col].isin(recent_periods)]

    overall_by_period = recent.groupby(time_col)[metric_col].sum().sort_index()
    if len(overall_by_period) < 3:
        return []

    x = np.arange(len(overall_by_period), dtype=float)
    try:
        overall_lr = scipy_stats.linregress(x, overall_by_period.values)
        overall_slope = float(overall_lr.slope)
    except Exception:
        overall_slope = 0.0

    # Pre-aggregate: pivot aux_val x period sums
    pivot = recent.pivot_table(
        index=aux_col, columns=time_col, values=metric_col, aggfunc="sum"
    ).reindex(columns=recent_periods).fillna(0)

    if pivot.empty:
        return []

    results = []
    ax = np.arange(pivot.shape[1], dtype=float)

    for aux_val in pivot.index:
        row_vals = pivot.loc[aux_val].values
        non_zero = np.count_nonzero(row_vals)
        if non_zero < 3:
            continue
        try:
            lr = scipy_stats.linregress(ax, row_vals)
            slope = float(lr.slope)
            r_sq = float(lr.rvalue ** 2) if not np.isnan(lr.rvalue) else 0
        except Exception:
            continue

        if r_sq < 0.3:
            continue

        direction = "declining" if slope < 0 else "increasing"
        if overall_slope != 0:
            same_sign = np.sign(slope) == np.sign(overall_slope)
            magnitude_ratio = abs(slope) / abs(overall_slope) if overall_slope != 0 else 999
            vs_overall = "aligned" if (same_sign and 0.5 < magnitude_ratio < 2) else "diverging"
        else:
            vs_overall = "diverging" if abs(slope) > 0 else "aligned"

        if vs_overall == "diverging":
            results.append({
                "auxiliary_value": str(aux_val),
                "slope_per_period": round(slope, 2),
                "r_squared": round(r_sq, 2),
                "direction": direction,
                "vs_overall_trend": vs_overall,
                "label": (
                    f"{aux_val} {direction} at {abs(slope):,.0f}/period "
                    f"while network trend is {'flat' if abs(overall_slope) < abs(slope) * 0.1 else 'different'}"
                ),
            })

    results.sort(key=lambda r: abs(r["slope_per_period"]), reverse=True)
    return results


def _build_recommendation(
    aux_name: str,
    explains: bool,
    interaction: bool,
    n_drags: int,
    n_boosts: int,
    patterns: List[dict],
    trends: List[dict],
) -> str:
    if not explains and not interaction:
        return f"{aux_name} does not significantly explain variance. No action needed."

    parts = []
    if explains:
        parts.append(f"{aux_name} is a significant secondary driver")
    if interaction:
        parts.append("specific combinations with the hierarchy dimension matter")
    if n_drags:
        top_drag = patterns[0]["auxiliary_value"] if patterns else "unknown"
        parts.append(f"{n_drags} cross-cutting drag(s) detected (top: {top_drag})")
    if trends:
        parts.append(f"{len(trends)} diverging trend(s)")

    return ". ".join(parts) + "."
