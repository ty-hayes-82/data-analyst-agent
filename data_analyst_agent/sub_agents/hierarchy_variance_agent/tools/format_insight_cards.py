# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Code-based Hierarchy Insight Card Formatter -- relative-ranking approach.

Converts compute_level_statistics() output into ranked Insight Cards weighted
by each dimension's share of the total (materiality).  A 5% swing at a
500-truck terminal matters more than a 300% swing at a 2-truck terminal.

Cards are ranked by composite impact score; no hard dollar thresholds gate
card creation.
"""

from __future__ import annotations
import os
from typing import Any


def _max_cards_per_level() -> int:
    """Get maximum insight cards per hierarchy level from environment.
    
    Reads MAX_HIERARCHY_CARDS_PER_LEVEL environment variable. Default 5.
    Clamped to range [3, 20] for safety.
    
    Returns:
        int: Max cards per level (3-20).
    
    Example:
        >>> os.environ["MAX_HIERARCHY_CARDS_PER_LEVEL"] = "10"
        >>> _max_cards_per_level()
        10
    """
    raw = os.environ.get("MAX_HIERARCHY_CARDS_PER_LEVEL", "5").strip()
    try:
        return max(3, min(int(raw), 20))
    except ValueError:
        return 5


MAX_CARDS_PER_LEVEL = 15  # Legacy default; _max_cards_per_level() used at runtime
MIN_DRILL_IMPACT_SCORE = 0.15  # top insight must beat this to justify drill-down
MIN_VARIANCE_DOLLAR = 50_000.0
HIGH_VARIANCE_DOLLAR = 200_000.0
CRITICAL_VARIANCE_DOLLAR = 500_000.0
MIN_VARIANCE_PCT = 5.0
HIGH_VARIANCE_PCT = 10.0
CRITICAL_VARIANCE_PCT = 20.0


# ---------------------------------------------------------------------------
# Impact scoring helpers
# ---------------------------------------------------------------------------

def _magnitude_impact(variance_pct: float) -> float:
    """Score [0..1] based on percentage deviation magnitude."""
    return min(abs(variance_pct) / 50.0, 1.0)  # 50%+ = max


def _materiality_weight(item_current: float, total_current: float) -> float:
    """Weight by the item's share of the total.  Larger share = more impactful."""
    if total_current == 0 or item_current == 0:
        return 0.1
    share = abs(item_current) / abs(total_current)
    return min(0.1 + share * 3.0, 1.0)


def _composite_score(mag: float, mat: float, variance_dollar: float,
                     total_variance: float) -> float:
    """Combine magnitude, materiality, and dollar contribution into one score."""
    # Dollar contribution: how much of the total variance is this item?
    dollar_share = 0.0
    if total_variance != 0:
        dollar_share = min(abs(variance_dollar) / abs(total_variance), 1.0)

    raw = (mag * 0.3 + dollar_share * 0.3) * (0.3 + 0.7 * mat)
    return round(min(raw, 1.0), 4)


def _priority_from_score(score: float) -> str:
    if score >= 0.5:
        return "critical"
    if score >= 0.3:
        return "high"
    if score >= 0.15:
        return "medium"
    return "low"


def _is_material_variance(var_dollar: float, var_pct: float | None) -> bool:
    pct_val = abs(var_pct) if var_pct is not None else 0.0
    return abs(var_dollar) >= MIN_VARIANCE_DOLLAR or pct_val >= MIN_VARIANCE_PCT


def _priority_from_variance(var_dollar: float, var_pct: float | None) -> str:
    pct_val = abs(var_pct) if var_pct is not None else 0.0
    abs_dollar = abs(var_dollar)
    if pct_val >= CRITICAL_VARIANCE_PCT or abs_dollar >= CRITICAL_VARIANCE_DOLLAR:
        return "critical"
    if pct_val >= HIGH_VARIANCE_PCT or abs_dollar >= HIGH_VARIANCE_DOLLAR:
        return "high"
    if pct_val >= MIN_VARIANCE_PCT or abs_dollar >= MIN_VARIANCE_DOLLAR:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def format_hierarchy_insight_cards(
    level_stats: dict,
    pvm_data: dict | None = None,
    mix_data: dict | None = None,
    discovery_method: str | None = None,
) -> dict:
    """
    Convert compute_level_statistics() output into ranked Insight Cards.

    ALL items are considered as candidates, then ranked by composite impact
    (magnitude x materiality).  Top N are returned.
    """
    if not level_stats or not isinstance(level_stats, dict):
        return {"insight_cards": [], "total_variance_dollar": 0.0,
                "is_last_level": True, "level": 0, "level_name": "Unknown"}

    if "error" in level_stats:
        return {"error": level_stats["error"], "insight_cards": [],
                "total_variance_dollar": 0.0, "is_last_level": True,
                "level": level_stats.get("level", 0), "level_name": "Unknown"}

    level = level_stats.get("level", 0)
    level_name = level_stats.get("level_name", f"Level {level}")
    total_variance = level_stats.get("total_variance_dollar", 0.0)
    is_last_level = level_stats.get("is_last_level", False)
    top_drivers = level_stats.get("top_drivers", [])

    # Compute total current for materiality weighting
    total_current = sum(abs(d.get("current", 0.0)) for d in top_drivers)

    pvm_by_item: dict[str, dict] = {}
    if pvm_data and isinstance(pvm_data, dict) and "top_drivers" in pvm_data:
        for pvm_row in pvm_data["top_drivers"]:
            pvm_by_item[str(pvm_row.get("item", ""))] = pvm_row

    mix_by_item: dict[str, dict] = {}
    if mix_data and isinstance(mix_data, dict) and "segment_detail" in mix_data:
        for mix_row in mix_data["segment_detail"]:
            mix_by_item[str(mix_row.get("segment", ""))] = mix_row

    cards: list[dict] = []

    # 1. Add specific Mix Shift Card if applicable
    if mix_data and not mix_data.get("error"):
        decomp = mix_data.get("total_decomposition", {})
        mix_effect = decomp.get("mix_effect", 0.0)
        total_var = decomp.get("total_variance", 0.0)
        
        if total_var != 0 and abs(mix_effect) / abs(total_var) > 0.1:
            # Significant mix effect at aggregate level
            mag = min(abs(mix_effect) / abs(total_var), 1.0)
            score = round(mag * 0.6, 4) # Priority for mix shift
            
            blended = mix_data.get("blended_price", {})
            cards.append({
                "title": f"Mix Shift Impact: {level_name}",
                "what_changed": f"Portfolio mix shift drove {mix_effect:+,.2f} of total variance.",
                "why": mix_data.get("summary", {}).get("narrative", ""),
                "evidence": {
                    "mix_effect": round(mix_effect, 2),
                    "mix_pct_of_variance": round(mix_effect / abs(total_var) * 100, 1) if total_var != 0 else 0,
                    "blended_price_change": round(blended.get("change_total", 0), 4),
                    "change_from_mix": round(blended.get("change_from_mix", 0), 4),
                    "change_from_rate": round(blended.get("change_from_rate", 0), 4),
                },
                "now_what": "Investigate if shift toward different segments is intentional strategy or organic churn.",
                "priority": _priority_from_score(score),
                "impact_score": score,
                "materiality_weight": 1.0,
                "tags": ["mix_shift", "hierarchy"],
            })

    # 2. Add driver cards
    lag_meta = level_stats.get("lag_metadata")
    is_lagging = lag_meta is not None
    share_mode = os.environ.get("LAG_METRIC_SHARE_MODE", "true").lower() == "true"

    for driver in top_drivers:
        var_dollar = driver.get("variance_dollar", 0.0)
        var_pct = driver.get("variance_pct")  # May be None
        is_new = bool(driver.get("is_new_from_zero", False))

        if not _is_material_variance(var_dollar, var_pct):
            continue
        item = str(driver.get("item", ""))
        current = driver.get("current", 0.0)
        prior = driver.get("prior", 0.0)
        cumulative_pct = driver.get("cumulative_pct", 0.0)
        
        share_cur = driver.get("share_current", 0.0)
        share_pri = driver.get("share_prior", 0.0)
        share_chg = driver.get("share_change", 0.0)
        
        direction = "unfavorable" if var_dollar < 0 else "favorable"

        # Magnitude impact: use 100% for new items
        if is_new or var_pct is None:
            mag = 1.0
        else:
            mag = _magnitude_impact(var_pct)
            
        mat = _materiality_weight(current, total_current)
        score = _composite_score(mag, mat, var_dollar, total_variance)
        priority_label = _priority_from_variance(var_dollar, var_pct)

        evidence: dict[str, Any] = {
            "variance_dollar": round(var_dollar, 2),
            "variance_pct": round(var_pct, 2) if var_pct is not None else None,
            "is_new_from_zero": is_new,
            "current": round(current, 2),
            "prior": round(prior, 2),
            "share_current": round(share_cur, 4),
            "share_prior": round(share_pri, 4),
            "share_change_pp": round(share_chg * 100, 2),
            "cumulative_variance_explained_pct": round(cumulative_pct, 2),
            "share_of_total": round(abs(current) / total_current, 4) if total_current else 0.0,
            "is_pvm": False,
        }

        pvm_row = pvm_by_item.get(item)
        mix_row = mix_by_item.get(item)
        
        if is_lagging and share_mode:
            title = f"{level_name} Share Shift: {item}"
            dir_str = "increased" if share_chg > 0 else "decreased"
            what_changed = f"Share of {level_stats.get('metric', 'metric')} {dir_str} from {share_pri:.1%} to {share_cur:.1%} ({share_chg*100:+.1f}pp)"
            why_note = f"Relative share analysis prioritized for lagging metric."
        else:
            title = f"Level {level} Variance Driver: {item}"
            if is_new:
                what_changed = f"Variance of {var_dollar:+,.2f} (new from zero baseline)"
            elif var_pct is not None:
                what_changed = f"Variance of {var_dollar:+,.2f} ({var_pct:+.1f}%)"
            else:
                what_changed = f"Variance of {var_dollar:+,.2f}"
            why_note = f"Aggregated {direction} impact at the {level_name} level."
        
        if pvm_row or mix_row:
            evidence["is_pvm"] = True
            
            # If we have 3-factor mix data, prioritize it over 2-factor PVM
            if mix_row:
                vol_impact = mix_row.get("volume_current", 0.0) - mix_row.get("volume_prior", 0.0) # simplified
                # For the individual segment, we'll just show its own contribution to the mix effect
                mix_contrib = mix_row.get("contribution_to_mix_effect", 0.0)
                
                evidence["mix_details"] = {
                    "weight_change": round(mix_row.get("weight_change", 0), 4),
                    "mix_contribution": round(mix_contrib, 2),
                    "current_rate": round(mix_row.get("current_rate", 0), 2),
                }
                
                # Check if it's a significant mix driver
                if abs(mix_contrib) > 0.1 * abs(var_dollar):
                    why_note = f"Mix shift: weight changed from {mix_row.get('prior_weight',0):.1%} to {mix_row.get('current_weight',0):.1%}."
            
            elif pvm_row:
                vol_impact = pvm_row.get("volume_impact", 0.0)
                price_impact = pvm_row.get("price_impact", 0.0)
                residual = pvm_row.get("residual", 0.0)
                evidence["pvm_details"] = {
                    "volume_impact": round(vol_impact, 2),
                    "price_impact": round(price_impact, 2),
                    "residual": round(residual, 2),
                }
                dominant = "volume" if abs(vol_impact) >= abs(price_impact) else "price"
                why_note = (
                    f"PVM: Volume {vol_impact:+,.2f} / Price {price_impact:+,.2f}. "
                    f"{dominant.capitalize()} effect is dominant."
                )

        card: dict[str, Any] = {
            "title": title,
            "what_changed": what_changed,
            "why": why_note,
            "evidence": evidence,
            "now_what": (
                "Drill down to next level or investigate specific driver."
                if not is_last_level
                else "Review detail-level data for this item."
            ),
            "priority": priority_label,
            "impact_score": score,
            "materiality_weight": round(mat, 3),
            "tags": ["hierarchy", "variance"] + (["pvm"] if pvm_row else []) + (["mix_shift"] if mix_row else []),
            "lag_metadata": lag_meta,
        }
        cards.append(card)

    # Rank by impact score, take top N
    cards.sort(key=lambda c: -c.get("impact_score", 0.0))
    top_cards = cards[: _max_cards_per_level()]

    # Tag all cards with discovery_method when provided
    if discovery_method is not None:
        for card in top_cards:
            card.setdefault("discovery_method", discovery_method)

    result = {
        "insight_cards": top_cards,
        "total_variance_dollar": round(total_variance, 2),
        "is_last_level": is_last_level,
        "level": level,
        "level_name": level_name,
        "total_candidates": len(cards),
    }

    if isinstance(level_stats, dict):
        if level_stats.get("is_duplicate"):
            result["is_duplicate"] = True
        if level_stats.get("skip_reason"):
            result["skip_reason"] = level_stats.get("skip_reason")
        if level_stats.get("dimension_filter_applied"):
            result["dimension_filter_applied"] = True
        if level_stats.get("filter_value") is not None:
            result["filter_value"] = level_stats.get("filter_value")
        if level_stats.get("dimension"):
            result["dimension"] = level_stats.get("dimension")

    return result


# ---------------------------------------------------------------------------
# Drill-down decision function
# ---------------------------------------------------------------------------

def should_continue_drilling(
    level_result: dict,
    current_level: int,
    max_depth: int,
) -> dict:
    """
    Determine whether to drill down based on whether top-level findings
    have sufficient impact to warrant deeper investigation.

    Criteria:
      - At least one insight card with impact_score >= MIN_DRILL_IMPACT_SCORE
      - Not at last level or max depth
      - Not a duplicate level
    """
    is_last_level = level_result.get("is_last_level", False)
    is_duplicate = level_result.get("is_duplicate", False)

    if is_last_level:
        return {"action": "STOP", "reasoning": "Reached last level of the hierarchy.",
                "material_variances": [], "next_level": None}

    if is_duplicate:
        return {"action": "STOP", "reasoning": f"Level {current_level} is a duplicate.",
                "material_variances": [], "next_level": None}

    if current_level >= max_depth - 1:
        return {"action": "STOP", "reasoning": f"Reached max drill depth ({max_depth}).",
                "material_variances": [], "next_level": None}

    insight_cards = level_result.get("insight_cards", [])
    high_impact_items = [
        c.get("title", "").split(": ", 1)[-1]
        for c in insight_cards
        if (
            c.get("impact_score", 0.0) >= MIN_DRILL_IMPACT_SCORE
            or str(c.get("priority", "")).lower() in {"high", "critical"}
        )
    ]

    if high_impact_items:
        return {
            "action": "CONTINUE",
            "reasoning": (
                f"Found {len(high_impact_items)} high-impact items at level {current_level}. "
                f"Drilling to level {current_level + 1} for deeper investigation."
            ),
            "material_variances": high_impact_items,
            "next_level": current_level + 1,
        }

    return {
        "action": "STOP",
        "reasoning": f"No high-impact findings at level {current_level}. Drill-down not warranted.",
        "material_variances": [],
        "next_level": None,
    }
