"""ANOVA helpers for cross-dimension analysis."""
from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd


def compute_two_way_anova(
    df: pd.DataFrame,
    hier_col: str,
    aux_col: str,
    metric_col: str,
    param_cap: int,
) -> Dict:
    """Run two-way ANOVA and return eta-squared + interaction stats."""
    try:
        from statsmodels.formula.api import ols
        from statsmodels.stats.anova import anova_lm

        work = df[[hier_col, aux_col, metric_col]].dropna()
        if len(work) < 10:
            return {"skipped": True, "reason": "Insufficient data for ANOVA"}

        n_hier = work[hier_col].nunique()
        n_aux = work[aux_col].nunique()
        if n_hier * n_aux > param_cap:
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
                    "p_value": round(float(row["PR(>F)"]), 6)
                    if not np.isnan(row["PR(>F)"]) else None,
                }
            return {"eta_squared": 0.0, "f_statistic": None, "p_value": None}

        hier_key = f"Q('{hier_col}')"
        aux_key = f"Q('{aux_col}')"
        interaction_key = f"Q('{hier_col}'):Q('{aux_col}')"

        hier_stats = _extract(hier_key)
        aux_stats = _extract(aux_key)
        inter_stats = _extract(interaction_key)

        residual_pct = (
            float(table.loc["Residual", "sum_sq"] / total_ss)
            if "Residual" in table.index
            else 0.0
        )

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
        interpretation = (
            "; ".join(interp_parts) if interp_parts else "No significant interaction detected."
        )

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
        pass

    return _fallback_one_way(
        df[[hier_col, aux_col, metric_col]].dropna().rename(columns={metric_col: "value"}),
        hier_col,
        aux_col,
    )


def _fallback_one_way(work: pd.DataFrame, hier_col: str, aux_col: str) -> Dict:
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
