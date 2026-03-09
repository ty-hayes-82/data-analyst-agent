"""Shared helpers for insight card formatting and totals."""

from __future__ import annotations

from typing import Any


def _compute_grand_total(stats: dict) -> float:
    """Best-effort grand total from summary_stats, monthly_totals, or top_drivers."""
    ss = stats.get("summary_stats", {})
    if isinstance(ss, dict) and ss.get("grand_total"):
        try:
            return abs(float(ss["grand_total"]))
        except (ValueError, TypeError):
            pass

    monthly_totals = stats.get("monthly_totals", {})
    if isinstance(monthly_totals, dict) and monthly_totals:
        try:
            return abs(sum(float(v) for v in monthly_totals.values()))
        except (ValueError, TypeError):
            pass

    top_drivers = stats.get("top_drivers", [])
    total = 0.0
    for driver in top_drivers:
        try:
            total += abs(float(driver.get("variance", 0)))
        except (ValueError, TypeError):
            continue
    return total


def _item_total_from_drivers(item_name: str, stats: dict) -> float:
    drivers = stats.get("top_drivers", [])
    for driver in drivers:
        if driver.get("item") == item_name:
            try:
                return float(driver.get("variance", 0))
            except (ValueError, TypeError):
                return 0.0
    return 0.0


__all__ = ["_compute_grand_total", "_item_total_from_drivers"]
