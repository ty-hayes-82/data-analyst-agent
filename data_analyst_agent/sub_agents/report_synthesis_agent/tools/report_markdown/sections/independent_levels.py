"""Independent level findings section."""

from __future__ import annotations

from typing import List

from ..formatting import is_skip_card
from ..parsing import collect_insight_cards, parse_json_safe


def build_independent_levels_section(independent_level_results: dict | None, condensed: bool) -> List[str]:
    if condensed or not independent_level_results:
        return []

    total_cards = 0
    sections: List[tuple[str, list]] = []

    for key in sorted(independent_level_results.keys()):
        level_data = independent_level_results[key]
        if isinstance(level_data, str):
            level_data = parse_json_safe(level_data)
        if not isinstance(level_data, dict):
            continue
        cards = [c for c in collect_insight_cards(level_data) if not is_skip_card(c)]
        if not cards:
            continue
        level_name = level_data.get("level_name", key)
        sections.append((level_name, cards))
        total_cards += len(cards)

    if total_cards == 0:
        return []

    lines: List[str] = ["## Independent Level Findings", ""]
    lines.append(
        "*These findings were discovered by flat-scanning individual hierarchy levels, bypassing the "
        "top-down drill-down gate. They represent anomalies that were masked at higher levels by "
        "offsetting data.*"
    )
    lines.append("")

    for level_name, cards in sections:
        lines.append(f"### {level_name} (independent scan)")
        for card in cards[:5]:
            priority = str(card.get("priority", "")).upper()
            title = card.get("title", card.get("item", ""))
            what = card.get("what_changed", "")
            prefix = f"[{priority}] " if priority else ""
            line = f"- **{prefix}{title}**"
            if what:
                line += f" — {what}"
            lines.append(line)
        lines.append("")

    return lines
