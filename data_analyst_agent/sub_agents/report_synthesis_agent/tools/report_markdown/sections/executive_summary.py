"""Executive summary section builder."""

from __future__ import annotations

from typing import List, Optional

from ..formatting import format_variance


def build_executive_summary_section(
    *,
    narrative_summary: str,
    levels_analyzed: list[int],
    level_analyses: dict,
    drill_down_path: str,
    temporal_grain: str,
    lag_meta: Optional[dict],
    unit: str,
    target_name: str,
    metric_key: Optional[str] = None,
) -> List[str]:
    lines: List[str] = ["## Executive Summary", ""]

    if narrative_summary:
        lines.append(narrative_summary)
        lines.append("")

    shallowest_level = min(levels_analyzed) if levels_analyzed else None
    if shallowest_level is not None:
        lvl_data = level_analyses.get(f"level_{shallowest_level}", {})
        total_var = lvl_data.get("total_variance_dollar", 0)
        if total_var:
            lines.append(f"- **Total Variance:** {format_variance(total_var, unit, metric_key)}")

    if lag_meta:
        lag_periods = lag_meta.get("lag_periods", 0)
        eff_latest = lag_meta.get("effective_latest") or lag_meta.get("effective_latest_period")
        lines.append(
            f"- **Data Maturity:** Lagging ({lag_periods} periods lag, analysis through {eff_latest})"
        )

    lines.append(f"- **Analysis Depth:** {drill_down_path}")
    lines.append(f"- **Detected Temporal Grain:** {temporal_grain.title()}")
    lines.append("")
    return lines
