"""Generate executive 1-pager markdown report from hierarchical analysis results."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from data_analyst_agent.utils.env_utils import parse_bool_env

from .report_markdown.formatting import resolve_unit
from .report_markdown.parsing import normalize_hierarchical_results, parse_json_safe
from .report_markdown.sections import (
    build_cross_dimension_section,
    build_data_quality_section,
    build_executive_summary_section,
    build_hierarchy_section,
    build_independent_levels_section,
    build_insight_cards_section,
    build_utilization_section,
    build_variance_section,
)


def _extract_levels(raw: Any, normalized: Dict[str, dict]) -> Tuple[Dict[str, dict], List[int], str]:
    if isinstance(raw, dict) and "level_analyses" in raw:
        level_analyses = raw.get("level_analyses", {}) or {}
        levels_analyzed = raw.get("levels_analyzed", []) or []
        drill_down_path = raw.get("drill_down_path", "N/A")
        return level_analyses, levels_analyzed, drill_down_path

    level_analyses: Dict[str, dict] = {}
    levels: List[int] = []
    for key, val in normalized.items():
        if not key.startswith("level_"):
            continue
        try:
            level_num = int(key.split("_")[1])
        except (IndexError, ValueError):
            continue
        parsed_val = val if isinstance(val, dict) else parse_json_safe(val)
        if not isinstance(parsed_val, dict):
            continue
        level_analyses[key] = parsed_val
        levels.append(level_num)

    levels = sorted(set(levels))
    drill_down_path = " -> ".join([f"Level {lvl}" for lvl in levels]) if levels else "N/A"
    return level_analyses, levels, drill_down_path


def _extract_lag_metadata(inputs: List[Any]) -> Optional[dict]:
    for raw in inputs:
        if not raw:
            continue
        parsed = parse_json_safe(raw)
        if not isinstance(parsed, dict):
            continue
        lag_meta = parsed.get("lag_metadata")
        if lag_meta:
            return lag_meta
        level_zero = parsed.get("level_0")
        if isinstance(level_zero, dict) and level_zero.get("lag_metadata"):
            return level_zero["lag_metadata"]
    return None


def _build_recommended_actions_section(narrative_data: dict, final_cards: List[dict]) -> List[str]:
    lines = ["## Recommended Actions", ""]
    actions: List[str] = []
    narrative_actions = narrative_data.get("recommended_actions") if isinstance(narrative_data, dict) else None
    if isinstance(narrative_actions, list):
        actions.extend([a for a in narrative_actions[:5] if a])

    if not actions and final_cards:
        for card in final_cards:
            action = card.get("now_what") or card.get("recommended_action")
            if action:
                actions.append(action)
            if len(actions) >= 5:
                break

    if not actions:
        actions.append("Investigate top variance drivers and validate mitigation plans.")

    for idx, action in enumerate(actions, start=1):
        lines.append(f"{idx}. {action}")
    lines.append("")
    return lines


def _parse_statistical_summary(statistical_summary: Any) -> dict:
    parsed = parse_json_safe(statistical_summary) if statistical_summary else {}
    return parsed if isinstance(parsed, dict) else {}


def _detect_temporal_labels(stats_data: dict) -> Tuple[str, str, str]:
    summary_stats = stats_data.get("summary_stats", {}) if isinstance(stats_data, dict) else {}
    metadata = stats_data.get("metadata", {}) if isinstance(stats_data, dict) else {}
    temporal_grain = summary_stats.get("temporal_grain") or metadata.get("temporal_grain") or "monthly"
    short_delta_label = "WoW" if temporal_grain == "weekly" else "MoM"
    period_label = "week" if temporal_grain == "weekly" else "month"
    return temporal_grain, short_delta_label, period_label


def _append_header(md: List[str], label: str, target_name: str, analysis_period: Optional[str], cost_center: Optional[str]) -> None:
    md.append(f"# {label} Report - {target_name}")
    md.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if analysis_period:
        md.append(f"**Period:** {analysis_period}")
    if cost_center:
        md.append(f"**Cost Center {target_name}**")
    md.append("")


async def generate_markdown_report(
    hierarchical_results: str,
    analysis_target: Optional[str] = None,
    analysis_period: Optional[str] = None,
    statistical_summary: Optional[str] = None,
    narrative_results: Optional[str] = None,
    target_label: Optional[str] = None,
    cost_center: Optional[str] = None,
    anomaly_indicators: Optional[str] = None,
    seasonal_decomposition: Optional[str] = None,
) -> str:
    try:
        target_name = cost_center or analysis_target or "unknown"
        raw_results = parse_json_safe(hierarchical_results)
        if not raw_results:
            return "# Error Generating Report\n\nError: Unable to parse hierarchical_results"

        normalized_results = normalize_hierarchical_results(raw_results)
        level_analyses, levels_analyzed, drill_down_path = _extract_levels(raw_results, normalized_results)

        narrative_data = parse_json_safe(narrative_results) if narrative_results else {}
        narrative_cards = narrative_data.get("insight_cards", []) if isinstance(narrative_data, dict) else []
        narrative_summary = narrative_data.get("narrative_summary", "") if isinstance(narrative_data, dict) else ""

        stats_data = _parse_statistical_summary(statistical_summary)
        temporal_grain, short_delta_label, period_label = _detect_temporal_labels(stats_data)

        lag_meta = _extract_lag_metadata([hierarchical_results, statistical_summary, narrative_results])
        unit = resolve_unit(target_name or "")
        label = target_label or "P&L Analysis"
        condensed = parse_bool_env(os.environ.get("REPORT_CONDENSED", "0"))

        md: List[str] = []
        _append_header(md, label, target_name, analysis_period, cost_center)

        md.extend(
            build_executive_summary_section(
                narrative_summary=narrative_summary,
                levels_analyzed=levels_analyzed,
                level_analyses=level_analyses,
                drill_down_path=drill_down_path,
                temporal_grain=temporal_grain,
                lag_meta=lag_meta,
                unit=unit,
                target_name=target_name,
            )
        )

        insight_lines, final_cards = build_insight_cards_section(narrative_cards, level_analyses, levels_analyzed)
        md.extend(insight_lines)

        md.extend(
            build_hierarchy_section(
                levels_analyzed=levels_analyzed,
                level_analyses=level_analyses,
                drill_down_path=drill_down_path,
                unit=unit,
                target_name=target_name,
                condensed=condensed,
            )
        )

        independent_results = raw_results.get("independent_level_results", {}) if isinstance(raw_results, dict) else {}
        md.extend(build_independent_levels_section(independent_results, condensed))

        cross_dim_results = raw_results.get("cross_dimension_results", {}) if isinstance(raw_results, dict) else {}
        md.extend(build_cross_dimension_section(cross_dim_results, condensed))

        md.extend(build_variance_section(levels_analyzed, level_analyses))

        # Optional explicit Anomalies + Seasonality sections (used by incremental E2E)
        if anomaly_indicators:
            anoms = parse_json_safe(anomaly_indicators)
            md.extend(["## Anomalies", ""])
            items = anoms.get("anomalies", []) if isinstance(anoms, dict) else []
            if items:
                for a in items[:10]:
                    sid = a.get("scenario_id")
                    atype = a.get("anomaly_type")
                    desc = a.get("ground_truth_insight") or a.get("description") or "Anomaly detected"
                    dev = float(a.get("deviation_pct") or 0.0)
                    md.append(f"- [{sid} | {atype}] {desc} (deviation {dev:+.1f}%)")
            else:
                md.append("- No anomalies available.")

            # If narrative didn’t provide actionable recommendations, derive them from anomaly scenarios.
            if isinstance(narrative_data, dict) and not narrative_data.get("recommended_actions") and items:
                derived_actions = []
                for a in items[:5]:
                    sid = a.get("scenario_id")
                    atype = a.get("anomaly_type")
                    ex = a.get("example") or {}
                    loc = "/".join([str(x) for x in (ex.get("state_name") or ex.get("state"), ex.get("port_name") or ex.get("port_code")) if x])
                    dev = float(a.get("deviation_pct") or 0.0)
                    derived_actions.append(
                        f"Investigate {sid} ({atype}) at {loc} and validate drivers behind {dev:+.1f}% deviation; propose mitigation/monitoring steps."
                    )
                narrative_data["recommended_actions"] = derived_actions

            md.append("")

        if seasonal_decomposition:
            seas = parse_json_safe(seasonal_decomposition)
            summary = seas.get("seasonality_summary") if isinstance(seas, dict) else None
            md.extend(["## Seasonality", ""])
            if isinstance(summary, dict) and summary:
                md.append(
                    f"- Peak month: {summary.get('peak_month')} | Trough month: {summary.get('trough_month')} | Amplitude: {float(summary.get('seasonal_amplitude_pct', 0)):.1f}%"
                )
            else:
                md.append("- No seasonality summary available.")
            md.append("")

        md.extend(_build_recommended_actions_section(narrative_data, final_cards))

        util_lines, util_meta = build_utilization_section(stats_data, period_label, short_delta_label)
        md.extend(util_lines)

        md.extend(
            build_data_quality_section(
                levels_analyzed=levels_analyzed,
                drill_down_path=drill_down_path,
                temporal_grain=temporal_grain,
                short_delta_label=short_delta_label,
                lag_meta=lag_meta,
                util_ratios=util_meta.get("util_ratios", []),
                util_summary=util_meta.get("util_summary", {}),
            )
        )

        return "\n".join(md)

    except Exception as exc:  # pragma: no cover
        return f"# Error Generating Report\n\nError: {exc}"
