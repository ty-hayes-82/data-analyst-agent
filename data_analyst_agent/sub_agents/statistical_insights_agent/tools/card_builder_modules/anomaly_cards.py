"""Card builders focused on anomalies and deviations."""

from __future__ import annotations

from ..card_formatters import _item_total_from_drivers
from ..priority_engine import (
    _anomaly_priority,
    _composite_score,
    _magnitude_impact,
    _materiality_weight,
    _priority_label,
    _statistical_impact,
)

def _build_anomaly_cards(
    anomalies: list[dict],
    grand_total: float,
    stats: dict,
    recent_periods: frozenset[str] | None = None,
) -> list[dict]:
    cards = []
    for a in anomalies:
        z = a.get("z_score", 0.0)
        if abs(z) < 2.0:  # align with spec threshold
            continue
        item_name = a.get("item_name", a.get("item", "Unknown"))
        period = a.get("period", "N/A")
        value = a.get("value", 0.0)
        avg = a.get("avg", 0.0)
        std = a.get("std", 0.0)
        direction = "above" if value > avg else "below"
        delta = abs(value - avg)
        p_val = a.get("p_value")

        stat = _statistical_impact(z=z)
        mag = _magnitude_impact(value, avg)
        item_vol = _item_total_from_drivers(item_name, stats)
        mat = _materiality_weight(item_vol, grand_total) if grand_total else 0.5
        score = _composite_score(stat, mag, mat)

        is_recent = str(period) in recent_periods if recent_periods else False

        evidence = {"z_score": round(z, 2), "avg": avg, "std_dev": std, "value": value}
        if p_val is not None:
            try:
                evidence["p_value"] = round(float(p_val), 6)
            except (TypeError, ValueError):
                evidence["p_value"] = p_val

        card = {
            "title": f"Anomaly: {item_name} in {period}",
            "what_changed": f"{value:,.2f} -- {delta:,.2f} ({direction} avg {abs(avg):,.2f})",
            "why": f"Z-score {z:+.2f} indicates a statistically significant deviation.",
            "evidence": evidence,
            "now_what": "Investigate root cause and verify data integrity for this period.",
            "priority": _anomaly_priority(z),
            "impact_score": score,
            "materiality_weight": round(mat, 3),
            "tags": ["outlier", "z-score"],
            "recent": is_recent,
        }
        cards.append(card)
    return cards


def _build_forecast_deviation_cards(forecasts: dict | list) -> list[dict]:
    if isinstance(forecasts, dict):
        items = forecasts.get("items", [])
    elif isinstance(forecasts, list):
        items = forecasts
    else:
        return []

    cards = []
    for f in items:
        variance_pct = f.get("variance_pct", 0.0)
        variance_dollar = f.get("variance_dollar", 0.0)
        item_name = f.get("item_name", f.get("item", "Unknown"))
        forecast = f.get("forecast", 0.0)
        actual = f.get("actual", 0.0)
        mape = f.get("mape", abs(variance_pct))
        direction = "exceeded" if actual > forecast else "missed"

        mag = _magnitude_impact(actual, forecast)
        score = round(mag * 0.6, 4)

        card = {
            "title": f"Forecast Deviation: {item_name}",
            "what_changed": f"Actual {actual:,.2f} vs forecast {forecast:,.2f} ({variance_pct:+.1f}%)",
            "why": f"Actual {direction} forecast by {abs(variance_dollar):,.2f} (MAPE={mape:.1f}%).",
            "evidence": {"forecast": round(forecast, 2), "actual": round(actual, 2),
                         "variance_dollar": round(variance_dollar, 2), "variance_pct": round(variance_pct, 2)},
            "now_what": "Determine if deviation is a one-off event or a trend shift.",
            "priority": _priority_label(score),
            "impact_score": score,
            "materiality_weight": 1.0,
            "tags": ["forecast", "deviation"],
        }
        cards.append(card)
    return cards


def _build_seasonal_anomaly_cards(seasonal_analysis: dict) -> list[dict]:
    if not isinstance(seasonal_analysis, dict):
        return []
    anomalies = seasonal_analysis.get("seasonal_anomalies", [])
    cards = []
    for a in anomalies:
        z = a.get("residual_z_score", 0.0)
        if abs(z) < 1.5:
            continue
        item_name = a.get("item_name", a.get("item", "Unknown"))
        period = a.get("period", "N/A")
        residual = a.get("residual", 0.0)
        seasonal_strength = a.get("seasonal_strength", 0.0)

        stat = _statistical_impact(z=z)
        score = round(stat * 0.5, 4)

        card = {
            "title": f"Seasonal Anomaly: {item_name} in {period}",
            "what_changed": f"Residual {residual:,.2f} after seasonal adjustment (z={z:+.2f})",
            "why": f"STL decomposition anomaly (z={z:+.2f}, seasonal strength={seasonal_strength:.2f}).",
            "evidence": {"residual_z_score": round(z, 2), "residual": round(residual, 2),
                         "seasonal_strength": round(seasonal_strength, 3)},
            "now_what": "Investigate non-seasonal drivers for this anomaly.",
            "priority": _priority_label(score),
            "impact_score": score,
            "materiality_weight": 1.0,
            "tags": ["seasonal", "anomaly"],
        }
        cards.append(card)
    return cards


def _build_outlier_impact_cards(outlier_impact_data: dict) -> list[dict]:
    """
    Build insight cards from outlier impact quantification data.
    """
    if not isinstance(outlier_impact_data, dict) or "aggregate_comparison" not in outlier_impact_data:
        return []
    
    comp = outlier_impact_data.get("aggregate_comparison", {})
    latest = comp.get("latest_period", {})
    trend = comp.get("trend_slope", {})
    
    cards = []
    
    # 1. Run Rate vs Headline Card
    impact_pct = latest.get("outlier_impact_pct", 0.0)
    if abs(impact_pct) >= 3.0: # Significant impact
        score = min(abs(impact_pct) / 20.0, 0.7)
        direction = "inflated" if impact_pct > 0 else "deflated"
        
        cards.append({
            "title": f"Outlier-Adjusted Run Rate: {latest.get('without_outliers'):+,.0f}",
            "what_changed": f"Headline numbers are {direction} by {abs(impact_pct):.1f}% due to outliers.",
            "why": outlier_impact_data.get("summary", {}).get("recommendation", ""),
            "evidence": latest,
            "now_what": "Base current period assessments on the adjusted run rate to avoid over-reacting to one-time events.",
            "priority": _priority_label(score),
            "impact_score": round(score, 4),
            "materiality_weight": 1.0,
            "tags": ["run_rate", "outlier_impact"],
        })
        
    # 2. Adjusted Trend Card
    impact_on_slope = trend.get("outlier_impact_on_slope", 0.0)
    with_slope = trend.get("with_outliers", 0.0)
    if with_slope != 0 and abs(impact_on_slope / with_slope) >= 0.2: # Trend significantly affected
        score = 0.5
        cards.append({
            "title": "Outlier-Adjusted Trend",
            "what_changed": f"Organic trend is {trend.get('without_outliers'):+,.2f}/period vs headline {with_slope:+,.2f}/period.",
            "why": trend.get("interpretation", ""),
            "evidence": trend,
            "now_what": "Monitor the underlying trend to assess structural performance changes.",
            "priority": "high",
            "impact_score": score,
            "materiality_weight": 1.0,
            "tags": ["trend", "outlier_impact"],
        })
        
    return cards
