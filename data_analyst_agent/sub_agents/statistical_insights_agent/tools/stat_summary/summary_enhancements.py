"""Summary statistics, enhanced drivers, and delta attribution."""

from __future__ import annotations

import numpy as np

from ..stat_summary.state import SummaryState


def build_summary_stats(state: SummaryState) -> None:
    pivot = state.pivot
    monthly_totals = state.monthly_totals
    anomalies_sorted = state.anomalies_sorted
    total_accounts = len(pivot.index)
    total_periods = len(pivot.columns)
    sorted_months = sorted(monthly_totals.items(), key=lambda x: x[1]) if monthly_totals else []
    highest_month = sorted_months[-1] if sorted_months else ("N/A", 0)
    lowest_month = sorted_months[0] if sorted_months else ("N/A", 0)

    state.summary_stats = {
        "total_items": int(total_accounts),
        "total_periods": int(total_periods),
        "period_range": f"{pivot.columns[0]} to {pivot.columns[-1]}",
        "highest_total_month": {"period": str(highest_month[0]), "total": float(highest_month[1])},
        "lowest_total_month": {"period": str(lowest_month[0]), "total": float(lowest_month[1])},
        "highest_total_period": {"period": str(highest_month[0]), "total": float(highest_month[1])},
        "lowest_total_period": {"period": str(lowest_month[0]), "total": float(lowest_month[1])},
        "total_anomalies_detected": int(len(anomalies_sorted)),
        "items_with_high_volatility": int(len([a for a in state.account_stats if a["cv"] > 0.5])),
        "temporal_grain": state.temporal_grain,
        "period_unit": state.period_unit,
    }


def build_enhanced_drivers(state: SummaryState) -> None:
    total_avg_mag = sum(abs(a["avg"]) for a in state.account_stats) or 1e-9
    enhanced: list[dict] = []
    for driver in state.top_drivers:
        acc = driver["item"]
        enhanced.append(
            {
                "item": acc,
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
                "contribution_share": round(float(state.contribution_share.get(acc, 0.0)), 4),
                "pattern_label": state.pattern_label_by_account.get(acc, "run_rate_change"),
                "per_unit_change": None,
                "anomaly_latest": bool(state.anomaly_latest_flag.get(acc, False)),
            }
        )
    state.enhanced_top_drivers = enhanced

    if state.prev_period is None or state.change_series is None:
        return

    delta_attribution = []
    deltas_sorted = state.change_series.sort_values(key=lambda s: s.abs(), ascending=False)
    latest_mt = state.monthly_totals.get(state.latest_period, 0)
    prev_mt = state.monthly_totals.get(state.prev_period, 0)
    correct_total_change = latest_mt - prev_mt
    denom = correct_total_change if correct_total_change != 0 else 1e-9
    for acc, delta in deltas_sorted.items():
        delta_attribution.append(
            {
                "item": acc,
                "item_name": state.names_map.get(acc, acc),
                "delta": round(float(delta), 2),
                "share": round(float(delta) / denom, 4),
                "pattern_label": state.pattern_label_by_account.get(acc, "run_rate_change"),
            }
        )
    state.delta_attribution = delta_attribution
