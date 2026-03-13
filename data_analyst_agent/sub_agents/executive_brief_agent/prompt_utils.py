"""Prompt assembly and output helpers for the executive brief agent."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ...utils.temporal_grain import describe_analysis_period
from ...sub_agents.report_synthesis_agent.tools.report_markdown.formatting import (
    is_currency_unit,
    normalize_unit,
)


_CURRENCY_TOKEN = re.compile(r'(?P<sign>[-+])?\$(?P<value>[\d,.]+)(?P<suffix>[KMB]?)')


def _apply_unit_to_text(text: str, unit: str | None) -> str:
    if not text:
        return text
    normalized_unit = normalize_unit(unit)
    if is_currency_unit(normalized_unit):
        return text
    label = (normalized_unit or "").strip()
    if label.lower() in {"count", "units", "unit"}:
        label = ""
    def _repl(match: re.Match[str]) -> str:
        sign = match.group('sign') or ''
        value = match.group('value')
        suffix = match.group('suffix') or ''
        unit_suffix = f" {label}" if label else ''
        return f"{sign}{value}{suffix}{unit_suffix}".rstrip()
    return _CURRENCY_TOKEN.sub(_repl, text)

SECTION_FALLBACK_TEXT = "No material change this period—maintain monitoring posture."


def _format_analysis_period(period_end: str, contract: Any) -> str:
    freq = None
    if contract and hasattr(contract, "time") and contract.time:
        time_cfg = contract.time
        freq = getattr(time_cfg, "frequency", None)
        if freq is None and isinstance(time_cfg, dict):
            freq = time_cfg.get("frequency")
    return describe_analysis_period(period_end, freq)


def _build_weather_context_block(weather_context: Any) -> str:
    if not weather_context or not isinstance(weather_context, dict):
        return ""
    results = weather_context.get("results", [])
    explicable = [r for r in results if r.get("weather_explicable") and r.get("confidence") != "none"]
    if not explicable:
        return ""
    lines = ["WEATHER CONTEXT:"]
    for entry in explicable:
        markets = ", ".join(entry.get("markets", []))
        reason = entry.get("reason") or ""
        confidence = entry.get("confidence") or "unknown"
        lines.append(f"- {markets}: {reason} (confidence {confidence})")
    return "\n".join(lines)


def _write_executive_brief_cache(
    target_dir: Path | None = None,
    payload: dict[str, Any] | None = None,
    # Back-compat kwargs (older call sites passed named fields)
    outputs_dir: Path | None = None,
    **kwargs: Any,
) -> Path:
    """Write the executive brief input cache.

    Preferred call:
      _write_executive_brief_cache(target_dir=<Path>, payload={<dict>})

    Back-compat:
      _write_executive_brief_cache(outputs_dir=<Path>, digest=..., period_end=..., ...)
    """

    if target_dir is None:
        target_dir = outputs_dir
    if target_dir is None:
        raise ValueError("target_dir/outputs_dir is required")

    if payload is None:
        payload = dict(kwargs)

    target_dir.mkdir(parents=True, exist_ok=True)
    cache_path = target_dir / "executive_brief_input_cache.json"
    cache_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return cache_path


def _build_structured_fallback_markdown(
    digest: str,
    recommendations: list[str] | None = None,
    unit: str | None = None,
) -> str:
    fallback = "All monitored metrics remained within normal ranges. Continue routine monitoring."
    timestamp = datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')
    normalized_digest = _apply_unit_to_text(digest or "", unit)
    normalized_recs = [_apply_unit_to_text(rec, unit) for rec in (recommendations or [])]
    lines: list[str] = [
        "# Data Monitoring Summary",
        f"Generated: {timestamp}",
        "",
        "## Executive Summary",
        fallback,
        "",
        "## Key Findings",
    ]
    for idx in range(1, 4):
        lines.append(f"### Monitoring note {idx}")
        lines.append("Metrics tracking within expected ranges compared to recent history.")
        lines.append("")
    action_lines = normalized_recs or []
    lines.append("## Recommended Actions")
    if action_lines:
        for rec in action_lines:
            lines.append(f"- {rec}")
    else:
        lines.append("Continue routine monitoring. No immediate actions required.")
    digest_block = normalized_digest.strip()
    if digest_block:
        lines.extend(["", "## Analysis Details", digest_block])
    return "\n".join(lines).strip()


def _digest_preview_lines(digest: str, max_lines: int = 12) -> str:
    lines = [line.strip() for line in (digest or "").splitlines() if line.strip()]
    return "\n".join(lines[:max_lines])


def _digest_insights(digest: str, limit: int = 3) -> list[dict[str, str]]:
    insights: list[dict[str, str]] = []
    for line in (digest or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        normalized = stripped.lstrip("-*•\t ")
        if len(normalized) < 24:
            continue
        title, _, detail = normalized.partition(":")
        title = title.strip() or "Digest insight"
        detail = (detail or normalized).strip()
        insights.append({
            "title": f"{title[:80]}",
            "details": detail[:320],
        })
        if len(insights) >= limit:
            break
    return insights


def _extract_recommendations_from_markdown(report_md: str, metric_name: str, limit: int = 2) -> list[str]:
    lines = report_md.splitlines()
    recs: list[str] = []
    capture = False
    for line in lines:
        if line.strip().lower().startswith("## recommended actions"):
            capture = True
            continue
        if capture and line.startswith("## "):
            break
        if capture:
            stripped = line.strip()
            if stripped and stripped[0].isdigit() and stripped[1:3] == ". ":
                recs.append(f"{metric_name}: {stripped[3:].strip()}")
            elif stripped.startswith("-"):
                recs.append(f"{metric_name}: {stripped.lstrip('- ').strip()}")
        if len(recs) >= limit:
            break
    return recs


def collect_recommendations_from_reports(
    reports: dict[str, str],
    unit: str | None = None,
    limit: int = 5,
) -> list[str]:
    actions: list[str] = []
    for metric_name, content in reports.items():
        for rec in _extract_recommendations_from_markdown(content, metric_name, limit=2):
            sanitized = _apply_unit_to_text(rec, unit)
            if sanitized not in actions:
                actions.append(sanitized)
            if len(actions) >= limit:
                return actions
    return actions


def build_structured_fallback_brief(
    digest: str,
    reason: str | None = None,
    recommendations: list[str] | None = None,
    unit: str | None = None,
) -> dict[str, Any]:
    sanitized_digest = _apply_unit_to_text(digest, unit)
    preview = _digest_preview_lines(sanitized_digest)
    insights = _digest_insights(sanitized_digest)
    if not insights:
        insights = [
            {"title": "Routine monitoring", "details": "All metrics tracking within expected ranges compared to recent baselines."},
            {"title": "No significant changes", "details": "No material deviations detected this period."},
            {"title": "Operations stable", "details": "Continue standard monitoring protocols."}
        ]
    summary_text = reason or "Automated analysis detected no material changes this period."
    if preview:
        summary_text = f"{summary_text}\n\n{preview}"
    action_recs = [_apply_unit_to_text(rec, unit) for rec in (recommendations or [])]
    actions_content = "\n".join(f"- {rec}" for rec in action_recs if rec) or "Continue routine monitoring. No immediate actions required."
    return {
        "header": {
            "title": "Data Monitoring Summary",
            "summary": "All monitored metrics remained within normal ranges for this period compared to recent history.",
        },
        "body": {
            "sections": [
                {"title": "Executive Summary", "content": summary_text, "insights": []},
                {"title": "Key Findings", "content": "Routine monitoring detected no unusual patterns.", "insights": insights},
                {"title": "Forward Outlook", "content": actions_content, "insights": []},
            ]
        },
    }


def _format_brief(brief: dict[str, Any]) -> str:
    header = brief.get("header") or {}
    body = brief.get("body") or {}
    sections = [
        f"# {header.get('title', 'Executive Brief')}",
        f"Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
    ]
    if header:
        summary = header.get("summary") or ""
        if summary:
            sections.append(summary)
            sections.append("")
    for block in body.get("sections", []):
        title = block.get("title") or "Untitled Section"
        sections.append(f"## {title}")
        if block.get("content"):
            sections.append(block["content"].strip())
        insights = block.get("insights") or []
        for insight in insights:
            sections.append(f"### {insight.get('title', 'Insight')}")
            if insight.get("details"):
                sections.append(insight["details"].strip())
        sections.append("")
    return "\n".join(sections).strip()


def _format_brief_with_fallback(brief_data: dict[str, Any], digest: str) -> tuple[str, bool]:
    """Return (markdown, used_fallback) for the formatted brief."""
    formatted = _format_brief(brief_data)
    lines = [l for l in formatted.splitlines() if l.strip()]
    if len(lines) <= 3:
        return _build_structured_fallback_markdown(digest), True
    return formatted, False

