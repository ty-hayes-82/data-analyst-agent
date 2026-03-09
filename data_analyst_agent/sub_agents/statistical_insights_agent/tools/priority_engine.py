"""Priority scoring utilities for statistical insight cards."""

from __future__ import annotations

import os

PRIORITY_SORT_ORDER = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def _max_cards() -> int:
    """Max insight cards to return. Env MAX_INSIGHT_CARDS overrides default (12)."""
    raw = os.environ.get("MAX_INSIGHT_CARDS", "12").strip()
    try:
        return max(5, min(int(raw), 50))
    except ValueError:
        return 12


def _statistical_impact(z: float = 0.0, p_value: float = 1.0,
                        cv: float = 0.0, confidence: float = 0.0) -> float:
    """Score based on statistical signal strength."""
    z_score = min(abs(z) / 5.0, 1.0)
    p_score = max(1.0 - p_value, 0.0) if p_value < 1.0 else 0.0
    cv_score = min(cv / 2.0, 1.0)
    conf_score = min(confidence, 1.0)
    return max(z_score, p_score, cv_score, conf_score)


def _magnitude_impact(value: float, baseline: float) -> float:
    """Score based on how far value deviates from baseline, proportionally."""
    if baseline == 0:
        return 1.0 if value != 0 else 0.0
    pct_dev = abs(value - baseline) / abs(baseline)
    return min(pct_dev / 0.5, 1.0)  # 50%+ deviation = max score


def _materiality_weight(item_total: float, grand_total: float) -> float:
    """Weight by the item's share of the overall total.  Larger = more impactful."""
    if grand_total == 0 or item_total == 0:
        return 0.1
    share = abs(item_total) / abs(grand_total)
    return min(0.1 + share * 3.0, 1.0)


def _composite_score(stat: float, mag: float, mat: float) -> float:
    """Combine the three dimensions into a single 0..1 score."""
    raw = (stat * 0.5 + mag * 0.3) * (0.4 + 0.6 * mat)
    return round(min(raw, 1.0), 4)


def _priority_label(score: float) -> str:
    if score >= 0.6:
        return "critical"
    if score >= 0.4:
        return "high"
    if score >= 0.2:
        return "medium"
    return "low"


def _anomaly_priority(z_score: float) -> str:
    abs_z = abs(z_score)
    if abs_z >= 4.0:
        return "critical"
    if abs_z >= 3.0:
        return "high"
    if abs_z >= 2.0:
        return "medium"
    return "low"


def _priority_rank(label: str | None) -> int:
    return PRIORITY_SORT_ORDER.get((label or "").lower(), 0)


__all__ = [
    "PRIORITY_SORT_ORDER",
    "_max_cards",
    "_statistical_impact",
    "_magnitude_impact",
    "_materiality_weight",
    "_composite_score",
    "_priority_label",
    "_anomaly_priority",
    "_priority_rank",
]
