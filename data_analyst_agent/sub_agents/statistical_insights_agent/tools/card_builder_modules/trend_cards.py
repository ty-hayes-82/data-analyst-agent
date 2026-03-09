"""Card builders for trends, volatility, and structural shifts."""

from __future__ import annotations

from ..priority_engine import (
    _composite_score,
    _magnitude_impact,
    _materiality_weight,
    _priority_label,
    _statistical_impact,
)

def _build_trend_cards(top_drivers: list[dict], grand_total: float) -> list[dict]:
    cards = []
    for d in top_drivers:
        slope = d.get("slope_3mo", 0.0)
        p_val = d.get("slope_3mo_p_value", 1.0)
        if p_val >= 0.10:  # looser than before (was 0.05)
            continue

        item_name = d.get("item_name", d.get("item", "Unknown"))
        accel = d.get("acceleration_3mo", 0.0)
        avg = d.get("avg", 0.0)
        direction = "increasing" if slope > 0 else "decreasing"

        stat = _statistical_impact(p_value=p_val)
        mag = _magnitude_impact(avg + slope, avg) if avg != 0 else 0.5
        item_vol = abs(avg) * d.get("count", 1)
        mat = _materiality_weight(item_vol, grand_total) if grand_total else 0.5
        score = _composite_score(stat, mag, mat)

        accel_note = f" (accelerating)" if abs(accel) > abs(slope) * 0.3 else ""
        
        # Wording based on significance
        if p_val < 0.05:
            sig_text = f"Statistically significant trend (p={p_val:.4f})"
        else:
            sig_text = f"Directional trend (p={p_val:.4f}, early signal)"
            
        card = {
            "title": f"Trend: {item_name} -- {direction.capitalize()}",
            "what_changed": f"3-month slope of {slope:+,.2f}/period{accel_note}",
            "why": f"{sig_text}. {direction.capitalize()} at {abs(slope):,.2f}/period.",
            "evidence": {"slope_3mo": round(slope, 2), "slope_p_value": round(p_val, 6),
                         "acceleration_3mo": round(accel, 2), "avg": avg},
            "now_what": "Monitor trend trajectory; assess if structural or seasonal.",
            "priority": _priority_label(score),
            "impact_score": score,
            "materiality_weight": round(mat, 3),
            "tags": ["trend"],
        }
        cards.append(card)
    return cards


def _build_volatility_cards(most_volatile: list[dict], grand_total: float) -> list[dict]:
    cards = []
    for d in most_volatile:
        cv = d.get("cv", 0.0)
        if cv <= 0.2:  # very loose floor
            continue
        item_name = d.get("item_name", d.get("item", "Unknown"))
        avg = d.get("avg", 0.0)
        std = d.get("std", 0.0)

        stat = _statistical_impact(cv=cv)
        item_vol = abs(avg) * d.get("count", 1)
        mat = _materiality_weight(item_vol, grand_total) if grand_total else 0.5
        score = _composite_score(stat, 0.3, mat)

        card = {
            "title": f"High Volatility: {item_name}",
            "what_changed": f"CV = {cv:.2%} (std={abs(std):,.2f} vs avg={abs(avg):,.2f})",
            "why": f"CV={cv:.3f} indicates inconsistent performance patterns.",
            "evidence": {"cv": round(cv, 4), "avg": avg, "std_dev": std},
            "now_what": "Investigate root cause of volatility; check for data quality issues.",
            "priority": _priority_label(score),
            "impact_score": score,
            "materiality_weight": round(mat, 3),
            "tags": ["volatility"],
        }
        cards.append(card)
    return cards


def _build_change_point_cards(change_points: list[dict], grand_total: float) -> list[dict]:
    if isinstance(change_points, dict):
        change_points = change_points.get("change_points", [])

    cards = []
    for cp in change_points:
        if not isinstance(cp, dict):
            continue
        item_name = cp.get("item_name", cp.get("item", "Unknown"))
        period = cp.get("period", "N/A")
        mag_dollar = cp.get("magnitude_dollar", 0.0)
        mag_pct = cp.get("magnitude_pct", 0.0)
        confidence = cp.get("confidence_score", 0.0)
        before_mean = cp.get("before_mean", 0.0)
        after_mean = cp.get("after_mean", 0.0)

        stat = _statistical_impact(confidence=confidence)
        mag = _magnitude_impact(after_mean, before_mean) if before_mean else 0.5
        mat = _materiality_weight(abs(before_mean), grand_total) if grand_total else 0.5
        score = _composite_score(stat, mag, mat)

        direction = "increased" if after_mean > before_mean else "decreased"
        card = {
            "title": f"Structural Break: {item_name} at {period}",
            "what_changed": f"Run-rate {direction} by {abs(mag_dollar):,.2f} ({mag_pct:+.1f}%) starting {period}",
            "why": f"Change point detection (confidence={confidence:.2f}). Before: {before_mean:,.2f} -> After: {after_mean:,.2f}.",
            "evidence": {"magnitude_dollar": round(mag_dollar, 2), "magnitude_pct": round(mag_pct, 2),
                         "confidence_score": round(confidence, 3), "before_mean": round(before_mean, 2),
                         "after_mean": round(after_mean, 2)},
            "now_what": "Identify the event or policy change that triggered this shift.",
            "priority": _priority_label(score),
            "impact_score": score,
            "materiality_weight": round(mat, 3),
            "tags": ["change_point", "structural_break"],
        }
        cards.append(card)
    return cards


def _build_leading_indicator_cards(lagged_data: dict) -> list[dict]:
    """
    Build insight cards from lagged correlation data.
    """
    if not isinstance(lagged_data, dict) or "leading_indicators" not in lagged_data:
        return []
    
    leading_indicators = lagged_data.get("leading_indicators", [])
    cards = []
    
    for indicator in leading_indicators[:3]:  # Top 3 leading indicators
        leader = indicator["leader"]
        follower = indicator["follower"]
        lag = indicator["optimal_lag"]
        r = indicator["lag_r"]
        improvement = indicator["improvement"]
        
        score = _statistical_impact(confidence=abs(r)) * 0.8
        
        granger_note = ""
        if "granger_causality" in indicator and indicator["granger_causality"]["significant"]:
            granger_note = " Granger causality test confirms the predictive relationship."
            score += 0.1
            
        cards.append({
            "title": f"Leading Indicator: {leader} predicts {follower}",
            "what_changed": f"{leader} leads {follower} by {lag} period{'s' if lag > 1 else ''} (r={r:+.3f}).",
            "why": f"Lagged correlation shows {improvement:+.2f} improvement over contemporaneous signals.{granger_note}",
            "evidence": indicator,
            "now_what": f"Monitor {leader} as an early warning signal for future {follower} performance.",
            "priority": _priority_label(score),
            "impact_score": round(score, 4),
            "materiality_weight": 1.0,
            "tags": ["leading_indicator", "predictive"],
        })
        
    return cards
