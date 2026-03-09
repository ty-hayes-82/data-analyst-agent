"""Insight cards section builder."""

from __future__ import annotations

import os
from typing import List, Tuple

from ..formatting import _DERIVED_TAGS, card_tags, is_skip_card
from ..parsing import collect_insight_cards

_PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _env_int(name: str, default: str, min_val: int, max_val: int) -> int:
    try:
        return max(min_val, min(int(os.environ.get(name, default)), max_val))
    except (ValueError, TypeError):
        return int(default)


def build_insight_cards_section(
    narrative_cards: list | None,
    level_analyses: dict,
    levels_analyzed: list[int],
) -> Tuple[List[str], List[dict]]:
    cards_source = narrative_cards or []
    if not cards_source and not level_analyses:
        return [], []

    max_primary = _env_int("MAX_TOP_CRITICAL_INSIGHTS", "5", 3, 10)
    max_derived = _env_int("MAX_DERIVED_INSIGHTS", "3", 0, 5)
    max_hierarchy_derived = _env_int("MAX_HIERARCHY_DRILLDOWN_INSIGHTS", "5", 0, 10)

    has_regional_narrative = any(
        bool(card_tags(card) & {"regional_distribution", "hierarchy", "regional_analysis"})
        for card in cards_source
        if isinstance(card, dict)
    )
    if has_regional_narrative:
        max_hierarchy_derived = 0

    sorted_cards = sorted(
        cards_source,
        key=lambda c: (
            _PRIORITY_ORDER.get(str(c.get("priority", "low")).lower(), 3),
            -c.get("impact_score", 0.0),
        ),
    )

    primary = [
        c
        for c in sorted_cards
        if str(c.get("priority", "")).lower() in ("critical", "high") and not is_skip_card(c)
    ][:max_primary]

    remaining = [c for c in sorted_cards if c not in primary]
    derived = [c for c in remaining if card_tags(c) & _DERIVED_TAGS and not is_skip_card(c)][:max_derived]

    hierarchy_derived = []
    for level in sorted(levels_analyzed):
        if level == 0:
            continue
        level_data = level_analyses.get(f"level_{level}", {})
        for card in collect_insight_cards(level_data):
            if is_skip_card(card):
                continue
            if card in primary or card in derived or card in hierarchy_derived:
                continue
            hierarchy_derived.append(card)
            if len(hierarchy_derived) >= max_hierarchy_derived:
                break
        if len(hierarchy_derived) >= max_hierarchy_derived:
            break

    combined_derived = derived + hierarchy_derived
    fallback_limit = max(0, 10 - len(primary) - len(combined_derived))
    fallback = [c for c in remaining if c not in derived and not is_skip_card(c)][:fallback_limit]

    final_cards = [
        c
        for c in (primary + combined_derived + fallback if (primary or combined_derived or fallback) else sorted_cards)
        if not is_skip_card(c)
    ]

    if not final_cards:
        return [], []

    lines: List[str] = ["## Insight Cards", ""]
    for card in final_cards:
        priority = str(card.get("priority", "low")).upper()
        title = card.get("title", "Untitled")
        what = card.get("what_changed", "")
        why = card.get("why", "")
        root_cause = card.get("root_cause", "")
        tags = ", ".join(card.get("tags", []))

        lines.append(f"### [{priority}] {title}")
        if root_cause:
            lines.append(f"**Root Cause:** {root_cause}")
        if what:
            lines.append(f"**What Changed:** {what}")
        if why:
            lines.append(f"**Why:** {why}")

        evidence = card.get("evidence", {})
        if isinstance(evidence, dict) and evidence:
            ev_parts = [f"{k}: {v}" for k, v in list(evidence.items())[:4]]
            lines.append(f"**Evidence:** {' | '.join(ev_parts)}")
        if tags:
            lines.append(f"**Tags:** {tags}")
        lines.append("")

    return lines, final_cards
