"""Card builders for variance decomposition and distribution analysis."""

from __future__ import annotations

from ..priority_engine import _priority_label

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
