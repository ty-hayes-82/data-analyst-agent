"""Hierarchical drill-down section builder."""

from __future__ import annotations

from typing import List

from ..formatting import format_variance, is_skip_card
from ..parsing import collect_insight_cards


def _resolve_level_name(level_data: dict, level_idx: int) -> str:
    raw = str(level_data.get("level_name", "")).strip() if isinstance(level_data, dict) else ""
    if raw:
        return raw
    return "Total" if level_idx == 0 else f"Level {level_idx}"


def build_hierarchy_section(
    *,
    levels_analyzed: list[int],
    level_analyses: dict,
    drill_down_path: str,
    unit: str,
    target_name: str,
    condensed: bool,
) -> List[str]:
    if condensed:
        return []

    lines: List[str] = ["## Hierarchical Drill-Down Path", "", f"Analysis Path: **{drill_down_path}**", ""]

    for level in levels_analyzed:
        level_key = f"level_{level}"
        level_data = level_analyses.get(level_key, {})
        level_name = _resolve_level_name(level_data, level)
        total_var = level_data.get("total_variance_dollar", 0)

        lines.append(f"### Level {level}: {level_name}")
        if total_var:
            lines.append(f"- **Total Variance:** {format_variance(total_var, unit, target_name)}")

        cards = [c for c in collect_insight_cards(level_data) if not is_skip_card(c)]
        if cards:
            for card in cards[:5]:
                priority = str(card.get("priority", "")).upper()
                title = card.get("title", card.get("item", ""))
                what = card.get("what_changed", "")
                prefix = f"[{priority}] " if priority else ""
                line = f"- **{prefix}{title}**"
                if what:
                    line += f" — {what}"
                lines.append(line)
        elif total_var:
            lines.append(f"- Total: {format_variance(total_var, unit, target_name)}")
        lines.append("")

    return lines
