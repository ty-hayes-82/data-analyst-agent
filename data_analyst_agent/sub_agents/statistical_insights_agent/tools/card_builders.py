"""Insight card builder functions."""

from __future__ import annotations

from typing import Any

from .priority_engine import (
    _anomaly_priority,
    _composite_score,
    _magnitude_impact,
    _materiality_weight,
    _priority_label,
    _statistical_impact,
)
from .card_formatters import _item_total_from_drivers


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

def _build_correlation_cards(correlations: dict) -> list[dict]:
    cards = []
    for key, value in correlations.items():
        if isinstance(value, dict):
            r = value.get("r", 0.0)
            p_val = value.get("p_value", 1.0)
        else:
            r = float(value)
            p_val = 0.0

        if abs(r) < 0.7:
            continue
        if p_val >= 0.05 and p_val != 0.0:
            continue

        parts = key.split("_vs_")
        item_a = parts[0] if len(parts) >= 1 else key
        item_b = parts[1] if len(parts) >= 2 else ""
        direction = "positive" if r > 0 else "negative"
        strength = "strong" if abs(r) >= 0.9 else "moderate" if abs(r) >= 0.7 else "weak-moderate"

        stat = _statistical_impact(confidence=abs(r))
        score = round(stat * 0.5, 4)

        card = {
            "title": f"Correlation: {item_a} vs {item_b}",
            "what_changed": f"{strength.capitalize()} {direction} correlation (r={r:+.3f})",
            "why": f"Pearson r={r:+.3f}" + (f", p={p_val:.4f}" if p_val < 1.0 else ""),
            "evidence": {"correlation": round(r, 3), "p_value": round(p_val, 6) if p_val < 1.0 else None},
            "now_what": "Consider joint root-cause analysis for correlated items.",
            "priority": _priority_label(score),
            "impact_score": score,
            "materiality_weight": 1.0,
            "tags": ["correlation"],
        }
        cards.append(card)
    return cards

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

def _build_new_lost_same_store_cards(nlss_data: dict, grand_total: float) -> list[dict]:
    """
    Build insight cards from new/lost/same-store decomposition data.
    
    Generates:
    - Portfolio Churn card: when new+lost volume > 20% of total delta
    - New Entity Impact card: when new entities contribute >= 30% of delta
    - Lost Entity Impact card: when lost entities are material
    - Same-Store Trend card: shows organic growth with churn stripped out
    """
    if not isinstance(nlss_data, dict):
        return []
    if nlss_data.get("error") or nlss_data.get("warning"):
        return []
    
    summary = nlss_data.get("summary", {})
    if not summary:
        return []
    
    new_total = summary.get("new_total", 0.0)
    lost_total = summary.get("lost_total", 0.0)
    same_store_delta = summary.get("same_store_delta", 0.0)
    same_store_current = summary.get("same_store_current", 0.0)
    same_store_prior = summary.get("same_store_prior", 0.0)
    new_count = summary.get("new_count", 0)
    lost_count = summary.get("lost_count", 0)
    same_store_count = summary.get("same_store_count", 0)
    total_delta = summary.get("total_delta", 0.0)
    new_pct_of_delta = summary.get("new_pct_of_delta", 0.0)
    lost_pct_of_delta = summary.get("lost_pct_of_delta", 0.0)
    same_store_pct_of_delta = summary.get("same_store_pct_of_delta", 0.0)
    
    top_new = nlss_data.get("top_new", [])
    top_lost = nlss_data.get("top_lost", [])
    top_same_store_movers = nlss_data.get("top_same_store_movers", [])
    
    cards = []
    
    churn_volume = abs(new_total) + abs(lost_total)
    if total_delta != 0 and churn_volume > 0.20 * abs(total_delta):
        churn_pct = (churn_volume / abs(total_delta)) * 100
        score = min(churn_pct / 100, 1.0) * 0.6
        
        card = {
            "title": f"Portfolio Churn: {new_count} new, {lost_count} lost entities",
            "what_changed": f"Churn volume of {churn_volume:,.0f} represents {churn_pct:.0f}% of total delta",
            "why": "Aggregate numbers mask significant entity turnover.",
            "evidence": {
                "new_count": new_count,
                "lost_count": lost_count,
                "new_total": round(new_total, 2),
                "lost_total": round(lost_total, 2),
                "churn_pct_of_delta": round(churn_pct, 1)
            },
            "now_what": "Investigate new/lost entities to determine if churn is structural or transient.",
            "priority": _priority_label(score),
            "impact_score": round(score, 4),
            "materiality_weight": 1.0,
            "tags": ["portfolio_churn", "new_lost"],
        }
        cards.append(card)
    
    if abs(new_pct_of_delta) >= 30 and new_count > 0:
        top_new_names = ", ".join([n.get("item_name", n.get("item", "?"))[:20] 
                                   for n in top_new[:3]])
        score = min(abs(new_pct_of_delta) / 100, 1.0) * 0.5
        
        card = {
            "title": f"New Entities: {new_count} contributing {new_total:+,.0f} to delta",
            "what_changed": f"New entities account for {new_pct_of_delta:+.0f}% of total change",
            "why": f"Top new: {top_new_names}" if top_new_names else "New entities entered the portfolio.",
            "evidence": {
                "new_count": new_count,
                "new_total": round(new_total, 2),
                "new_pct_of_delta": round(new_pct_of_delta, 1),
                "top_new": top_new[:5]
            },
            "now_what": "Verify new entities are expected; assess if growth is sustainable.",
            "priority": _priority_label(score),
            "impact_score": round(score, 4),
            "materiality_weight": 1.0,
            "tags": ["new_entities", "portfolio_change"],
        }
        cards.append(card)
    
    if lost_count > 0 and (abs(lost_total) > 0.1 * abs(grand_total) if grand_total else abs(lost_total) > 0):
        top_lost_names = ", ".join([n.get("item_name", n.get("item", "?"))[:20] 
                                    for n in top_lost[:3]])
        lost_impact = abs(lost_pct_of_delta) if total_delta != 0 else 0
        score = min(lost_impact / 100, 1.0) * 0.5
        
        card = {
            "title": f"Lost Entities: {lost_count} removed {lost_total:,.0f} from prior period",
            "what_changed": f"Lost entities account for {lost_pct_of_delta:+.0f}% of total change",
            "why": f"Top lost: {top_lost_names}" if top_lost_names else "Entities exited the portfolio.",
            "evidence": {
                "lost_count": lost_count,
                "lost_total": round(lost_total, 2),
                "lost_pct_of_delta": round(lost_pct_of_delta, 1),
                "top_lost": top_lost[:5]
            },
            "now_what": "Determine if lost entities are expected (discontinued) or unexpected churn.",
            "priority": _priority_label(score),
            "impact_score": round(score, 4),
            "materiality_weight": 1.0,
            "tags": ["lost_entities", "portfolio_change"],
        }
        cards.append(card)
    
    if same_store_count > 0:
        organic_growth_rate = ((same_store_delta / same_store_prior) * 100) if same_store_prior != 0 else 0.0
        score = min(abs(same_store_delta) / abs(grand_total) if grand_total else 0.3, 1.0) * 0.4
        
        top_movers_summary = ", ".join([f"{m.get('item_name', m.get('item', '?'))[:15]} ({m.get('delta', 0):+,.0f})"
                                        for m in top_same_store_movers[:3]])
        
        card = {
            "title": f"Same-Store Organic Change: {same_store_delta:+,.0f}",
            "what_changed": f"Organic growth rate of {organic_growth_rate:+.1f}% ({same_store_count} continuing entities)",
            "why": f"Top movers: {top_movers_summary}" if top_movers_summary else "Same-store entities showed aggregate change.",
            "evidence": {
                "same_store_count": same_store_count,
                "same_store_current": round(same_store_current, 2),
                "same_store_prior": round(same_store_prior, 2),
                "same_store_delta": round(same_store_delta, 2),
                "organic_growth_rate_pct": round(organic_growth_rate, 1),
                "same_store_pct_of_delta": round(same_store_pct_of_delta, 1),
                "top_movers": top_same_store_movers[:5]
            },
            "now_what": "Compare organic growth rate to targets; identify drivers of same-store change.",
            "priority": _priority_label(score),
            "impact_score": round(score, 4),
            "materiality_weight": 1.0,
            "tags": ["same_store", "organic_growth"],
        }
        cards.append(card)
    
    return cards

def _build_concentration_cards(concentration_data: dict) -> list[dict]:
    """
    Build insight cards from concentration/Pareto analysis data.
    
    Generates:
    - Portfolio Concentration card: structural overview of HHI, Gini, Pareto ratio
    - Concentration Trending card: when HHI slope is statistically significant
    - Variance Concentration card: when same entities persistently drive variance
    """
    if not isinstance(concentration_data, dict):
        return []
    if concentration_data.get("error") or concentration_data.get("warning"):
        return []
    
    cards = []
    
    lp = concentration_data.get("latest_period", {})
    if lp:
        pareto_count = lp.get("pareto_count", 0)
        pareto_ratio = lp.get("pareto_ratio", 0)
        total_entities = lp.get("total_entities", 0)
        hhi = lp.get("hhi", 0)
        hhi_label = lp.get("hhi_label", "")
        gini = lp.get("gini", 0)
        top_5_share = lp.get("top_5_share", 0)
        top_10_share = lp.get("top_10_share", 0)
        
        score = min(gini * 0.4, 0.5)
        
        card = {
            "title": f"Portfolio Concentration: Top {pareto_count} of {total_entities} entities drive 80% of total",
            "what_changed": f"HHI = {hhi:.0f} ({hhi_label}). Gini = {gini:.2f}.",
            "why": f"Top {pareto_ratio*100:.0f}% of entities account for 80% of total value. Top-5 share = {top_5_share*100:.0f}%.",
            "evidence": {
                "hhi": round(hhi, 1),
                "gini": round(gini, 3),
                "pareto_count": pareto_count,
                "pareto_ratio": round(pareto_ratio, 3),
                "top_5_share": round(top_5_share, 3),
                "top_10_share": round(top_10_share, 3),
                "total_entities": total_entities
            },
            "now_what": "Review portfolio concentration risk. High concentration increases exposure to single-entity disruptions.",
            "priority": _priority_label(score),
            "impact_score": round(score, 4),
            "materiality_weight": 1.0,
            "tags": ["concentration", "pareto"],
        }
        cards.append(card)
    
    trend = concentration_data.get("concentration_trend", {})
    if trend and "warning" not in trend:
        slope = trend.get("hhi_slope", 0)
        p_val = trend.get("hhi_slope_p_value", 1.0)
        direction = trend.get("hhi_direction", "stable")
        
        if p_val < 0.10 and abs(slope) > 0:
            score = min((1.0 - p_val) * 0.4, 0.45)
            direction_word = "more" if slope > 0 else "less"
            trend_word = "up" if slope > 0 else "down"
            
            card = {
                "title": f"Concentration {direction.capitalize()}: HHI trending {trend_word}",
                "what_changed": f"HHI slope = {slope:+.1f}/period (p={p_val:.3f}). Portfolio is becoming {direction_word} concentrated.",
                "why": f"Linear regression on HHI time series shows statistically significant {direction} trend.",
                "evidence": {
                    "hhi_slope": round(slope, 2),
                    "hhi_slope_p_value": round(p_val, 4),
                    "direction": direction,
                    "gini_slope": trend.get("gini_slope", 0),
                    "gini_direction": trend.get("gini_direction", "stable")
                },
                "now_what": f"Investigate drivers of {'increasing' if slope > 0 else 'decreasing'} concentration. {'Growing concentration may indicate market consolidation or over-reliance on key entities.' if slope > 0 else 'Diversification may improve risk profile but could indicate loss of key entities.'}",
                "priority": _priority_label(score),
                "impact_score": round(score, 4),
                "materiality_weight": 1.0,
                "tags": ["concentration", "trend"],
            }
            cards.append(card)
    
    variance = concentration_data.get("variance_concentration", {})
    persistent_movers = variance.get("persistent_top_movers", [])
    
    if persistent_movers:
        num_persistent = len(persistent_movers)
        out_of_periods = persistent_movers[0].get("out_of_periods", 0) if persistent_movers else 0
        top_movers_names = ", ".join([m.get("item_name", m.get("item", "?"))[:20] for m in persistent_movers[:3]])
        variance_top_5_share = variance.get("top_5_variance_share", 0)
        
        score = min(num_persistent / 10.0 * 0.4, 0.4)
        
        card = {
            "title": f"Variance Driven by Same {num_persistent} Entities",
            "what_changed": f"These entities appear in top-5 variance drivers in >50% of {out_of_periods} periods.",
            "why": f"Persistent movers: {top_movers_names}. Top-5 entities drive {variance_top_5_share*100:.0f}% of total period-over-period variance.",
            "evidence": {
                "persistent_mover_count": num_persistent,
                "out_of_periods": out_of_periods,
                "top_5_variance_share": round(variance_top_5_share, 3),
                "variance_pareto_ratio": variance.get("pareto_ratio", 0),
                "persistent_top_movers": persistent_movers[:5]
            },
            "now_what": "Focus root-cause analysis on persistent variance drivers. Consistent volatility from the same entities may indicate systemic issues.",
            "priority": _priority_label(score),
            "impact_score": round(score, 4),
            "materiality_weight": 1.0,
            "tags": ["concentration", "variance", "persistent_movers"],
        }
        cards.append(card)
    
    return cards

def _build_cross_metric_correlation_cards(cross_metric_data: dict) -> list[dict]:
    """
    Build insight cards from cross-metric correlation data.
    
    Generates:
    - Unexpected Correlation card: surfaces correlations between metrics with no declared dependency
    - Operational-Financial Link card: highlights strong cross-metric pairs
    - Correlation Breakdown card: surfaces dimension-level outliers
    """
    if not isinstance(cross_metric_data, dict) or "significant_pairs" not in cross_metric_data:
        return []
    
    significant_pairs = cross_metric_data.get("significant_pairs", [])
    unexpected_pairs = cross_metric_data.get("unexpected_pairs", [])
    dimension_outliers = cross_metric_data.get("dimension_outliers", [])
    
    cards = []
    
    # 1. Unexpected Correlation Card
    for pair in unexpected_pairs[:3]:  # Top 3 unexpected
        m_a, m_b = pair["metric_a"], pair["metric_b"]
        r, p = pair["r"], pair["p_value"]
        score = _statistical_impact(confidence=abs(r), p_value=p) * 0.7
        
        cards.append({
            "title": f"Unexpected Correlation: {m_a} vs {m_b}",
            "what_changed": f"Strong co-movement (r={r:+.3f}) between metrics with no declared dependency.",
            "why": f"Pearson r={r:+.3f}, p={p:.4f}. These metrics typically move independently.",
            "evidence": pair,
            "now_what": "Investigate if this correlation represents a new operational linkage or a data quality issue.",
            "priority": _priority_label(score),
            "impact_score": round(score, 4),
            "materiality_weight": 1.0,
            "tags": ["unexpected_correlation", "cross_metric"],
        })

    # 2. Operational-Financial Link Card (Strongest Expected)
    expected_pairs = [p for p in significant_pairs if p["expected"]]
    if expected_pairs:
        # Sort by r magnitude
        expected_pairs.sort(key=lambda x: abs(x["r"]), reverse=True)
        top_link = expected_pairs[0]
        m_a, m_b = top_link["metric_a"], top_link["metric_b"]
        r = top_link["r"]
        score = _statistical_impact(confidence=abs(r)) * 0.5
        
        cards.append({
            "title": f"Operational Link: {m_a} and {m_b}",
            "what_changed": f"Confirmed linkage (r={r:+.3f}) between operational and financial signals.",
            "why": f"{top_link['relationship'] or 'Expected relationship confirmed'}.",
            "evidence": top_link,
            "now_what": "Use this linkage to forecast financial outcomes based on operational leading indicators.",
            "priority": _priority_label(score),
            "impact_score": round(score, 4),
            "materiality_weight": 1.0,
            "tags": ["operational_link", "cross_metric"],
        })

    # 3. Correlation Breakdown Card
    if dimension_outliers:
        outlier = dimension_outliers[0]
        score = 0.6 # High priority for breakdown
        cards.append({
            "title": f"Correlation Breakdown: {outlier['dimension_value']}",
            "what_changed": f"{outlier['metric_a']} decoupled from {outlier['metric_b']} at this entity.",
            "why": f"Population r={outlier['population_r']} vs Entity r={outlier['r']}. {outlier['deviation']}.",
            "evidence": outlier,
            "now_what": "Investigate why this entity's operational-financial relationship differs from the rest of the network.",
            "priority": _priority_label(score),
            "impact_score": round(score, 4),
            "materiality_weight": 0.8,
            "tags": ["correlation_breakdown", "outlier"],
        })
        
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

def _build_variance_decomposition_cards(variance_data: dict) -> list[dict]:
    """
    Build insight cards from variance decomposition data.
    """
    if not isinstance(variance_data, dict) or "dimension_contributions" not in variance_data:
        return []
    
    contributions = variance_data.get("dimension_contributions", [])
    interactions = variance_data.get("interaction_effects", [])
    
    cards = []
    
    # 1. Dominant Dimension Card
    if contributions:
        top_dim = contributions[0]
        dim_name = top_dim["dimension"]
        eta_sq = top_dim["eta_squared"]
        score = min(eta_sq * 0.8, 0.7)
        
        cards.append({
            "title": f"Primary Variance Driver: {dim_name}",
            "what_changed": f"{dim_name} explains {eta_sq:.1%} of total variance.",
            "why": f"Statistical decomposition identifies {dim_name} as the most impactful dimension for performance variation.",
            "evidence": top_dim,
            "now_what": f"Prioritize {dim_name}-level analysis and strategy to address the majority of performance variance.",
            "priority": _priority_label(score),
            "impact_score": round(score, 4),
            "materiality_weight": 1.0,
            "tags": ["variance_driver", "anova"],
        })
        
    # 2. Interaction Effect Card
    if interactions:
        top_interaction = interactions[0]
        if top_interaction["eta_squared"] >= 0.05: # At least 5% variance
            dims = top_interaction["dimensions"]
            eta_sq = top_interaction["eta_squared"]
            score = min(eta_sq * 1.5, 0.6)
            
            cards.append({
                "title": f"Interaction Effect: {' x '.join(dims)}",
                "what_changed": f"Combinations of {', '.join(dims)} explain {eta_sq:.1%} of variance beyond individual effects.",
                "why": f"Performance is significantly driven by specific overlaps between these dimensions.",
                "evidence": top_interaction,
                "now_what": "Look for specific combinations (e.g., particular LOBs at certain terminals) that deviate from expected performance.",
                "priority": _priority_label(score),
                "impact_score": round(score, 4),
                "materiality_weight": 0.8,
                "tags": ["interaction_effect", "anova"],
            })
            
    # 3. Residual Variance Card (if high)
    residual_pct = variance_data.get("residual_variance_pct", 0.0)
    if residual_pct >= 0.4:
        score = 0.4
        cards.append({
            "title": "High Unexplained Variance",
            "what_changed": f"{residual_pct:.1%} of variance is not explained by the analyzed dimensions.",
            "why": "Temporal noise or missing factors (e.g., weather, fuel prices, macro events) are driving a large portion of movement.",
            "evidence": {"residual_variance_pct": residual_pct},
            "now_what": "Consider if additional data dimensions should be brought into the analysis.",
            "priority": "medium",
            "impact_score": score,
            "materiality_weight": 0.5,
            "tags": ["unexplained_variance", "anova"],
        })
        
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

def _build_distribution_cards(distribution_data: dict) -> list[dict]:
    """
    Build insight cards from distribution shape analysis data.
    """
    if not isinstance(distribution_data, dict):
        return []
    
    cards = []
    
    # 1. Non-Normal Distribution Card
    non_normal = distribution_data.get("summary", {}).get("non_normal_count", 0)
    total = distribution_data.get("summary", {}).get("items_analyzed", 0)
    if total > 0 and non_normal / total >= 0.5:
        score = 0.4
        cards.append({
            "title": f"Non-Normal Distributions: {non_normal} of {total} items",
            "what_changed": f"Majority of analyzed items ({non_normal/total:.0%}) exhibit non-normal distributions.",
            "why": f"Dominant pattern is {distribution_data.get('summary', {}).get('dominant_classification', 'N/A')}.",
            "evidence": distribution_data.get("summary", {}),
            "now_what": "Z-score-based anomalies may produce false positives/negatives for these items; prioritize MAD-based detection.",
            "priority": "medium",
            "impact_score": score,
            "materiality_weight": 1.0,
            "tags": ["distribution", "data_quality"],
        })

    # 2. Bimodal Pattern Card
    cs = distribution_data.get("cross_sectional", {})
    bimodal = cs.get("bimodal", {})
    if bimodal.get("detected"):
        score = 0.6
        cards.append({
            "title": f"Bimodal Pattern in {cs.get('latest_period')}",
            "what_changed": f"Metric distribution shows multiple distinct operating modes or clusters.",
            "why": bimodal.get("interpretation", ""),
            "evidence": bimodal,
            "now_what": "Analyze clusters separately to identify different performance profiles or customer segments.",
            "priority": "high",
            "impact_score": score,
            "materiality_weight": 1.0,
            "tags": ["distribution", "bimodal"],
        })

    # 3. Heavy Tails / Extreme Kurtosis Card
    item_dists = distribution_data.get("item_distributions", [])
    heavy_tailed = [d for d in item_dists if "heavy_tailed" in d.get("classification", "")]
    if heavy_tailed:
        top_heavy = sorted(heavy_tailed, key=lambda x: x.get("excess_kurtosis", 0), reverse=True)[0]
        score = 0.5
        cards.append({
            "title": f"Heavy-Tailed Distribution: {top_heavy.get('item_name')}",
            "what_changed": f"Extreme values are more likely than a normal distribution predicts (kurtosis={top_heavy.get('excess_kurtosis')}).",
            "why": "Current outlier thresholds may be too conservative for this item.",
            "evidence": top_heavy,
            "now_what": "Use robust statistical methods (like MAD) to evaluate outliers for this item.",
            "priority": "medium",
            "impact_score": score,
            "materiality_weight": 0.8,
            "tags": ["distribution", "outlier_risk"],
        })
        
    return cards

def _build_cross_dimension_cards(cross_dim_data: dict | None) -> list[dict]:
    """Build insight cards from cross-dimension analysis results."""
    if not cross_dim_data or not isinstance(cross_dim_data, dict):
        return []

    cards: list[dict] = []

    for key, cd_result in cross_dim_data.items():
        if not isinstance(cd_result, dict) or cd_result.get("skipped") or cd_result.get("error"):
            continue

        aux_name = cd_result.get("auxiliary_dimension", key)
        summary = cd_result.get("summary", {})
        independence = cd_result.get("independence_test", {})

        # 1. Interaction effect card
        if summary.get("interaction_significant"):
            eta = independence.get("interaction_eta_squared", 0)
            p_val = independence.get("interaction_p_value", 1.0)
            interp = independence.get("interpretation", "")
            hier_col = cd_result.get("hierarchy_dimension", "hierarchy")

            score = min(0.3 + eta * 2.0, 0.9)
            cards.append({
                "title": f"Interaction Effect: {hier_col} x {aux_name}",
                "what_changed": (
                    f"The {hier_col} x {aux_name} interaction explains "
                    f"{eta:.0%} of variance beyond main effects (p={p_val:.4f})."
                ),
                "why": interp,
                "evidence": {
                    "hierarchy_eta_sq": independence.get("hierarchy_eta_squared"),
                    "auxiliary_eta_sq": independence.get("auxiliary_eta_squared"),
                    "interaction_eta_sq": eta,
                    "interaction_p": p_val,
                },
                "now_what": (
                    f"Investigate specific {hier_col}-{aux_name} combinations "
                    f"that deviate from expectations."
                ),
                "priority": _priority_label(score),
                "impact_score": score,
                "materiality_weight": 1.0,
                "tags": ["cross_dimension", "interaction", "anova"],
            })

        # 2. Cross-cutting drag/boost cards
        for pattern in cd_result.get("cross_cutting_patterns", [])[:3]:
            aux_val = pattern.get("auxiliary_value", "Unknown")
            direction = pattern.get("effect_direction", "negative")
            mean_pct = pattern.get("mean_impact_pct", 0)
            n_affected = pattern.get("affected_entity_count", 0)
            consistency = pattern.get("consistency", 0)
            affected = pattern.get("affected_entities", [])

            score = min(0.2 + abs(mean_pct) / 50.0 + consistency * 0.3, 0.9)
            tag = "cross_cutting_drag" if direction == "negative" else "cross_cutting_boost"

            cards.append({
                "title": f"Cross-Cutting {'Drag' if direction == 'negative' else 'Boost'}: {aux_val}",
                "what_changed": pattern.get("label", f"{aux_val} impacts {n_affected} entities"),
                "why": (
                    f"{aux_val} consistently {'underperforms' if direction == 'negative' else 'outperforms'} "
                    f"across {n_affected} entities ({consistency:.0%} consistency)."
                ),
                "evidence": {
                    "auxiliary_value": aux_val,
                    "mean_impact_pct": mean_pct,
                    "affected_entities": affected[:5],
                    "consistency": consistency,
                },
                "now_what": (
                    f"Investigate {aux_val}-level factors that may be "
                    f"{'dragging' if direction == 'negative' else 'boosting'} "
                    f"performance across entities."
                ),
                "priority": _priority_label(score),
                "impact_score": score,
                "materiality_weight": 1.0,
                "tags": ["cross_dimension", tag],
            })

        # 3. Trend divergence cards
        for trend in cd_result.get("trends", [])[:2]:
            aux_val = trend.get("auxiliary_value", "Unknown")
            slope = trend.get("slope_per_period", 0)
            r_sq = trend.get("r_squared", 0)
            direction = trend.get("direction", "flat")

            score = min(0.3 + r_sq * 0.4, 0.8)
            cards.append({
                "title": f"Trend Divergence: {aux_val}",
                "what_changed": trend.get("label", f"{aux_val} {direction}"),
                "why": (
                    f"{aux_val} trend ({slope:+,.0f}/period, R-sq={r_sq:.2f}) "
                    f"is diverging from the overall network trend."
                ),
                "evidence": {
                    "auxiliary_value": aux_val,
                    "slope": slope,
                    "r_squared": r_sq,
                    "vs_overall": trend.get("vs_overall_trend"),
                },
                "now_what": f"Monitor {aux_val} as a leading indicator of broader changes.",
                "priority": _priority_label(score),
                "impact_score": score,
                "materiality_weight": 0.9,
                "tags": ["cross_dimension", "trend_divergence"],
            })

    return cards
