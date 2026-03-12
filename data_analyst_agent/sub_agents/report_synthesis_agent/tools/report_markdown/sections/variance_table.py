"""Variance drivers table section."""

from __future__ import annotations

from typing import List

from ..formatting import format_variance, unit_display_label


def _recomputed_cumulative(drivers: list[dict], limit: int) -> List[float]:
    display = drivers[:limit]
    contributions = []
    for driver in display:
        try:
            contributions.append(abs(float(driver.get("variance_dollar", 0) or 0.0)))
        except (TypeError, ValueError):
            contributions.append(0.0)
    total = sum(contributions)
    if total <= 0:
        return [0.0 for _ in display]

    cumulative: List[float] = []
    running = 0.0
    for weight in contributions:
        running += weight / total * 100.0
        cumulative.append(min(running, 100.0))
    if cumulative:
        cumulative[-1] = 100.0
    return cumulative


def build_variance_section(levels_analyzed: list[int], level_analyses: dict, unit: str) -> List[str]:
    if not levels_analyzed:
        return []
    deepest_level = max(levels_analyzed)
    deepest_analysis = level_analyses.get(f"level_{deepest_level}", {})
    drivers = deepest_analysis.get("top_drivers", [])
    if not drivers:
        return []

    max_rows = 10
    recomputed = _recomputed_cumulative(drivers, max_rows)

    lines: List[str] = ["## Variance Drivers", ""]
    amount_label = unit_display_label(unit)
    if amount_label == "$":
        variance_header = "Variance $"
    elif amount_label:
        variance_header = f"Variance ({amount_label})"
    else:
        variance_header = "Variance"
    lines.append(f"| Rank | Category/GL | {variance_header} | Variance % | Materiality | Cumulative % |")
    lines.append("|------|-------------|------------|------------|-------------|--------------|")

    for idx, driver in enumerate(drivers[:max_rows]):
        rank = driver.get("rank", "-")
        item = driver.get("item", "Unknown")
        var_dollar = driver.get("variance_dollar", 0)
        var_pct = driver.get("variance_pct")
        is_new = bool(driver.get("is_new_from_zero", False))
        materiality = driver.get("materiality", "LOW")
        cumulative = recomputed[idx] if idx < len(recomputed) else float(driver.get("cumulative_pct", 0) or 0)

        if is_new:
            pct_display = "new"
        elif var_pct is not None:
            pct_display = f"{var_pct:+.1f}%"
        else:
            pct_display = "N/A"

        var_display = format_variance(var_dollar, unit)
        if var_dollar > 0 and not var_display.startswith("+"):
            var_display = f"+{var_display}"

        lines.append(
            f"| {rank} | {item} | {var_display} | {pct_display} | {materiality} | {cumulative:.1f}% |"
        )
    lines.append("")
    return lines
