"""Variance drivers table section."""

from __future__ import annotations

from typing import List


def build_variance_section(levels_analyzed: list[int], level_analyses: dict) -> List[str]:
    if not levels_analyzed:
        return []
    deepest_level = max(levels_analyzed)
    deepest_analysis = level_analyses.get(f"level_{deepest_level}", {})
    drivers = deepest_analysis.get("top_drivers", [])
    if not drivers:
        return []

    lines: List[str] = ["## Variance Drivers", ""]
    lines.append("| Rank | Category/GL | Variance $ | Variance % | Materiality | Cumulative % |")
    lines.append("|------|-------------|------------|------------|-------------|--------------|")

    for driver in drivers[:10]:
        rank = driver.get("rank", "-")
        item = driver.get("item", "Unknown")
        var_dollar = driver.get("variance_dollar", 0)
        var_pct = driver.get("variance_pct")
        is_new = bool(driver.get("is_new_from_zero", False))
        materiality = driver.get("materiality", "LOW")
        cumulative = driver.get("cumulative_pct", 0)

        if is_new:
            pct_display = "new"
        elif var_pct is not None:
            pct_display = f"{var_pct:+.1f}%"
        else:
            pct_display = "N/A"

        lines.append(
            f"| {rank} | {item} | ${var_dollar:+,.0f} | {pct_display} | {materiality} | {cumulative:.1f}% |"
        )
    lines.append("")
    return lines
