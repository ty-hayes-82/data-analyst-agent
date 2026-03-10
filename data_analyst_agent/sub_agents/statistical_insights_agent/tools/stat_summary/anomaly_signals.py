"""Anomaly detection and correlation helpers."""

from __future__ import annotations

import os
import numpy as np
from scipy import stats as scipy_stats

from ..stat_summary.state import SummaryState


def compute_anomalies_and_correlations(state: SummaryState) -> None:
    pivot = state.pivot
    focus_settings = state.focus_settings or {}
    z_threshold = float(focus_settings.get("z_threshold", 2.0))
    anomalies: list[dict] = []
    for account in pivot.index:
        values = pivot.loc[account].values
        values_nnan = values[~np.isnan(values)]
        if len(values_nnan) == 0:
            continue
        mean = np.mean(values_nnan)
        std = np.std(values_nnan)
        if std <= 0:
            continue
        for period, val in zip(pivot.columns, values):
            if np.isnan(val):
                continue
            z = (val - mean) / std
            if abs(z) < z_threshold:
                continue
            p_value = float(scipy_stats.norm.sf(abs(z)) * 2)
            anomalies.append(
                {
                    "period": str(period),
                    "item": account,
                    "item_name": state.names_map.get(account, account),
                    "value": round(float(val), 2),
                    "z_score": round(float(z), 2),
                    "p_value": round(p_value, 6),
                    "avg": round(float(mean), 2),
                    "std": round(float(std), 2),
                }
            )

    focus_periods = int(focus_settings.get("focus_periods") or 0)
    if focus_periods <= 0:
        focus_periods = max(1, int(os.environ.get("ANALYSIS_FOCUS_PERIODS", "4")))
    periods_list = list(pivot.columns)
    recent_periods = (
        set(periods_list[-focus_periods:]) if len(periods_list) >= focus_periods else set(periods_list)
    )

    def _rank(anomaly):
        z = abs(anomaly.get("z_score", 0))
        recency = 1 if str(anomaly.get("period", "")) in recent_periods else 0
        return (recency, z)

    anomalies_sorted = sorted(anomalies, key=_rank, reverse=True)[:20]
    anomaly_latest_flag = {
        a["item"]: True for a in anomalies if a["period"] == state.latest_period
    }

    suspected_uniform_growth = _compute_uniform_growth_flag(pivot)

    correlations = _compute_correlations(state, pivot)

    state.anomalies = anomalies
    state.anomalies_sorted = anomalies_sorted
    state.anomaly_latest_flag = anomaly_latest_flag
    state.suspected_uniform_growth = suspected_uniform_growth
    state.correlations = correlations


def _compute_uniform_growth_flag(pivot) -> bool:
    try:
        corr_matrix = np.corrcoef(pivot.values)
        n = corr_matrix.shape[0]
        if n < 2:
            return False
        upper = []
        for i in range(n):
            for j in range(i + 1, n):
                if not np.isnan(corr_matrix[i, j]):
                    upper.append(abs(float(corr_matrix[i, j])))
        if not upper:
            return False
        high = len([v for v in upper if v >= 0.95])
        return (high / len(upper)) > 0.5
    except Exception:
        return False


def _compute_correlations(state: SummaryState, pivot) -> dict[str, dict]:
    correlation_items = []
    if state.ctx and state.ctx.contract:
        policies = state.ctx.contract.policies
        classification = policies.get("item_classification", {})
        revenue_policy = classification.get("revenue", {})
        starts_with = revenue_policy.get("starts_with", [])
        if isinstance(starts_with, str):
            starts_with = [starts_with]
        keywords = revenue_policy.get("keywords", [])
        correlation_items = [
            item
            for item in pivot.index
            if any(str(item).startswith(s) for s in starts_with)
            or any(kw in state.names_map.get(item, "").lower() for kw in keywords)
        ]
    if not correlation_items:
        correlation_items = list(pivot.iloc[:5].index)

    correlations: dict[str, dict] = {}
    if len(correlation_items) >= 2:
        for i in range(min(3, len(correlation_items))):
            for j in range(i + 1, min(4, len(correlation_items))):
                acc1 = correlation_items[i]
                acc2 = correlation_items[j]
                a_vals = pivot.loc[acc1].values
                b_vals = pivot.loc[acc2].values
                mask = ~(np.isnan(a_vals) | np.isnan(b_vals))
                a_vals = a_vals[mask]
                b_vals = b_vals[mask]
                if len(a_vals) < 2:
                    continue
                try:
                    corr, p_val = scipy_stats.pearsonr(a_vals, b_vals)
                    corr = float(corr) if not np.isnan(corr) else 0.0
                    p_val = float(p_val) if not np.isnan(p_val) else 1.0
                except Exception:
                    corr = float(np.corrcoef(a_vals, b_vals)[0, 1]) if len(a_vals) > 1 else 0.0
                    p_val = 1.0
                if abs(corr) > 0.7 and p_val < 0.05:
                    key = f"{acc1}_vs_{acc2}"
                    correlations[key] = {"r": round(corr, 3), "p_value": round(p_val, 6)}
    return correlations
