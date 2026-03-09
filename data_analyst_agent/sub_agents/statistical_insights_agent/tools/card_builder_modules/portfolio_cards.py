"""Card builders covering portfolio composition insights."""

from __future__ import annotations

from ..priority_engine import _priority_label

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
