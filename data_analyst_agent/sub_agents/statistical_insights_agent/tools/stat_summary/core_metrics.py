"""Core statistical computations extracted from the monolithic summary tool."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats


def generate_account_statistics(
    pivot: pd.DataFrame, names_map: Dict[Any, Any]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], float]:
    account_stats: List[Dict[str, Any]] = []
    for account in pivot.index:
        values = pivot.loc[account].values
        values_clean = values[~np.isnan(values)]
        if len(values_clean) == 0:
            continue

        avg = float(np.mean(values_clean))
        std = float(np.std(values_clean))
        cv = abs(std / avg) if avg != 0 else 0

        last_values = values_clean[-3:] if len(values_clean) >= 3 else values_clean
        slope = 0.0
        slope_p_value = 1.0
        slope_r_value = 0.0
        if len(last_values) >= 3:
            x = np.arange(len(last_values), dtype=float)
            try:
                lr = scipy_stats.linregress(x, last_values)
                slope = float(lr.slope)
                slope_p_value = float(lr.pvalue) if not np.isnan(lr.pvalue) else 1.0
                slope_r_value = float(lr.rvalue) if not np.isnan(lr.rvalue) else 0.0
            except Exception:
                slope = float(np.polyfit(x, last_values, 1)[0])

        acceleration = 0.0
        if len(values_clean) >= 6:
            prev_3 = values_clean[-6:-3]
            x2 = np.arange(len(prev_3), dtype=float)
            try:
                lr2 = scipy_stats.linregress(x2, prev_3)
                slope_prev = float(lr2.slope)
            except Exception:
                slope_prev = float(np.polyfit(x2, prev_3, 1)[0])
            acceleration = float(slope - slope_prev)

        item_name = names_map.get(account, account)
        account_stats.append(
            {
                "item": account,
                "item_name": item_name,
                "avg": round(avg, 2),
                "std": round(std, 2),
                "cv": round(cv, 4),
                "slope_3mo": round(slope, 2),
                "slope_3mo_p_value": round(slope_p_value, 6),
                "slope_3mo_r_value": round(slope_r_value, 4),
                "acceleration_3mo": round(acceleration, 2),
                "min": round(float(np.min(values_clean)), 2),
                "max": round(float(np.max(values_clean)), 2),
            }
        )

    account_stats_sorted = sorted(account_stats, key=lambda x: abs(x["avg"]), reverse=True)
    top_drivers = account_stats_sorted[:10]
    most_volatile = sorted(account_stats, key=lambda x: x["cv"], reverse=True)[:10]
    total_avg_mag = sum(abs(a["avg"]) for a in account_stats) or 1e-9
    return account_stats, top_drivers, most_volatile, total_avg_mag


def detect_anomalies(
    pivot: pd.DataFrame,
    names_map: Dict[Any, Any],
    latest_period: str,
    recent_periods: Sequence[str],
) -> Tuple[List[Dict[str, Any]], Dict[Any, bool]]:
    anomalies: List[Dict[str, Any]] = []
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
            if abs(z) >= 2.0:
                item_name = names_map.get(account, account)
                p_value = float(scipy_stats.norm.sf(abs(z)) * 2)
                anomalies.append(
                    {
                        "period": str(period),
                        "item": account,
                        "item_name": item_name,
                        "value": round(float(val), 2),
                        "z_score": round(float(z), 2),
                        "p_value": round(p_value, 6),
                        "avg": round(float(mean), 2),
                        "std": round(float(std), 2),
                    }
                )

    recent_periods_set = set(recent_periods)

    def _anomaly_rank(entry: Dict[str, Any]) -> Tuple[int, float]:
        z = abs(entry.get("z_score", 0))
        recency = 1 if str(entry.get("period", "")) in recent_periods_set else 0
        return (recency, z)

    anomalies_sorted = sorted(anomalies, key=_anomaly_rank, reverse=True)[:20]

    anomaly_latest_flag: Dict[Any, bool] = {}
    for entry in anomalies:
        if entry["period"] == latest_period:
            anomaly_latest_flag[entry["item"]] = True

    return anomalies_sorted, anomaly_latest_flag


def compute_correlations(
    pivot: pd.DataFrame,
    names_map: Dict[Any, Any],
    ctx: Any,
) -> Tuple[Dict[str, Dict[str, float]], bool]:
    correlations: Dict[str, Dict[str, float]] = {}

    correlation_items: List[Any] = []
    if ctx and getattr(ctx, "contract", None):
        policies = ctx.contract.policies
        classification = policies.get("item_classification", {})
        revenue_policy = classification.get("revenue", {})

        starts_with = revenue_policy.get("starts_with", [])
        if isinstance(starts_with, str):
            starts_with = [starts_with]

        keywords = revenue_policy.get("keywords", [])

        correlation_items = [
            item
            for item in pivot.index
            if any(str(item).startswith(prefix) for prefix in starts_with)
            or any(keyword in names_map.get(item, "").lower() for keyword in keywords)
        ]

    if not correlation_items:
        correlation_items = list(pivot.iloc[:5].index)

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
                if len(a_vals) <= 1:
                    continue
                try:
                    corr, p_val = scipy_stats.pearsonr(a_vals, b_vals)
                    corr = float(corr) if not np.isnan(corr) else 0.0
                    p_val = float(p_val) if not np.isnan(p_val) else 1.0
                except Exception:
                    with np.errstate(divide="ignore", invalid="ignore"):
                        corr = float(np.corrcoef(a_vals, b_vals)[0, 1])
                    p_val = 1.0

                if abs(corr) > 0.7 and p_val < 0.05:
                    key = f"{acc1}_vs_{acc2}"
                    correlations[key] = {"r": round(corr, 3), "p_value": round(p_val, 6)}

    suspected_uniform_growth = False
    if pivot.shape[1] < 2:
        return correlations, False
    try:
        with np.errstate(divide="ignore", invalid="ignore"):
            corr_matrix = np.corrcoef(pivot.values)
        n = corr_matrix.shape[0]
        if n >= 2:
            upper = []
            for i in range(n):
                for j in range(i + 1, n):
                    if not np.isnan(corr_matrix[i, j]):
                        upper.append(abs(float(corr_matrix[i, j])))
            if upper:
                high = len([v for v in upper if v >= 0.95])
                suspected_uniform_growth = (high / len(upper)) > 0.5
    except Exception:
        suspected_uniform_growth = False

    return correlations, suspected_uniform_growth


def build_summary_sections(
    pivot: pd.DataFrame,
    monthly_totals: Dict[str, float],
    latest_period: str,
    prev_period: Optional[str],
    temporal_grain: str,
    period_unit: str,
    account_stats: List[Dict[str, Any]],
    top_drivers: List[Dict[str, Any]],
    most_volatile: List[Dict[str, Any]],
    total_avg_mag: float,
    contribution_share: Dict[str, float],
    pattern_label_by_account: Dict[str, str],
    anomalies_sorted: List[Dict[str, Any]],
    change_series: pd.Series,
    names_map: Dict[Any, Any],
    anomaly_latest_flag: Dict[Any, bool],
    lag: int,
    lag_window: List[str],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    total_accounts = len(pivot.index)
    total_periods = len(pivot.columns)

    sorted_months = sorted(monthly_totals.items(), key=lambda x: x[1])
    highest_month = sorted_months[-1] if sorted_months else ("N/A", 0)
    lowest_month = sorted_months[0] if sorted_months else ("N/A", 0)

    summary_stats = {
        "total_items": int(total_accounts),
        "total_periods": int(total_periods),
        "period_range": f"{pivot.columns[0]} to {pivot.columns[-1]}",
        "highest_total_month": {
            "period": str(highest_month[0]),
            "total": float(highest_month[1]),
        },
        "lowest_total_month": {
            "period": str(lowest_month[0]),
            "total": float(lowest_month[1]),
        },
        "highest_total_period": {
            "period": str(highest_month[0]),
            "total": float(highest_month[1]),
        },
        "lowest_total_period": {
            "period": str(lowest_month[0]),
            "total": float(lowest_month[1]),
        },
        "total_anomalies_detected": int(len(anomalies_sorted)),
        "items_with_high_volatility": int(
            len([a for a in account_stats if a.get("cv", 0) > 0.5])
        ),
        "temporal_grain": temporal_grain,
        "period_unit": period_unit,
    }

    enhanced_top_drivers: List[Dict[str, Any]] = []
    for driver in top_drivers:
        account = driver["item"]
        enhanced_top_drivers.append(
            {
                "item": account,
                "item_name": driver["item_name"],
                "avg": driver["avg"],
                "std": driver["std"],
                "cv": driver["cv"],
                "slope_3mo": driver["slope_3mo"],
                "slope_3mo_p_value": driver.get("slope_3mo_p_value", 1.0),
                "slope_3mo_r_value": driver.get("slope_3mo_r_value", 0.0),
                "acceleration_3mo": driver.get("acceleration_3mo", 0),
                "min": driver["min"],
                "max": driver["max"],
                "share_of_total": round(abs(driver["avg"]) / total_avg_mag, 4),
                "contribution_share": round(
                    float(contribution_share.get(account, 0.0)), 4
                ),
                "pattern_label": pattern_label_by_account.get(
                    account, "run_rate_change"
                ),
                "per_unit_change": None,
                "anomaly_latest": bool(anomaly_latest_flag.get(account, False)),
            }
        )

    delta_attribution: List[Dict[str, Any]] = []
    if prev_period is not None and not change_series.empty:
        deltas_sorted = change_series.sort_values(key=lambda s: s.abs(), ascending=False)
        latest_mt = monthly_totals.get(latest_period, 0)
        prev_mt = monthly_totals.get(prev_period, 0)
        total_change = latest_mt - prev_mt or 1e-9
        for account, delta in deltas_sorted.items():
            item_name = names_map.get(account, account)
            delta_attribution.append(
                {
                    "item": account,
                    "item_name": item_name,
                    "delta": round(float(delta), 2),
                    "share": round(float(delta) / total_change, 4),
                    "pattern_label": pattern_label_by_account.get(
                        account, "run_rate_change"
                    ),
                }
            )

    if lag > 0:
        summary_stats["lag_metadata"] = {
            "lag_periods": lag,
            "effective_latest": latest_period,
            "lag_window": lag_window,
        }
    else:
        summary_stats["lag_metadata"] = None

    return summary_stats, enhanced_top_drivers, delta_attribution
