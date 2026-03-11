"""Generate executive 1-pager markdown report from hierarchical analysis results."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from data_analyst_agent.utils.env_utils import parse_bool_env
from data_analyst_agent.utils.stub_guard import contains_stub_content

from data_analyst_agent.sub_agents.report_synthesis_agent.tools.report_markdown.formatting import resolve_unit
from data_analyst_agent.sub_agents.report_synthesis_agent.tools.report_markdown.parsing import (
    normalize_hierarchical_results,
    parse_json_safe,
)
from data_analyst_agent.sub_agents.report_synthesis_agent.tools.report_markdown.sections import (
    build_cross_dimension_section,
    build_data_quality_section,
    build_executive_summary_section,
    build_hierarchy_section,
    build_independent_levels_section,
    build_insight_cards_section,
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



def _humanize_metric_label(analysis_target: Optional[str], dataset_display_name: Optional[str], fallback: str) -> str:
    if analysis_target:
        label = analysis_target
        if label.startswith("metric_"):
            label = label.split("metric_", 1)[1]
        label = label.replace("_", " ").strip()
        return label.title() if label else fallback
    if dataset_display_name:
        return dataset_display_name
    return fallback


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "")
        cleaned = cleaned.replace("$", "")
        if cleaned.endswith("%"):
            cleaned = cleaned[:-1]
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _format_amount_short(value: Optional[float], unit: str) -> str:
    if value is None:
        return ""
    sign = "+" if value >= 0 else "-"
    abs_val = abs(value)
    if abs_val >= 1_000_000_000:
        scaled = abs_val / 1_000_000_000
        suffix = "B"
    elif abs_val >= 1_000_000:
        scaled = abs_val / 1_000_000
        suffix = "M"
    elif abs_val >= 1_000:
        scaled = abs_val / 1_000
        suffix = "K"
    else:
        scaled = abs_val
        suffix = ""
    precision = 0 if scaled >= 100 or suffix == "" else 1
    formatted = f"{scaled:,.{precision}f}{suffix}"
    prefix = "$" if unit == "currency" else ""
    return f"{sign}{prefix}{formatted}"


def _format_pct(value: Optional[float]) -> str:
    if value is None:
        return ""
    return f"{value:+.1f}%"


def _dimension_label(card: dict) -> str:
    candidates = (
        card.get("dimension"),
        card.get("item"),
        card.get("title"),
        card.get("name"),
    )
    for raw in candidates:
        if not raw:
            continue
        text = str(raw).strip()
        if not text:
            continue
        if ":" in text:
            text = text.split(":", 1)[-1].strip()
        if text:
            return text
    return "this driver"


def _compose_change_clause(amount_str: str, pct_str: str) -> str:
    if amount_str and pct_str:
        return f"{amount_str} ({pct_str})"
    return amount_str or pct_str or ""


_PLACEHOLDER_ACTIONS = {
    "drill down to next level or investigate specific driver.",
    "investigate top variance drivers and validate mitigation plans.",
    "investigate variance drivers",
}


def _looks_like_placeholder(action: str) -> bool:
    if not action:
        return True
    normalized = " ".join(action.strip().lower().split())
    if normalized in _PLACEHOLDER_ACTIONS:
        return True
    return len(normalized) < 24


def _variance_actions(final_cards: List[dict], metric_label: str, unit: str) -> List[str]:
    actions: List[str] = []
    for card in final_cards or []:
        evidence = card.get("evidence") or {}
        variance_amt = _safe_float(evidence.get("variance_dollar"))
        if variance_amt is None:
            variance_amt = _safe_float(evidence.get("variance_amount"))
        if variance_amt is None:
            variance_amt = _safe_float(card.get("variance_dollar"))
        variance_pct = _safe_float(evidence.get("variance_pct"))
        if variance_pct is None:
            variance_pct = _safe_float(card.get("variance_pct"))
        change_clause = _compose_change_clause(_format_amount_short(variance_amt, unit), _format_pct(variance_pct))
        if not change_clause:
            continue
        basis = variance_amt if variance_amt is not None else variance_pct or 0.0
        direction = "increase" if basis >= 0 else "decline"
        dimension = _dimension_label(card)
        reason = (card.get("why") or card.get("root_cause") or "").strip()
        reason_clause = f" Root cause: {reason}" if reason else ""
        actions.append(
            f"Investigate {dimension} – {change_clause} change in {metric_label}; validate drivers causing the {direction}.{reason_clause}"
        )
        if len(actions) >= 3:
            break
    return actions


def _anomaly_actions(stats_data: dict, metric_label: str, unit: str, period_label: str) -> List[str]:
    anomalies = stats_data.get("anomalies") if isinstance(stats_data, dict) else []
    actions: List[str] = []
    if not isinstance(anomalies, list):
        return actions
    for anomaly in anomalies:
        if not isinstance(anomaly, dict):
            continue
        item = anomaly.get("item") or anomaly.get("dimension") or anomaly.get("name")
        if not item:
            continue
        period = anomaly.get("period") or anomaly.get("window") or period_label
        value = _format_amount_short(_safe_float(anomaly.get("value") or anomaly.get("amount")), unit)
        z_score = _safe_float(anomaly.get("z_score") or anomaly.get("score"))
        z_clause = f" (z={z_score:.2f})" if z_score is not None else ""
        value_clause = f"; observed value {value}" if value else ""
        actions.append(
            f"Review {item} for data quality issues – anomaly flagged in {period}{z_clause}{value_clause} impacting {metric_label}."
        )
        if len(actions) >= 2:
            break
    return actions


def _parse_correlation_entry(entry: Any) -> Tuple[Optional[str], Optional[str], Optional[float]]:
    if isinstance(entry, dict):
        a = entry.get("metric_a") or entry.get("item_a") or entry.get("source")
        b = entry.get("metric_b") or entry.get("item_b") or entry.get("target")
        value = _safe_float(entry.get("correlation") or entry.get("value") or entry.get("r"))
        return a, b, value
    if isinstance(entry, (list, tuple)):
        if len(entry) == 2 and isinstance(entry[0], str):
            raw_pair = entry[0]
            value = _safe_float(entry[1])
            if isinstance(raw_pair, str) and "_vs_" in raw_pair:
                a, b = raw_pair.split("_vs_", 1)
            elif isinstance(raw_pair, str) and "/" in raw_pair:
                a, b = raw_pair.split("/", 1)
            else:
                parts = raw_pair.split()
                a = parts[0]
                b = parts[-1] if len(parts) > 1 else None
            return a, b, value
        if len(entry) == 2 and all(isinstance(v, str) for v in entry):
            return entry[0], entry[1], None
    return None, None, None


def _correlation_actions(stats_data: dict, metric_label: str) -> List[str]:
    correlations = stats_data.get("correlations") if isinstance(stats_data, dict) else []
    actions: List[str] = []
    if not correlations:
        return actions
    for entry in correlations:
        metric_a, metric_b, value = _parse_correlation_entry(entry)
        if not metric_a or not metric_b or value is None:
            continue
        direction = "positive" if value >= 0 else "negative"
        actions.append(
            f"Leverage {metric_a} / {metric_b} correlation (r={value:.2f}, {direction}) to improve {metric_label} forecasting and scenario planning."
        )
        if len(actions) >= 1:
            break
    return actions


def _trend_actions(stats_data: dict, metric_label: str, unit: str, period_label: str) -> List[str]:
    top_drivers = stats_data.get("top_drivers") if isinstance(stats_data, dict) else []
    actions: List[str] = []
    if not isinstance(top_drivers, list):
        return actions
    for driver in top_drivers:
        if not isinstance(driver, dict):
            continue
        slope = _safe_float(driver.get("slope_3mo") or driver.get("trend_slope") or driver.get("slope"))
        if slope is None or abs(slope) < 1e-9:
            continue
        direction = "upward" if slope > 0 else "downward"
        item = driver.get("item") or driver.get("dimension") or driver.get("name") or "Key driver"
        slope_clause = _format_amount_short(slope, unit)
        actions.append(
            f"Monitor {item} – {direction} trend over last 3 {period_label}s (slope {slope_clause} per {period_label}) to stay ahead of {metric_label} swings."
        )
        if len(actions) >= 1:
            break
    return actions


def _fallback_actions(metric_label: str) -> List[str]:
    return [
        f"Validate upstream data pipelines feeding {metric_label} before publishing executive reporting.",
        f"Align mitigation plans with owners of the largest unfavorable driver in {metric_label}.",
        f"Reforecast {metric_label} incorporating latest variance and trend signals.",
    ]


def _filtered_narrative_actions(narrative_data: dict) -> List[str]:
    if not isinstance(narrative_data, dict):
        return []
    raw_actions = narrative_data.get("recommended_actions") or []
    filtered: List[str] = []
    for action in raw_actions:
        if not isinstance(action, str):
            continue
        if _looks_like_placeholder(action):
            continue
        filtered.append(action.strip())
    return filtered


def _derive_contextual_actions(
    final_cards: List[dict],
    stats_data: dict,
    metric_label: str,
    unit: str,
    period_label: str,
) -> List[str]:
    actions: List[str] = []
    seen: set[str] = set()

    def _append_unique(candidate: str) -> None:
        normalized = " ".join(candidate.strip().split()).lower()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        actions.append(candidate.strip())

    for source in (
        _variance_actions(final_cards, metric_label, unit),
        _anomaly_actions(stats_data, metric_label, unit, period_label),
        _correlation_actions(stats_data, metric_label),
        _trend_actions(stats_data, metric_label, unit, period_label),
    ):
        for action in source:
            _append_unique(action)
            if len(actions) >= 5:
                return actions
    return actions


def _build_recommended_actions_section(
    narrative_data: dict,
    final_cards: List[dict],
    stats_data: dict,
    metric_label: str,
    unit: str,
    period_label: str,
) -> List[str]:
    lines = ["## Recommended Actions", ""]
    actions: List[str] = []
    seen: set[str] = set()

    def _append_unique(action: str) -> None:
        normalized = " ".join(action.strip().split()).lower()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        actions.append(action.strip())

    for action in _derive_contextual_actions(final_cards, stats_data, metric_label, unit, period_label):
        _append_unique(action)
        if len(actions) >= 5:
            break

    if len(actions) < 5:
        for action in _filtered_narrative_actions(narrative_data):
            _append_unique(action)
            if len(actions) >= 5:
                break

    if len(actions) < 3:
        for action in _fallback_actions(metric_label):
            _append_unique(action)
            if len(actions) >= 3:
                break

    if not actions:
        actions.append("Investigate top variance drivers and validate mitigation plans.")

    for idx, action in enumerate(actions[:5], start=1):
        lines.append(f"{idx}. {action}")
    lines.append("")
    return lines


def _build_summary_from_data(metric_label: str, period_label: str, stats_data: dict, final_cards: List[dict], unit: str) -> str:
    summary_stats = stats_data.get("summary_stats", {}) if isinstance(stats_data, dict) else {}
    variance_amt = _safe_float(summary_stats.get("variance_amount") or summary_stats.get("variance_dollar"))
    variance_pct = _safe_float(summary_stats.get("variance_pct"))
    change_clause = _compose_change_clause(_format_amount_short(variance_amt, unit), _format_pct(variance_pct))
    sentences: List[str] = []
    if change_clause:
        sentences.append(f"{metric_label} moved {change_clause} over the last {period_label}.")

    driver_bits: List[str] = []
    for card in final_cards[:2]:
        evidence = card.get("evidence", {}) if isinstance(card, dict) else {}
        amount = _safe_float((evidence or {}).get("variance_dollar") or card.get("variance_dollar"))
        pct = _safe_float((evidence or {}).get("variance_pct") or card.get("variance_pct"))
        clause = _compose_change_clause(_format_amount_short(amount, unit), _format_pct(pct))
        label = _dimension_label(card)
        driver_bits.append(f"{label} ({clause})" if clause else label)

    if driver_bits:
        driver_sentence = "Key drivers: " + ", ".join(driver_bits[:2]) + "."
        sentences.append(driver_sentence)

    anomalies = stats_data.get("anomalies") if isinstance(stats_data, dict) else None
    if isinstance(anomalies, list) and anomalies:
        count = min(len(anomalies), 3)
        noun = "anomalies" if count > 1 else "anomaly"
        sentences.append(f"{count} {noun} triggered monitoring during this period.")

    if not sentences:
        sentences.append(f"{metric_label} performance is stable but warrants monitoring despite missing narrative output.")
    return " ".join(sentences)


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
    dataset_display_name: Optional[str] = None,
    dataset_description: Optional[str] = None,
    independent_findings: Optional[str] = None,
) -> str:
    try:
        target_name = cost_center or analysis_target or dataset_display_name or "Network Total"
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
        unit = resolve_unit(dataset_display_name or target_name or "")
        default_label = dataset_display_name or "Executive Analysis"
        label = target_label or default_label
        dataset_label = dataset_display_name or label
        metric_label = _humanize_metric_label(analysis_target, dataset_display_name, target_name)
        condensed = parse_bool_env(os.environ.get("REPORT_CONDENSED", "0"))

        md: List[str] = []
        _append_header(md, label, target_name, analysis_period, cost_center)

        insight_lines, final_cards = build_insight_cards_section(narrative_cards, level_analyses, levels_analyzed)
        summary_text = narrative_summary
        if contains_stub_content(summary_text):
            summary_text = _build_summary_from_data(metric_label, period_label, stats_data, final_cards, unit)

        md.extend(
            build_executive_summary_section(
                narrative_summary=summary_text,
                levels_analyzed=levels_analyzed,
                level_analyses=level_analyses,
                drill_down_path=drill_down_path,
                temporal_grain=temporal_grain,
                lag_meta=lag_meta,
                unit=unit,
                target_name=target_name,
            )
        )

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

        independent_results: dict = {}
        if independent_findings:
            parsed_independent = parse_json_safe(independent_findings)
            if isinstance(parsed_independent, dict):
                independent_results = parsed_independent
        if not independent_results and isinstance(raw_results, dict):
            fallback_independent = raw_results.get("independent_level_results", {})
            if isinstance(fallback_independent, dict):
                independent_results = fallback_independent
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
                    # Dataset-agnostic context from example dimensions
                    bits = []
                    if isinstance(ex, dict):
                        for k, v in ex.items():
                            if v in (None, ""):
                                continue
                            bits.append(f"{k}={v}")
                            if len(bits) >= 4:
                                break
                    ctx_txt = (" (" + ", ".join(bits) + ")") if bits else ""
                    dev = float(a.get("deviation_pct") or 0.0)
                    derived_actions.append(
                        f"Investigate {sid} ({atype}){ctx_txt} and validate drivers behind {dev:+.1f}% deviation; propose mitigation/monitoring steps."
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

        md.extend(
            _build_recommended_actions_section(
                narrative_data=narrative_data,
                final_cards=final_cards,
                stats_data=stats_data,
                metric_label=metric_label,
                unit=unit,
                period_label=period_label,
            )
        )

        md.extend(
            build_data_quality_section(
                dataset_label=dataset_label,
                dataset_description=dataset_description,
                levels_analyzed=levels_analyzed,
                drill_down_path=drill_down_path,
                temporal_grain=temporal_grain,
                short_delta_label=short_delta_label,
                lag_meta=lag_meta,
            )
        )

        return "\n".join(md)

    except Exception as exc:  # pragma: no cover
        return f"# Error Generating Report\n\nError: {exc}"
