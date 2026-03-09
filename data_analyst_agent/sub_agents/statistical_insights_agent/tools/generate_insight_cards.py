"""
Code-based Insight Card Generator -- relative-ranking approach.

Generates ALL candidate insight cards, then ranks them by a composite
impact score that accounts for:
  1. Statistical significance (z-scores, p-values, confidence)
  2. Magnitude relative to the dataset (not absolute dollar thresholds)
  3. Materiality weight (dimension's share of the total population)

The top N cards are returned.  No hard-coded dollar or percentage
thresholds gate card *creation*; thresholds are only used for priority
*labeling* after ranking.
"""

from __future__ import annotations

import os
from typing import Any

from config.statistical_analysis_config import is_tool_enabled

from .card_builders import (
    _build_anomaly_cards,
    _build_change_point_cards,
    _build_concentration_cards,
    _build_correlation_cards,
    _build_cross_dimension_cards,
    _build_cross_metric_correlation_cards,
    _build_distribution_cards,
    _build_forecast_deviation_cards,
    _build_leading_indicator_cards,
    _build_new_lost_same_store_cards,
    _build_outlier_impact_cards,
    _build_seasonal_anomaly_cards,
    _build_trend_cards,
    _build_variance_decomposition_cards,
    _build_volatility_cards,
)
from .card_formatters import _compute_grand_total
from .priority_engine import PRIORITY_SORT_ORDER, _max_cards


# ---------------------------------------------------------------------------
# Card builders -- generate ALL candidates (no filtering)
# ---------------------------------------------------------------------------











































# ---------------------------------------------------------------------------
# Cross-dimension analysis cards
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def generate_statistical_insight_cards(statistical_summary: dict) -> dict:
    """
    Convert pre-computed statistical_summary into ranked Insight Cards.

    Approach:
      1. Generate ALL candidate cards (loose filters, no hard thresholds)
      2. Score each card: statistical significance x magnitude x materiality
      3. Rank by composite score descending
      4. Return top N cards

    Args:
        statistical_summary: The dict output from compute_statistical_summary().

    Returns:
        {"insight_cards": [...], "summary_stats": {...}}
    """
    if not statistical_summary or not isinstance(statistical_summary, dict):
        return {"insight_cards": [], "summary_stats": {}}

    if "error" in statistical_summary:
        return {"error": statistical_summary["error"], "insight_cards": [], "summary_stats": {}}

    grand_total = _compute_grand_total(statistical_summary)
    cards: list[dict] = []

    # Compute recent periods for recency-weighted ranking (from ANALYSIS_FOCUS_PERIODS env)
    periods_list = sorted(statistical_summary.get("monthly_totals", {}).keys())
    focus_periods = max(1, int(os.environ.get("ANALYSIS_FOCUS_PERIODS", "4")))
    recent_periods = frozenset(periods_list[-focus_periods:]) if len(periods_list) >= focus_periods else frozenset()

    try:
        cards.extend(_build_anomaly_cards(
            statistical_summary.get("anomalies", []), grand_total, statistical_summary,
            recent_periods=recent_periods or None,
        ))
        cards.extend(_build_correlation_cards(statistical_summary.get("correlations", {})))

        top_drivers = (statistical_summary.get("enhanced_top_drivers")
                       or statistical_summary.get("top_drivers", []))
        cards.extend(_build_trend_cards(top_drivers, grand_total))
        cards.extend(_build_volatility_cards(
            statistical_summary.get("most_volatile", []), grand_total))
        if is_tool_enabled("change_points"):
            cards.extend(_build_change_point_cards(
                statistical_summary.get("change_points", []), grand_total))
        if is_tool_enabled("forecast_baseline"):
            cards.extend(_build_forecast_deviation_cards(
                statistical_summary.get("forecasts", {})))
        if is_tool_enabled("seasonal_decomposition"):
            cards.extend(_build_seasonal_anomaly_cards(
                statistical_summary.get("seasonal_analysis", {})))
        if is_tool_enabled("new_lost_same_store"):
            cards.extend(_build_new_lost_same_store_cards(
                statistical_summary.get("new_lost_same_store", {}), grand_total))
        if is_tool_enabled("concentration_analysis"):
            cards.extend(_build_concentration_cards(
                statistical_summary.get("concentration_analysis", {})))
        if is_tool_enabled("cross_metric_correlation"):
            cards.extend(_build_cross_metric_correlation_cards(
                statistical_summary.get("cross_metric_correlations", {})))
        if is_tool_enabled("lagged_correlation"):
            cards.extend(_build_leading_indicator_cards(
                statistical_summary.get("lagged_correlations", {})))
        if is_tool_enabled("variance_decomposition"):
            cards.extend(_build_variance_decomposition_cards(
                statistical_summary.get("variance_decomposition", {})))
        if is_tool_enabled("outlier_impact"):
            cards.extend(_build_outlier_impact_cards(
                statistical_summary.get("outlier_impact", {})))
        if is_tool_enabled("distribution_analysis"):
            cards.extend(_build_distribution_cards(
                statistical_summary.get("distribution_analysis", {})))
        if is_tool_enabled("cross_dimension_analysis"):
            cards.extend(_build_cross_dimension_cards(
                statistical_summary.get("cross_dimension_analysis")))
    except Exception as exc:
        cards.append({
            "title": "Card Generation Error",
            "what_changed": str(exc),
            "why": "An error occurred during card generation.",
            "evidence": {},
            "now_what": "Check statistical_summary data for unexpected shapes.",
            "priority": "low",
            "impact_score": 0.0,
            "materiality_weight": 0.0,
            "tags": ["error"],
        })

    def _priority_rank(card: dict) -> int:
        label = str(card.get("priority", "")).lower()
        return PRIORITY_SORT_ORDER.get(label, 0)

    cards.sort(key=lambda c: (
        -_priority_rank(c),
        -int(bool(c.get("recent", False))),
        -c.get("impact_score", 0.0)
    ))
    
    # Add lag metadata to summary_stats if available
    summary_stats = statistical_summary.get("summary_stats", {})
    if "lag_metadata" in statistical_summary:
        summary_stats["lag_metadata"] = statistical_summary["lag_metadata"]

    top_cards = cards[: _max_cards()]

    return {
        "insight_cards": top_cards,
        "summary_stats": statistical_summary.get("summary_stats", {}),
        "total_candidates": len(cards),
        "returned": len(top_cards),
    }
