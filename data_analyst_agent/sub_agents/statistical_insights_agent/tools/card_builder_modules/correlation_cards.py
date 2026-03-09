"""Card builders for correlation-based insights."""

from __future__ import annotations

from ..priority_engine import (
    _priority_label,
    _statistical_impact,
)

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
